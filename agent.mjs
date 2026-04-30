import { query } from "@anthropic-ai/claude-agent-sdk";
import { randomUUID } from "crypto";

const sessions = new Map();

export function getSessions() {
  return Array.from(sessions.values()).map(({ id, prompt, status, createdAt, messages }) => ({
    id, prompt, status, createdAt, messageCount: messages.length,
  }));
}

export function getSession(id) {
  return sessions.get(id);
}

export async function createSession({ prompt, tools, disallowedTools, settingSources }) {
  const id = randomUUID();
  const session = {
    id,
    prompt,
    status: "running",
    createdAt: new Date().toISOString(),
    messages: [],
    subscribers: new Set(),
  };
  sessions.set(id, session);

  runAgent(session, { prompt, tools, disallowedTools, settingSources });

  return id;
}

export function subscribe(id, callback) {
  const session = sessions.get(id);
  if (!session) return null;
  session.subscribers.add(callback);
  return () => session.subscribers.delete(callback);
}

async function runAgent(session, { prompt, tools, disallowedTools, settingSources }) {
  const q = query({
    prompt,
    options: {
      cwd: "/Users/noah/Desktop/Workspace/viv-monorepo/agent-workspace",
      permissionMode: "bypassPermissions",
      allowDangerouslySkipPermissions: true,
      ...(tools && { tools }),
      ...(disallowedTools && { disallowedTools }),
      ...(settingSources !== undefined && { settingSources }),
    },
  });

  try {
    for await (const msg of q) {
      session.messages.push(msg);
      for (const cb of session.subscribers) cb(msg);
    }
    session.status = "done";
  } catch (err) {
    session.status = "error";
    const errMsg = { type: "error", message: err.message };
    session.messages.push(errMsg);
    for (const cb of session.subscribers) cb(errMsg);
  }

  for (const cb of session.subscribers) cb(null);
}
