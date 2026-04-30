import { query } from "@anthropic-ai/claude-agent-sdk";
import { createWriteStream } from "fs";

const q = query({
  prompt: "hello.txt 파일을 만들고 'hello world' 라고 써줘",
  options: {
    settingSources: [],
    tools: ["Bash"],
  },
});

const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
const filename = `./query-log-${timestamp}.json`;
const log = createWriteStream(filename, { flags: "w" });
log.write("[\n");
let first = true;

for await (const msg of q) {
  if (!first) log.write(",\n");
  log.write(JSON.stringify(msg, null, 2));
  first = false;
}

log.write("\n]\n");
log.end();
console.log(`saved to ${filename}`);
