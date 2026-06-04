#!/usr/bin/env node
import {
  constants as cryptoConstants,
  createHash,
  createPublicKey,
  publicEncrypt,
} from "node:crypto";

const BASE_URL = "https://onestop.pusan.ac.kr";
const USER_AGENT = "PNUPublicNoticeFeed/0.1";

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const menuCd = args["menu-cd"];
  const limit = Number.parseInt(args.limit ?? "20", 10);
  if (!menuCd) throw new Error("--menu-cd is required");
  if (!Number.isFinite(limit) || limit <= 0) throw new Error("--limit must be positive");

  const client = await OnestopClient.create(menuCd);
  const globalInfo = await client.postJson("/global/info", { menuCD: menuCd });
  const menuInfo = findMenuInfo(globalInfo, menuCd);
  if (!menuInfo?.AUTH_STR) throw new Error(`AUTH_STR not found for menuCD=${menuCd}`);

  const list = await client.postJson(
    "/bbs/selectList",
    {
      SCH_GUBUN: "",
      SCH_CONTENT: "",
      CATE_TYPE_SEQ_NO: "",
      totPage: 1,
      totCnt: 0,
      pageSize: limit,
      pageIndex: 0,
      pageGrp: 1,
    },
    menuInfo.AUTH_STR,
  );

  const notices = uniqueByNoticeId(
    (Array.isArray(list.data) ? list.data : []).map((row) => normalizeNotice(row, menuCd)),
  ).slice(0, limit);

  process.stdout.write(
    JSON.stringify({
      menu_cd: menuCd,
      source_name: menuInfo.MENU_KOR_NM ?? null,
      total_count: list.totalCnt ?? notices.length,
      notices,
    }),
  );
}

class OnestopClient {
  constructor({ menuCd, cookie, csrfToken, rsaKey }) {
    this.menuCd = menuCd;
    this.cookie = cookie;
    this.csrfToken = csrfToken;
    this.rsaKey = rsaKey;
  }

