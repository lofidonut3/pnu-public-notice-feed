import { createHandler } from "./index.ts";
import { createSearchService } from "./search.ts";

const BASE = "https://example.test/functions/v1/pnu-public-search";

async function fixture() {
  const rows = [1, 2, 3].map((id) => ({
    id: String(id),
    title: "장학금 신청",
    archive_month: "2026-09",
    published_at: id === 3 ? null : "2026-09-03",
    first_seen_at: "2026-09-04T03:00:00Z",
    source_name: "부산대학교",
    topics: ["scholarship"],
    preview: null,
  }));
  const body = JSON.stringify(rows);
  const bytes = new TextEncoder().encode(body);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const catalog = {
    schema_version: 1,
    checked_at: "2026-09-10T03:00:00Z",
    topics: ["scholarship"],
    months: [{
      month: "2026-09",
      size_bytes: bytes.length,
      published_from: "2026-09-03",
      published_to: "2026-09-03",
      undated_from: "2026-09-04",
      undated_to: "2026-09-04",
      sha256: new Uint8Array(digest).toHex(),
    }],
  };
  let shardBody = body;
  const fetchFeed = (url: string | URL | Request) =>
    Promise.resolve(
      String(url).endsWith("/search/catalog.json")
        ? Response.json(catalog)
        : new Response(shardBody),
    );
  const handle = createHandler(
    createSearchService("https://feed.test/", fetchFeed),
  );
  return {
    get: (path: string) => handle(new Request(BASE + path)),
    corrupt: () => {
      shardBody = body.replace("2026-09-03", "2026-09-04");
    },
  };
}

Deno.test("search cursor continues a stable ordering and rejects changed filters", async () => {
  const { get } = await fixture();
  const path = "/search?" +
    new URLSearchParams({
      query: "장학금",
      published_to: "2026-09-10",
      limit: "1",
    });
  const first = await (await get(path)).json();
  if (first.items[0].id !== "2" || !first.next_cursor) {
    throw new Error("Missing first page.");
  }
  const next = await (await get(path + "&cursor=" + first.next_cursor)).json();
  if (next.items[0].id !== "1" || next.next_cursor !== null) {
    throw new Error("Invalid second page.");
  }
  const stale = await get(
    path + "&topic=scholarship&cursor=" + first.next_cursor,
  );
  if (
    stale.status !== 409 ||
    (await stale.json()).error.code !== "search_cursor_changed"
  ) {
    throw new Error("Cursor accepted for different filters.");
  }
});

Deno.test("default search can find undated notices without assigning a publication date", async () => {
  const { get } = await fixture();
  const data = await (await get("/search?limit=1")).json();
  const item = data.items[0];
  if (item.id !== "3" || item.published_at !== null || !item.first_seen_at) {
    throw new Error("Missing or falsely dated notice.");
  }
});

Deno.test("search refuses a shard from another publication", async () => {
  const { get, corrupt } = await fixture();
  corrupt();
  const response = await get("/search");
  if (
    response.status !== 503 ||
    (await response.json()).error.code !== "feed_unavailable"
  ) {
    throw new Error(
      "Search returned metadata whose checksum does not match the catalog.",
    );
  }
});
