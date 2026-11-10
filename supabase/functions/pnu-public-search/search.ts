export const FEED_URL = "https://lofidonut3.github.io/pnu-public-notice-feed/";
const DAY_MS = 86_400_000;
const MAX_MONTH_BYTES = 8 * 1024 * 1024;
const MAX_SEARCH_BYTES = 24 * 1024 * 1024;
const MONTH_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/;
const SEOUL_DATE = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul" });

type Month = {
  month: string;
  published_from: string | null;
  published_to: string | null;
  undated_from: string | null;
  undated_to: string | null;
  size_bytes: number;
  sha256: string;
};
type Catalog = {
  schema_version: number;
  checked_at: string;
  topics: string[];
  months: Month[];
};
type Item = {
  id: string;
  title: string;
  archive_month: string;
  published_at: string | null;
  first_seen_at: string | null;
  source_name: string | null;
  topics: string[];
  preview: string | null;
};
type Events = {
  checked_at: string;
  events: Array<{ event_id: string; seen_at: string; archive_file: string }>;
};

export class SearchError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

function invalid(message: string): never {
  throw new SearchError(400, "invalid_argument", message);
}

function unavailable(): never {
  throw new SearchError(
    503,
    "feed_unavailable",
    "The public feed is temporarily unavailable. Retry shortly.",
  );
}

function optionalText(
  args: Record<string, unknown>,
  name: string,
  maxLength: number,
) {
  const value = args[name];
  if (value === undefined) return undefined;
  if (typeof value !== "string" || value.length > maxLength) {
    invalid(`${name} must be a string of up to ${maxLength} characters.`);
  }
  return value;
}

function dateValue(value: string): number {
  const ms = Date.parse(value);
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(ms) ||
    new Date(ms).toISOString().slice(0, 10) !== value
  ) invalid("Use a valid YYYY-MM-DD date.");
  return ms;
}

function pageSize(args: Record<string, unknown>): number {
  const limit = args.limit ?? 10;
  if (
    typeof limit !== "number" || !Number.isInteger(limit) || limit < 1 ||
    limit > 20
  ) {
    invalid("limit must be an integer from 1 to 20.");
  }
  return limit;
}

function normalize(value: string): string {
  return value.normalize("NFKC").toLowerCase().trim();
}

function noticeDate(item: Item, includeUndated: boolean) {
  return item.published_at ??
    (includeUndated ? item.first_seen_at?.slice(0, 10) : undefined);
}

