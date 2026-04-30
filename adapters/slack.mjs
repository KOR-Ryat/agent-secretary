import { SocketModeClient } from "@slack/socket-mode";
import { WebClient } from "@slack/web-api";
import { executeCommand } from "../commands.mjs";
import { resolveChannel } from "../service-map.mjs";

function log(tag, ...args) {
  const ts = new Date().toISOString();
  console.log(`[${ts}] [slack] [${tag}]`, ...args);
}

function classifyPrompt(text) {
  if (!text) return null;
  if (text.includes("디버깅") || text.includes("분석")) return "debug";
  if (text.includes("수정") || text.includes("픽스")) return "fix";
  if (text.includes("이슈") && text.includes("등록")) return "issue";
  return null;
}

function buildCommandBlock(ctx) {
  return {
    blocks: [
      {
        type: "actions",
        block_id: JSON.stringify(ctx),
        elements: [
          { type: "button", text: { type: "plain_text", text: "🔍 버그 분석" }, action_id: "cmd_debug" },
          { type: "button", text: { type: "plain_text", text: "🔧 버그 수정" }, style: "primary", action_id: "cmd_fix" },
          { type: "button", text: { type: "plain_text", text: "📋 이슈 등록" }, action_id: "cmd_issue" },
        ],
      },
    ],
    text: "커맨드를 선택하세요.",
  };
}

async function fetchThread(web, channel, thread_ts) {
  try {
    const { messages } = await web.conversations.replies({ channel, ts: thread_ts });
    log("thread", `fetched ${messages.length} messages`);
    return messages;
  } catch (err) {
    log("thread", `fetch error: ${err.message}`);
    return [];
  }
}

async function handleCommand(web, channel, thread_ts, mention_ts, cmd, gatewayUrl) {
  await web.reactions.add({ channel, timestamp: mention_ts, name: "hourglass_flowing_sand" }).catch(() => {});

  try {
    const threadMessages = await fetchThread(web, channel, thread_ts);
    const resolved = resolveChannel(channel);
    log("command", `cmd=${cmd} service=${resolved?.service ?? "unknown"} env=${resolved?.env ?? "unknown"}`);

    const { message, fileContent } = await executeCommand(cmd, {
      threadMessages,
      channel: resolved?.channelName ?? channel,
      service: resolved?.service,
      env: resolved?.env,
      repos: resolved?.repos ?? [],
    }, gatewayUrl);

    await web.reactions.remove({ channel, timestamp: mention_ts, name: "hourglass_flowing_sand" }).catch(() => {});
    await web.reactions.add({ channel, timestamp: mention_ts, name: "white_check_mark" }).catch(() => {});

    if (fileContent) {
      await web.files.uploadV2({
        channel_id: channel,
        thread_ts,
        content: fileContent,
        filename: "result.md",
        filetype: "markdown",
        initial_comment: message,
      }).catch((err) => log("slack", `file upload error: ${err.message}`));
      log("slack", "file uploaded with message");
    } else {
      await web.chat.postMessage({ channel, thread_ts, text: message });
      log("slack", "message posted");
    }
  } catch (err) {
    log("error", err.message);
    await web.reactions.remove({ channel, timestamp: mention_ts, name: "hourglass_flowing_sand" }).catch(() => {});
    await web.reactions.add({ channel, timestamp: mention_ts, name: "x" }).catch(() => {});
    await web.chat.postMessage({ channel, thread_ts, text: `❌ ${err.message}` });
  }
}

export function start({ appToken, botToken, gatewayUrl }) {
  const socket = new SocketModeClient({ appToken });
  const web = new WebClient(botToken);

  socket.on("app_mention", async ({ event, ack }) => {
    log("mention", `channel=${event.channel} ts=${event.ts} user=${event.user}`);
    log("mention", `raw_text="${event.text}"`);
    await ack();

    const text = event.text.replace(/<@[A-Z0-9]+>/g, "").trim();
    const { channel } = event;
    const thread_ts = event.thread_ts ?? event.ts;
    const ctx = { channel, thread_ts, mention_ts: event.ts };
    const cmd = classifyPrompt(text);

    if (!text || !cmd) {
      log("mention", "posting command block");
      await web.chat.postMessage({ channel, thread_ts, ...buildCommandBlock(ctx) });
      return;
    }

    log("mention", `cmd=${cmd}`);
    await handleCommand(web, channel, thread_ts, event.ts, cmd, gatewayUrl);
  });

  socket.on("interactive", async (args) => {
    const { ack } = args;
    await ack();
    const payload = args.body ?? args.payload;
    const action = payload?.actions?.[0];
    log("interactive", `action_id=${action?.action_id}`);

    let ctx;
    try { ctx = JSON.parse(action?.block_id ?? "{}"); } catch { ctx = {}; }
    const { channel, thread_ts, mention_ts } = ctx;
    const block_msg_ts = payload?.container?.message_ts;

    if (block_msg_ts) {
      await web.chat.delete({ channel, ts: block_msg_ts }).catch((err) => log("interactive", `delete error: ${err.message}`));
    }

    const cmdMap = { cmd_debug: "debug", cmd_fix: "fix", cmd_issue: "issue" };
    const cmd = cmdMap[action?.action_id];

    if (!cmd) {
      log("interactive", `unknown action_id=${action?.action_id}`);
      return;
    }

    await handleCommand(web, channel, thread_ts, mention_ts, cmd, gatewayUrl);
  });

  socket.on("slash_commands", ({ ack }) => ack());
  socket.on("error", (err) => log("error", err.message));
  socket.on("disconnect", (msg) => log("disconnect", JSON.stringify(msg)));
  socket.on("reconnecting", () => log("reconnecting", "attempting reconnect…"));
  socket.on("connected", () => log("connected", "socket connected"));

  socket.start();
  log("boot", "started");
}
