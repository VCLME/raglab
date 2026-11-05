/**
 * Serves the built frontend (frontend/dist) and its /api, either recorded
 * from a live raglab API or replayed from a fixture.
 *
 * - record: every /api call is forwarded to the live API and kept (JSON
 *   bodies, Server-Sent Events with their arrival time). Only local file
 *   paths are shortened (`scrub`): they would show the machine's user name.
 * - replay: /api calls are answered from the fixture. With `step`, a stream
 *   sends its events only when the driver releases them (`release(n)`), so
 *   each screenshot shows a known state.
 */
import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".css": "text/css",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".json": "application/json",
  ".woff2": "font/woff2",
  ".map": "application/json",
};

/** One SSE block ("event: x\ndata: {...}") as [event, data]. */
function parseBlock(block) {
  let event = "message";
  const data = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  return data.length ? [event, JSON.parse(data.join("\n"))] : null;
}

const sseBlock = (event, data) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

/**
 * Local paths in API payloads (C:\Users\me\...\data\lexml\x.txt) as
 * repository paths (data\lexml\x.txt); any other home directory as "~".
 */
export function scrub(value) {
  if (typeof value === "string") {
    return value
      .replace(/[A-Za-z]:[\\/](?:[^"\\/]+[\\/])*?(?=(?:data|benchmarks)[\\/])/g, "")
      .replace(/[A-Za-z]:[\\/]Users[\\/][^"\\/]+/g, "~");
  }
  if (Array.isArray(value)) return value.map(scrub);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, scrub(v)]));
  }
  return value;
}

async function readBody(req) {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const text = Buffer.concat(chunks).toString("utf8");
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/** The key a request is matched on: method, path, and the question it asks. */
function requestKey(method, url, body) {
  const path = url.split("?")[0];
  const question = body && typeof body === "object" ? body.question : undefined;
  return question ? `${method} ${path} ${question}` : `${method} ${url}`;
}

export async function startServer({ mode, dist, fixture, apiUrl, apiKey, port = 5199, step = false, log = () => {} }) {
  const recorded = [];
  const unmatched = [];
  // Replay with steps: the stream currently held open and what it still has to send.
  let held = null;

  async function serveStatic(req, res) {
    const path = normalize(decodeURIComponent(req.url.split("?")[0])).replace(/^([/\\])+/, "");
    for (const candidate of [join(dist, path), join(dist, "index.html")]) {
      try {
        const body = await readFile(candidate);
        res.writeHead(200, { "Content-Type": TYPES[extname(candidate)] ?? "application/octet-stream" });
        return res.end(body);
      } catch {
        // try the SPA fallback
      }
    }
    res.writeHead(404).end();
  }

  async function record(req, res) {
    const body = req.method === "GET" ? null : await readBody(req);
    const started = performance.now();
    const upstream = await fetch(apiUrl + req.url, {
      method: req.method,
      headers: {
        "Content-Type": "application/json",
        Accept: req.headers.accept ?? "*/*",
        ...(apiKey ? { "X-API-Key": apiKey } : {}),
      },
      body: body === null ? undefined : JSON.stringify(body),
    });
    const type = upstream.headers.get("content-type") ?? "";
    const entry = { method: req.method, url: req.url, body, status: upstream.status, type };
    recorded.push(entry);
    if (type.includes("text/event-stream")) {
      entry.events = [];
      res.writeHead(upstream.status, { "Content-Type": type, "Cache-Control": "no-cache" });
      const decoder = new TextDecoder();
      let buffer = "";
      res.on("close", () => (entry.ended = true));
      for await (const chunk of upstream.body) {
        buffer += decoder.decode(chunk, { stream: true }).replace(/\r\n/g, "\n");
        let sep;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          const parsed = parseBlock(buffer.slice(0, sep));
          buffer = buffer.slice(sep + 2);
          if (!parsed) continue;
          const [event, data] = [parsed[0], scrub(parsed[1])];
          entry.events.push({ event, data, t: Math.round(performance.now() - started) });
          res.write(sseBlock(event, data));
        }
      }
      entry.ended = true;
      return res.end();
    }
    const text = await upstream.text();
    let json = null;
    try {
      json = scrub(JSON.parse(text));
    } catch {
      entry.text = text;
    }
    // The demo runs in a fresh browser: keep its conversations in the browser
    // instead of adding them to the server's history.
    if (req.method === "GET" && req.url.split("?")[0] === "/api/config" && json) {
      json = { ...json, conversation_history: false };
    }
    if (json !== null) entry.json = json;
    res.writeHead(upstream.status, { "Content-Type": type || "application/json" });
    res.end(json !== null ? JSON.stringify(json) : text);
    log(`${req.method} ${req.url} -> ${upstream.status} (${Math.round(performance.now() - started)} ms)`);
  }

  function findEntry(method, url, body) {
    const key = requestKey(method, url, body);
    const path = url.split("?")[0];
    const sameKey = fixture.requests.filter((e) => requestKey(e.method, e.url, e.body) === key);
    if (sameKey.length) return sameKey[sameKey.length - 1];
    // Placeholder fixtures answer every question with the same payload.
    const any = fixture.requests.find((e) => e.anyQuestion && e.method === method && e.url.split("?")[0] === path);
    if (any) return any;
    // Same endpoint, other query string (a GET polled with another parameter).
    if (method === "GET") {
      const samePath = fixture.requests.filter((e) => e.method === "GET" && e.url.split("?")[0] === path);
      if (samePath.length) return samePath[samePath.length - 1];
    }
    return null;
  }

  async function replay(req, res) {
    const body = req.method === "GET" ? null : await readBody(req);
    const entry = findEntry(req.method, req.url, body);
    if (!entry) {
      unmatched.push(requestKey(req.method, req.url, body));
      res.writeHead(404, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ detail: "Not in the demo fixture" }));
    }
    if (entry.events) {
      res.writeHead(entry.status, { "Content-Type": entry.type, "Cache-Control": "no-cache" });
      if (!step) {
        for (const e of entry.events) res.write(sseBlock(e.event, e.data));
        return res.end();
      }
      held = { res, events: entry.events, sent: 0 };
      return;
    }
    res.writeHead(entry.status, { "Content-Type": entry.type || "application/json" });
    res.end(entry.json !== undefined ? JSON.stringify(entry.json) : entry.text ?? "");
  }

  /** Replay with steps: send the next `n` events of the held stream. */
  function release(n = 1) {
    if (!held) return;
    const until = Math.min(held.events.length, held.sent + n);
    for (; held.sent < until; held.sent++) {
      const e = held.events[held.sent];
      held.res.write(sseBlock(e.event, e.data));
    }
    if (held.sent >= held.events.length) {
      held.res.end();
      held = null;
    }
  }

  const server = http.createServer((req, res) => {
    const handle = req.url.startsWith("/api/")
        ? () => (mode === "record" ? record(req, res) : replay(req, res))
        : () => serveStatic(req, res);
    handle().catch((e) => {
      log(`error on ${req.method} ${req.url}: ${e.message}`);
      if (!res.headersSent) res.writeHead(502, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ detail: String(e.message) }));
    });
  });
  await new Promise((resolve) => server.listen(port, "127.0.0.1", resolve));
  return {
    url: `http://127.0.0.1:${port}`,
    recorded,
    unmatched,
    /** The stream held open by a replay with steps: its events and how many were sent. */
    held: () => (held ? { events: held.events, sent: held.sent } : null),
    release,
    close: () =>
      new Promise((resolve) => {
        server.closeAllConnections();
        server.close(resolve);
      }),
  };
}
