import assert from "node:assert/strict";
import {
  Client,
  StreamableHTTPClientTransport,
} from "npm:@modelcontextprotocol/client@2.4.0";
import { handleMcp, type McpToolDispatch, McpToolError } from "./mcp.ts";

const endpoint = new URL("https://example.com/pnu-public-search/mcp");

for (const era of ["modern", "legacy"] as const) {
  Deno.test(`official MCP client discovers and calls tools (${era})`, async () => {
    const calls: Array<Parameters<McpToolDispatch>> = [];
    const dispatch: McpToolDispatch = (name, args) => {
      calls.push([name, args]);
      return Promise.resolve({ name, ...args });
    };
    const client = new Client({ name: "pnu-mcp-test", version: "1.0.0" }, {
      ...(era === "modern" && {
        versionNegotiation: { mode: { pin: "2026-07-28" } },
      }),
    });
    const transport = new StreamableHTTPClientTransport(endpoint, {
      fetch: async (input, init) => {
        const response = await handleMcp(new Request(input, init), dispatch);
        assert.equal(response.headers.get("Mcp-Session-Id"), null);
        if (era === "modern" && response.status === 200) {
          assert.match(
            response.headers.get("content-type") ?? "",
            /^application\/json\b/,
          );
        }
        return response;
      },
    });

    try {
      await client.connect(transport);
      assert.equal(client.getProtocolEra(), era);
      const { tools } = await client.listTools();
      assert.deepEqual(tools.map(({ name }) => name).sort(), [
        "get_notice",
        "list_changes",
        "search_notices",
      ]);
      assert.ok(tools.every(({ annotations }) => annotations?.readOnlyHint));
      assert.deepEqual(
        tools.find(({ name }) => name === "get_notice")?.inputSchema.required,
        ["notice_id", "archive_month"],
      );

      const requests = [
        ["search_notices", {
          query: "국가장학금",
          topic: "scholarship",
          limit: 2,
        }],
        ["get_notice", { notice_id: "pnu:1", archive_month: "2026-11" }],
        ["list_changes", { after_event_id: "2026-11-10|added|pnu:1" }],
      ] as const;
      for (const [name, args] of requests) {
        const result = await client.callTool({ name, arguments: args });
        const expected = { name, ...args };
        assert.deepEqual(result.structuredContent, expected);
        assert.deepEqual(result.content, [{
          type: "text",
          text: JSON.stringify(expected),
        }]);
      }
      assert.deepEqual(calls, requests);
    } finally {
      await client.close();
    }
  });
}

Deno.test("invalid MCP inputs do not invoke a notice lookup", async () => {
  let dispatchCount = 0;
  const dispatch: McpToolDispatch = () => {
    dispatchCount += 1;
    return Promise.resolve({});
  };
  const client = new Client({ name: "pnu-mcp-test", version: "1.0.0" });
  const transport = new StreamableHTTPClientTransport(endpoint, {
    fetch: (input, init) => handleMcp(new Request(input, init), dispatch),
  });

  try {
    await client.connect(transport);
    for (
      const [name, args] of [
        ["search_notices", { limit: 21 }],
        ["search_notices", { published_from: "2026-02-30" }],
        ["get_notice", { notice_id: "pnu:1" }],
        ["get_notice", { notice_id: "pnu:1", archive_month: "2026-13" }],
        ["list_changes", { upstream_url: "https://example.org/" }],
      ] as const
    ) {
      const result = await client.callTool({ name, arguments: args });
      assert.equal(result.isError, true);
    }
    assert.equal(dispatchCount, 0);
  } finally {
    await client.close();
  }
});

Deno.test("MCP maps safe service failures and hides internal details", async () => {
  const dispatch: McpToolDispatch = (name) => {
    if (name === "get_notice") {
      return Promise.reject(new McpToolError("not_found", "Notice not found."));
    }
    return Promise.reject(new Error("private test detail"));
  };
  const client = new Client({ name: "pnu-mcp-test", version: "1.0.0" });
  const transport = new StreamableHTTPClientTransport(endpoint, {
    fetch: (input, init) => handleMcp(new Request(input, init), dispatch),
  });

  try {
    await client.connect(transport);
    const missing = await client.callTool({
      name: "get_notice",
      arguments: { notice_id: "pnu:1", archive_month: "2026-11" },
    });
    assert.equal(missing.isError, true);
    assert.deepEqual(missing.structuredContent, {
      error: { code: "not_found", message: "Notice not found." },
    });
    const failed = await client.callTool({ name: "search_notices" });
    assert.equal(failed.isError, true);
    assert.deepEqual(failed.structuredContent, {
      error: { code: "internal_error", message: "The notice lookup failed." },
    });
    assert.doesNotMatch(JSON.stringify(failed), /private test detail/);
  } finally {
    await client.close();
  }
});

Deno.test("MCP validates origins, HTTP methods, body size and protocol versions", async () => {
  const dispatch: McpToolDispatch = () =>
    assert.fail("Unexpected notice lookup");
  const foreignOrigin = await handleMcp(
    new Request(endpoint, {
      method: "POST",
      headers: { origin: "https://foreign.example.com" },
    }),
    dispatch,
  );
  assert.equal(foreignOrigin.status, 403);

  const get = await handleMcp(new Request(endpoint), dispatch);
  assert.equal(get.status, 405);
  assert.equal(get.headers.get("allow"), "POST");

  const oversized = await handleMcp(
    new Request(endpoint, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ unused: "a".repeat(16 * 1024) }),
    }),
    dispatch,
  );
  assert.equal(oversized.status, 413);

  const headers = {
    accept: "application/json, text/event-stream",
    "content-type": "application/json",
    origin: endpoint.origin,
  };
  const unknownVersion = await handleMcp(
    new Request(endpoint, {
      method: "POST",
      headers: { ...headers, "mcp-protocol-version": "2099-01-01" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "ping" }),
    }),
    dispatch,
  );
  assert.equal(unknownVersion.status, 400);
  await unknownVersion.body?.cancel();

  const notification = await handleMcp(
    new Request(endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "notifications/initialized",
      }),
    }),
    dispatch,
  );
  assert.equal(notification.status, 202);
  assert.equal(await notification.text(), "");
});
