import { readFileSync } from "fs";
import { start as startSlack } from "./adapters/slack.mjs";

// load .env
try {
  readFileSync("./.env", "utf8").split("\n").forEach((line) => {
    const [k, ...rest] = line.split("=");
    if (k && rest.length) process.env[k.trim()] = rest.join("=").trim();
  });
} catch {}

const GATEWAY_URL = process.env.GATEWAY_URL ?? "http://localhost:3456";

function log(tag, ...args) {
  const ts = new Date().toISOString();
  console.log(`[${ts}] [ingress] [${tag}]`, ...args);
}

log("boot", `GATEWAY_URL=${GATEWAY_URL}`);

// Slack 어댑터
if (process.env.SLACK_APP_TOKEN && process.env.SLACK_BOT_TOKEN) {
  log("boot", "starting Slack adapter");
  startSlack({
    appToken: process.env.SLACK_APP_TOKEN,
    botToken: process.env.SLACK_BOT_TOKEN,
    gatewayUrl: GATEWAY_URL,
  });
} else {
  log("boot", "SLACK_APP_TOKEN or SLACK_BOT_TOKEN missing, skipping Slack adapter");
}