  static async create(menuCd) {
    const entryUrl = `${BASE_URL}/page?menuCD=${encodeURIComponent(menuCd)}`;
    const response = await fetch(entryUrl, {
      headers: { "User-Agent": USER_AGENT },
    });
    if (!response.ok) throw new Error(`failed to fetch onestop entry: ${response.status}`);

    const cookie = collectCookies("", getSetCookies(response.headers));
    const html = await response.text();
    const csrfToken = matchRequired(
      html,
      /scwin\.token\s*=\s*["']([0-9a-f-]{30,50})["']/i,
      "csrf token",
    );
    const modulus = matchRequired(
      html,
      /var\s+RSAModulus\s*=\s*'([0-9a-f]+)'/i,
      "RSA modulus",
    );
    const exponent = matchRequired(
      html,
      /var\s+RSAExponent\s*=\s*'([0-9a-f]+)'/i,
      "RSA exponent",
    );

    return new OnestopClient({
      menuCd,
      cookie,
      csrfToken,
      rsaKey: createRsaKey(modulus, exponent),
    });
  }

  async postJson(path, payload, authStr = {}) {
    const requestData = { ...payload, locale: "0001" };
    const wrapped = {
      _data: JSON.stringify(requestData),
      AUTH_STR: authStr,
    };
    const body = JSON.stringify({
      _data: encryptChunked(JSON.stringify(wrapped), this.rsaKey),
    });
    const response = await fetch(`${BASE_URL}${path}`, {
      method: "POST",
      headers: {
        Accept: "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        AJAX: "true",
        "User-Agent": USER_AGENT,
        Cookie: this.cookie,
        Referer: `${BASE_URL}/page?menuCD=${this.menuCd}`,
        "X-CSRF-TOKEN": this.csrfToken,
      },
      body,
    });
    const text = await response.text();
    if (!response.ok) {
      throw new Error(`onestop ${path} failed: ${response.status} ${text.slice(0, 300)}`);
    }
    try {
      return JSON.parse(text);
    } catch {
      throw new Error(`onestop ${path} returned non-json: ${text.slice(0, 300)}`);
    }
  }
}

function parseArgs(argv) {
  const result = {};
  for (let i = 0; i < argv.length; i += 1) {
    const part = argv[i];
    if (!part.startsWith("--")) continue;
    const key = part.slice(2);
    const value = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : "true";
    result[key] = value;
  }
  return result;
}

function getSetCookies(headers) {
  if (typeof headers.getSetCookie === "function") return headers.getSetCookie();
  const cookie = headers.get("set-cookie");
  return cookie ? [cookie] : [];
}

function collectCookies(previous, setCookies) {
  const jar = new Map();
  for (const part of previous.split(";").map((value) => value.trim()).filter(Boolean)) {
    const index = part.indexOf("=");
    if (index > 0) jar.set(part.slice(0, index), part.slice(index + 1));
  }
  for (const raw of setCookies) {
    const first = raw.split(";")[0];
    const index = first.indexOf("=");
    if (index > 0) jar.set(first.slice(0, index), first.slice(index + 1));
  }
  return [...jar].map(([key, value]) => `${key}=${value}`).join("; ");
}

function matchRequired(text, pattern, label) {
  const match = text.match(pattern);
  if (!match) throw new Error(`${label} not found`);
  return match[1];
}

function createRsaKey(modulusHex, exponentHex) {
  const normalizedModulus = modulusHex.length % 2 === 0 ? modulusHex : `0${modulusHex}`;
  const normalizedExponent = exponentHex.length % 2 === 0 ? exponentHex : `0${exponentHex}`;
  return createPublicKey({
    key: {
      kty: "RSA",
      n: toBase64Url(Buffer.from(normalizedModulus, "hex")),
      e: toBase64Url(Buffer.from(normalizedExponent, "hex")),
    },
    format: "jwk",
  });
}

function toBase64Url(buffer) {
  return buffer
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

function encryptChunked(text, rsaKey) {
  return splitByUtf8Bytes(text, 200)
    .map((chunk) => {
      let hex = publicEncrypt(
        {
          key: rsaKey,
          padding: cryptoConstants.RSA_PKCS1_PADDING,
        },
        Buffer.from(chunk, "utf8"),
      )
        .toString("hex")
        .replace(/^0+/, "");
      if (!hex) hex = "00";
      if (hex.length % 2 === 1) hex = `0${hex}`;
      return hex;
    })
    .join(",");
}

function splitByUtf8Bytes(text, maxBytes) {
  const chunks = [];
  let current = "";
  let bytes = 0;
  for (const char of text) {
    const charBytes = Buffer.byteLength(char, "utf8");
    if (current && bytes + charBytes > maxBytes) {
      chunks.push(current);
      current = "";
      bytes = 0;
    }
    current += char;
    bytes += charBytes;
  }
  if (current) chunks.push(current);
  return chunks;
}

function findMenuInfo(globalInfo, menuCd) {
  const menu = Array.isArray(globalInfo?._Menu) ? globalInfo._Menu : [];
  return menu.find((item) => item?.MENU_CD === menuCd);
}

function normalizeNotice(row, menuCd) {
  const seq = String(row.POSTING_SEQ_NO ?? row.POSTING_GRP_NO ?? row.RN ?? "");
  const title = cleanText(row.TITLE_CONTENT ?? row.TITLE ?? "");
  const contentText = cleanText(stripHtml(row.CONTENT ?? ""));
  const attachments = normalizeAttachments(row.bbsFileList ?? [], row);
  return {
    notice_id: seq,
    title,
    url: `${BASE_URL}/page?menuCD=${encodeURIComponent(menuCd)}&mode=DETAIL&seq=${encodeURIComponent(seq)}`,
    published_at: normalizeDate(row.INS_DT),
    snippet: contentText ? contentText.slice(0, 500) : null,
    attachments,
    content_hash: createHash("sha256")
      .update(
        JSON.stringify({
          title,
          published_at: normalizeDate(row.INS_DT),
          content: contentText,
          attachments,
        }),
      )
      .digest("hex"),
  };
}

function uniqueByNoticeId(notices) {
  const seen = new Set();
  const result = [];
  for (const notice of notices) {
    if (!notice.notice_id || seen.has(notice.notice_id)) continue;
    seen.add(notice.notice_id);
    result.push(notice);
  }
  return result;
}

function normalizeAttachments(fileList, row) {
  if (Array.isArray(fileList) && fileList.length > 0) {
    return fileList
      .filter((file) => file?.PARAM_CODE && file?.ORIGIN_FILE_NM)
      .map((file) => ({
        name: String(file.ORIGIN_FILE_NM),
        url: `${BASE_URL}/file/download.do?${file.PARAM_CODE}`,
        type: file.FILE_EXTENSION_CONTENT
          ? String(file.FILE_EXTENSION_CONTENT).toLowerCase()
          : extensionOf(file.ORIGIN_FILE_NM),
      }));
  }
  if (row.PARAM_CODE && row.ATTACH_FILE_TXT) {
    return [
      {
        name: String(row.ATTACH_FILE_TXT),
        url: `${BASE_URL}/file/download.do?${row.PARAM_CODE}`,
        type: extensionOf(row.ATTACH_FILE_TXT),
      },
    ];
  }
  return [];
}

function normalizeDate(value) {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") {
    return new Date(value).toISOString().slice(0, 10);
  }
  const text = String(value);
  const match = text.match(/\d{4}-\d{2}-\d{2}/);
  return match ? match[0] : null;
}

function stripHtml(value) {
  return String(value)
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>/gi, "\n")
    .replace(/<[^>]*>/g, " ");
}

function cleanText(value) {
  return decodeHtml(String(value)).replace(/\s+/g, " ").trim();
}

function decodeHtml(value) {
  return value
    .replace(/&nbsp;/g, " ")
    .replace(/&middot;/g, "·")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'");
}

function extensionOf(name) {
  const match = String(name).match(/\.([A-Za-z0-9]+)(?:\s|\(|$)/);
  return match ? match[1].toLowerCase() : null;
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});

