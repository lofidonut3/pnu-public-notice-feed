import { handleMcp, McpToolError, type McpToolName } from "./mcp.ts";
import { createSearchService, FEED_URL, SearchError } from "./search.ts";

const NAME = "pnu-public-search";
const REST_HEADERS = {
  "access-control-allow-origin": "*",
  "cache-control": "no-store",
};
const ROUTES = {
  "/search": {
    tool: "search_notices",
    fields: [
      "query",
      "topic",
      "published_from",
      "published_to",
      "limit",
      "cursor",
    ],
  },
  "/notice": { tool: "get_notice", fields: ["notice_id", "archive_month"] },
  "/changes": { tool: "list_changes", fields: ["after_event_id", "limit"] },
} satisfies Record<string, { tool: McpToolName; fields: string[] }>;

export function createHandler(service = createSearchService()) {
  return async (request: Request): Promise<Response> => {
    const url = new URL(request.url);
    const route = url.pathname.replace(
      new RegExp(`^(?:/functions/v1)?/${NAME}(?=/|$)`),
      "",
    ).replace(/\/$/, "");
    if (route === "/mcp") {
      return await handleMcp(request, async (name, args) => {
        try {
          return await service[name](args);
        } catch (error) {
          if (error instanceof SearchError) {
            throw new McpToolError(error.code, error.message);
          }
          throw error;
        }
      });
    }
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          ...REST_HEADERS,
          "access-control-allow-methods": "GET, OPTIONS",
        },
      });
    }
    if (request.method !== "GET") {
      return new Response(null, {
        status: 405,
        headers: { ...REST_HEADERS, allow: "GET, OPTIONS" },
      });
    }

    try {
      if (route === "") {
        return Response.json({
          name: "PNU Public Notice Feed Search",
          feed_url: FEED_URL,
          openapi_url: new URL("search-api.json", FEED_URL).href,
          paths: ["search", "notice", "changes", "mcp"],
        }, { headers: REST_HEADERS });
      }
      const endpoint = ROUTES[route as keyof typeof ROUTES];
      if (!endpoint) {
        throw new SearchError(404, "not_found", "Unknown API path.");
      }
      if (url.search.length > 4096) {
        throw new SearchError(
          400,
          "invalid_argument",
          "Query string is too long.",
        );
      }
      const args: Record<string, unknown> = {};
      for (const [key, value] of url.searchParams) {
        if (!endpoint.fields.includes(key) || Object.hasOwn(args, key)) {
          throw new SearchError(
            400,
            "invalid_argument",
            "Unknown or repeated query parameter.",
          );
        }
        args[key] = key === "limit"
          ? (/^\d{1,2}$/.test(value) ? Number(value) : NaN)
          : value;
      }
      return Response.json(await service[endpoint.tool](args), {
        headers: REST_HEADERS,
      });
    } catch (error) {
      const safe = error instanceof SearchError
        ? error
        : new SearchError(500, "internal_error", "The notice lookup failed.");
      return Response.json({
        error: { code: safe.code, message: safe.message },
      }, {
        status: safe.status,
        headers: REST_HEADERS,
      });
    }
  };
}

if (import.meta.main) Deno.serve(createHandler());
