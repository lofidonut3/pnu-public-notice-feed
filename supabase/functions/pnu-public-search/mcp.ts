import {
  type CallToolResult,
  createMcpHandler,
  McpServer,
} from "npm:@modelcontextprotocol/server@2.4.0";
import { z } from "npm:zod@4.6.7/v4";

export type McpToolName = "search_notices" | "get_notice" | "list_changes";
export type McpToolDispatch = (
  name: McpToolName,
  args: Record<string, unknown>,
) => Promise<Record<string, unknown>>;

export class McpToolError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
  }
}

const annotations = {
  readOnlyHint: true,
  destructiveHint: false,
  idempotentHint: true,
  openWorldHint: true,
};
const limit = z.int().min(1).max(20).optional().describe(
  "Maximum results on this page, from 1 to 20.",
);

function toolResult(data: Record<string, unknown>): CallToolResult {
  return {
    structuredContent: data,
    content: [{ type: "text", text: JSON.stringify(data) }],
  };
}

function createServer(dispatch: McpToolDispatch): McpServer {
  const server = new McpServer({
    name: "pnu-public-notice-feed",
    title: "PNU Public Notice Feed",
    version: "1.0.0",
  }, {
    capabilities: { tools: { listChanged: false } },
    instructions:
      "Read-only metadata for public Pusan National University notices. Search in Korean or English. Follow the official notice URL for eligibility, deadlines, full text, and attachments.",
  });

  function call(name: McpToolName) {
    return async (args: Record<string, unknown>): Promise<CallToolResult> => {
      try {
        return toolResult(await dispatch(name, args));
      } catch (error) {
        const details = error instanceof McpToolError
          ? { code: error.code, message: error.message }
          : { code: "internal_error", message: "The notice lookup failed." };
        return { ...toolResult({ error: details }), isError: true };
      }
    };
  }

  server.registerTool("search_notices", {
    title: "Search PNU notices",
    description:
      "Search public PNU notice metadata by keyword, topic, or publication date. Keep the same filters when requesting the next page.",
    annotations,
    inputSchema: z.strictObject({
      query: z.string().optional().describe("Keywords such as 국가장학금."),
      topic: z.string().min(1).optional().describe(
        "A feed topic ID such as scholarship, academic, or career.",
      ),
      published_from: z.iso.date().optional().describe(
        "First publication date to include, YYYY-MM-DD.",
      ),
      published_to: z.iso.date().optional().describe(
        "Last publication date to include, YYYY-MM-DD.",
      ),
      limit,
      cursor: z.string().min(1).optional().describe(
        "Opaque cursor returned by the preceding search page.",
      ),
    }),
  }, call("search_notices"));

  server.registerTool("get_notice", {
    title: "Get PNU notice metadata",
    description:
      "Fetch the archived metadata for one public notice using its ID and archive month from search or change results.",
    annotations,
    inputSchema: z.strictObject({
      notice_id: z.string().min(1).describe("Stable notice ID from the feed."),
      archive_month: z.string().regex(/^[0-9]{4}-(0[1-9]|1[0-2])$/).describe(
        "Archive month from the notice or event, YYYY-MM.",
      ),
    }),
  }, call("get_notice"));

  server.registerTool("list_changes", {
    title: "List PNU notice changes",
    description:
      "Read public notice changes. For polling, save the last successfully processed event ID and resume with it.",
    annotations,
    inputSchema: z.strictObject({
      after_event_id: z.string().min(1).optional().describe(
        "Exact event ID to resume after.",
      ),
      limit,
    }),
  }, call("list_changes"));

  return server;
}

export async function handleMcp(
  request: Request,
  dispatch: McpToolDispatch,
): Promise<Response> {
  const origin = request.headers.get("origin");
  if (origin !== null && origin !== new URL(request.url).origin) {
    return Response.json({
      jsonrpc: "2.0",
      error: { code: -32000, message: "Forbidden origin." },
    }, { status: 403 });
  }
  if (request.method !== "POST") {
    return new Response(null, { status: 405, headers: { allow: "POST" } });
  }
  const handler = createMcpHandler(() => createServer(dispatch), {
    maxRequestBodySize: 16 * 1024,
  });
  return await handler.fetch(request);
}