async function hash(data: Uint8Array<ArrayBuffer>) {
  const bytes = await crypto.subtle.digest("SHA-256", data);
  return Array.from(
    new Uint8Array(bytes),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
}

function decodeCursor(cursor: string) {
  const [signature, offset] = cursor.split(".");
  if (!/^[a-f0-9]{64}\.[1-9]\d{0,7}$/.test(cursor)) {
    invalid("Invalid search cursor.");
  }
  return { signature, offset: Number(offset) };
}

export function createSearchService(feedUrl = FEED_URL, fetchFeed = fetch) {
  const feed = (path: string) => new URL(path, feedUrl).href;

  async function read<T>(
    path: string,
    maxBytes: number,
    signal: AbortSignal,
    checksum?: string,
  ): Promise<T> {
    try {
      const response = await fetchFeed(feed(path), {
        redirect: "error",
        signal,
      });
      if (
        !response.ok || !response.body ||
        Number(response.headers.get("content-length")) > maxBytes
      ) {
        await response.body?.cancel();
        return unavailable();
      }
      const reader = response.body.getReader();
      const chunks: Uint8Array[] = [];
      let size = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > maxBytes) {
          await reader.cancel();
          return unavailable();
        }
        chunks.push(value);
      }
      const data = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) {
        data.set(chunk, offset);
        offset += chunk.byteLength;
      }
      if (checksum && await hash(data) !== checksum) return unavailable();
      return JSON.parse(
        new TextDecoder("utf-8", { fatal: true }).decode(data),
      ) as T;
    } catch {
      return unavailable();
    }
  }

  async function catalog(signal: AbortSignal) {
    const data = await read<Catalog>("search/catalog.json", 256 * 1024, signal);
    if (
      data?.schema_version !== 1 ||
      !Number.isFinite(Date.parse(data.checked_at)) ||
      !Array.isArray(data.topics) || !Array.isArray(data.months)
    ) return unavailable();
    return data;
  }

  function monthItems(entry: Month, signal: AbortSignal) {
    if (
      !MONTH_PATTERN.test(entry.month) ||
      !/^[a-f0-9]{64}$/.test(entry.sha256) ||
      !Number.isSafeInteger(entry.size_bytes) || entry.size_bytes < 1 ||
      entry.size_bytes > MAX_MONTH_BYTES
    ) {
      return unavailable();
    }
    return read<Item[]>(
      `search/${entry.month}.json?v=${entry.sha256}`,
      entry.size_bytes,
      signal,
      entry.sha256,
    );
  }

  function withArchiveUrl(item: Item) {
    return { ...item, archive_url: feed(`archive/${item.archive_month}.json`) };
  }

  return {
    async search_notices(args: Record<string, unknown>) {
      const limit = pageSize(args);
      const query = normalize(optionalText(args, "query", 160) ?? "");
      const terms = query ? query.split(/\s+/u) : [];
      if (terms.length > 12) invalid("Use up to 12 search words.");
      const topic = optionalText(args, "topic", 40);
      const cursorText = optionalText(args, "cursor", 80);
      const cursor = cursorText === undefined ? null : decodeCursor(cursorText);
      const requestedFrom = optionalText(args, "published_from", 10);
      const requestedTo = optionalText(args, "published_to", 10);
      const includeUndated = requestedFrom === undefined &&
        requestedTo === undefined;
      if (requestedFrom !== undefined) dateValue(requestedFrom);
      if (requestedTo !== undefined) dateValue(requestedTo);

      const signal = AbortSignal.timeout(12_000);
      const { checked_at, topics, months } = await catalog(signal);
      if (topic !== undefined && !topics.includes(topic)) {
        invalid("Unknown topic. See agent.json for available topics.");
      }
      const publishedTo = requestedTo ??
        SEOUL_DATE.format(new Date(checked_at));
      const to = dateValue(publishedTo);
      const publishedFrom = requestedFrom ??
        new Date(to - 89 * DAY_MS).toISOString().slice(0, 10);
      const from = dateValue(publishedFrom);
      if (to < from || (to - from) / DAY_MS >= 366) {
        invalid("Use an ordered publication date range of at most 366 days.");
      }

      const overlaps = (first: string | null, last: string | null) =>
        first !== null && last !== null && first <= publishedTo &&
        last >= publishedFrom;
      const selected = months.filter((entry) =>
        overlaps(entry.published_from, entry.published_to) ||
        (includeUndated && overlaps(entry.undated_from, entry.undated_to))
      );
      if (
        selected.length > 16 ||
        selected.reduce((sum, entry) => sum + entry.size_bytes, 0) >
          MAX_SEARCH_BYTES
      ) {
        throw new SearchError(
          422,
          "range_too_large",
          "Narrow the publication date range.",
        );
      }
      const signature = await hash(new TextEncoder().encode(JSON.stringify([
        query,
        topic,
        includeUndated,
        publishedFrom,
        publishedTo,
        selected.map((entry) => [entry.month, entry.sha256]),
      ])));
      if (cursor && cursor.signature !== signature) {
        throw new SearchError(
          409,
          "search_cursor_changed",
          "Search filters or feed data changed. Start the search again without the cursor.",
        );
      }

      const matches: Array<{ item: Item; date: string }> = [];
      for (let start = 0; start < selected.length; start += 4) {
        const shards = await Promise.all(
          selected.slice(start, start + 4).map((entry) =>
            monthItems(entry, signal)
          ),
        );
        for (const items of shards) {
          for (const item of items) {
            const date = noticeDate(item, includeUndated);
            if (
              !date || date < publishedFrom || date > publishedTo ||
              (topic !== undefined && !item.topics.includes(topic))
            ) continue;
            const text = normalize(
              [item.title, item.preview, item.source_name].join(" "),
            );
            if (terms.every((term) => text.includes(term))) {
              matches.push({ item, date });
            }
          }
        }
      }
      matches.sort((left, right) => {
        if (left.date !== right.date) {
          return left.date > right.date ? -1 : 1;
        }
        return left.item.id === right.item.id
          ? 0
          : left.item.id > right.item.id
          ? -1
          : 1;
      });

      const offset = cursor?.offset ?? 0;
      if (cursor && offset >= matches.length) {
        invalid("Invalid search cursor offset.");
      }
      const end = offset + limit;
      return {
        checked_at,
        published_from: publishedFrom,
        published_to: publishedTo,
        items: matches.slice(offset, end).map(({ item }) =>
          withArchiveUrl(item)
        ),
        matching_count: matches.length,
        has_more: end < matches.length,
        next_cursor: end < matches.length ? `${signature}.${end}` : null,
      };
    },

    async get_notice(args: Record<string, unknown>) {
      const month = optionalText(args, "archive_month", 7);
      const id = optionalText(args, "notice_id", 512);
      if (!month || !MONTH_PATTERN.test(month) || !id) {
        invalid("Supply notice_id and an archive_month in YYYY-MM format.");
      }
      const signal = AbortSignal.timeout(12_000);
      const { checked_at, months } = await catalog(signal);
      const entry = months.find((candidate) => candidate.month === month);
      const item = entry &&
        (await monthItems(entry, signal)).find((candidate) =>
          candidate.id === id
        );
      if (!item) {
        throw new SearchError(
          404,
          "notice_not_found",
          "No notice matches that ID and archive month.",
        );
      }
      return { item: withArchiveUrl(item), checked_at };
    },

    async list_changes(args: Record<string, unknown>) {
      const limit = pageSize(args);
      const after = optionalText(args, "after_event_id", 256);
      if (after === "") invalid("after_event_id must not be empty.");
      const data = await read<Events>(
        "events.json",
        MAX_MONTH_BYTES,
        AbortSignal.timeout(12_000),
      );
      if (!Array.isArray(data?.events) || !data.checked_at) {
        return unavailable();
      }
      const offset = after === undefined
        ? Math.max(0, data.events.length - limit)
        : data.events.findIndex((event) => event.event_id === after) + 1;
      if (after !== undefined && offset === 0) {
        throw new SearchError(
          409,
          "archive_required",
          `The event cursor is outside the recent window. Resume from ${
            feed("index.json")
          } and its monthly archives.`,
        );
      }
      const events = data.events.slice(offset, offset + limit);
      return {
        events: events.map((event) => ({
          ...event,
          archive_url: feed(event.archive_file),
        })),
        next_after_event_id: events.at(-1)?.event_id ?? after ?? null,
        has_more: offset + limit < data.events.length,
        checked_at: data.checked_at,
        archive_index_url: feed("index.json"),
      };
    },
  };
}
