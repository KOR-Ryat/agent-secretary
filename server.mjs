import { createServer } from "http";
import { readFileSync } from "fs";
import { createSession, getSessions, getSession, subscribe } from "./agent.mjs";

const PORT = 3456;

process.on("uncaughtException", (err) => {
  console.error(`[${new Date().toISOString()}] [server] [FATAL] uncaughtException: ${err.message}\n${err.stack}`);
});
process.on("unhandledRejection", (reason) => {
  console.error(`[${new Date().toISOString()}] [server] [FATAL] unhandledRejection:`, reason);
});

function log(tag, ...args) {
  const ts = new Date().toISOString();
  console.log(`[${ts}] [server] [${tag}]`, ...args);
}

function json(res, status, data) {
  res.writeHead(status, { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*" });
  res.end(JSON.stringify(data));
}

function sse(res) {
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Access-Control-Allow-Origin": "*",
  });
  return (data) => res.write(`data: ${JSON.stringify(data)}\n\n`);
}

createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  log("req", `${req.method} ${url.pathname}`);

  if (req.method === "OPTIONS") {
    res.writeHead(204, { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST", "Access-Control-Allow-Headers": "Content-Type" });
    res.end();
    return;
  }

  // Dashboard
  if (req.method === "GET" && url.pathname === "/") {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(readFileSync("./index.html"));
    return;
  }

  // 세션 목록
  if (req.method === "GET" && url.pathname === "/sessions") {
    const sessions = getSessions();
    log("sessions", `list count=${sessions.length}`);
    json(res, 200, sessions);
    return;
  }

  // 세션 생성
  if (req.method === "POST" && url.pathname === "/sessions") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", async () => {
      let parsed;
      try {
        parsed = JSON.parse(body);
      } catch (err) {
        log("session:create", `JSON parse error: ${err.message} body="${body.slice(0, 80)}"`);
        json(res, 400, { error: "invalid JSON" });
        return;
      }
      const { prompt, tools, disallowedTools, settingSources } = parsed;
      log("session:create", `prompt="${(prompt ?? "").slice(0, 100)}" tools=${JSON.stringify(tools ?? null)} disallowedTools=${JSON.stringify(disallowedTools ?? null)}`);
      try {
        const id = await createSession({ prompt, tools, disallowedTools, settingSources });
        log("session:create", `created id=${id}`);
        json(res, 201, { id });
      } catch (err) {
        log("session:create", `error: ${err.message}`);
        json(res, 500, { error: err.message });
      }
    });
    return;
  }

  // 세션 상세
  const sessionMatch = url.pathname.match(/^\/sessions\/([^/]+)$/);
  if (req.method === "GET" && sessionMatch) {
    const id = sessionMatch[1];
    const session = getSession(id);
    if (!session) {
      log("session:get", `not found id=${id}`);
      json(res, 404, { error: "not found" });
      return;
    }
    log("session:get", `id=${id} status=${session.status} messages=${session.messages.length}`);
    json(res, 200, { ...session, subscribers: undefined });
    return;
  }

  // 세션 스트림 (SSE)
  const streamMatch = url.pathname.match(/^\/sessions\/([^/]+)\/stream$/);
  if (req.method === "GET" && streamMatch) {
    const id = streamMatch[1];
    const session = getSession(id);
    if (!session) {
      log("stream", `not found id=${id}`);
      json(res, 404, { error: "not found" });
      return;
    }

    log("stream", `start id=${id} status=${session.status} replay=${session.messages.length} messages`);
    const send = sse(res);

    for (const msg of session.messages) {
      log("stream", `replay type=${msg.type}${msg.subtype ? "/" + msg.subtype : ""}`);
      send(msg);
    }

    if (session.status !== "running") {
      log("stream", `session already done (status=${session.status}), closing`);
      res.write("data: null\n\n");
      res.end();
      return;
    }

    let sentCount = 0;
    const unsubscribe = subscribe(id, (msg) => {
      if (msg === null) {
        log("stream", `null received, closing (sent ${sentCount} live messages)`);
        res.write("data: null\n\n");
        res.end();
        return;
      }
      sentCount++;
      log("stream", `live #${sentCount} type=${msg.type}${msg.subtype ? "/" + msg.subtype : ""} ${JSON.stringify(msg).slice(0, 80)}`);
      send(msg);
    });

    req.on("close", () => {
      log("stream", `client disconnected id=${id}`);
      unsubscribe();
    });
    return;
  }

  log("req", `404 ${req.method} ${url.pathname}`);
  json(res, 404, { error: "not found" });
}).listen(PORT, () => log("boot", `gateway running at http://localhost:${PORT}`));
