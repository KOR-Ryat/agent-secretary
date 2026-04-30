const OUTPUT_INSTRUCTION = `
작업을 완료한 뒤, 반드시 아래 JSON 형식으로만 최종 응답하라. 다른 텍스트는 절대 포함하지 말 것.
{"메시지":"<사용자에게 보여줄 간결한 결과 요약>","파일":"<전체 상세 내역 마크다운>"}
`.trim();

export const SYSTEM_PROMPTS = {
  debug: `당신은 시니어 백엔드 엔지니어입니다. 버그 분석 요청이 들어왔습니다.

레포-브랜치 전략 참조: REPOS.md
JSON "파일" 필드(result.md) 작성 예시 참조: EXAMPLE_DEBUG.md

컨텍스트는 에러 로그/스택 트레이스일 수도 있고, 유저의 버그 제보(자연어)일 수도 있습니다. 형식에 관계없이 문제를 파악하세요.

다음 순서로 작업하세요:
1. 컨텍스트에서 문제의 증상을 파악합니다. 에러 메시지, 스택 트레이스, 재현 조건 등을 추출하세요.
2. 주어진 레포지토리에서 해당 환경의 브랜치를 git worktree로 마운트하고 최신 코드를 fetch합니다. (브랜치 정보 및 worktree 사용법은 REPOS.md 참조)
3. 코드를 직접 읽어 문제가 발생하는 정확한 파일과 라인을 찾습니다.
4. 근본 원인(root cause)을 설명합니다. 표면적 증상이 아닌 실제 원인을 찾으세요.
5. 해결 방향을 구체적으로 제시합니다. 코드 수준의 힌트를 포함하세요.
6. 원인 분석과 해결책 각각에 대해 컨피던스를 백분율로 표기하고, 낮은 경우 이유를 명시하세요.

결과에 반드시 포함할 것:
- 분석 기준 레포와 브랜치 (예: mesher-labs/project-201-server @ main)
- 문제가 발견된 파일 경로와 라인 번호

레포지토리 코드를 실제로 읽지 않고 추측만으로 답하지 마세요.`,
  fix: "플레이스홀더: 버그 수정 시스템 프롬프트",
  issue: "플레이스홀더: 리니어 이슈 등록 시스템 프롬프트",
};

export function buildPrompt(cmd, { threadMessages = [], channel, service, env, repos = [], sessionId } = {}) {
  const systemPrompt = SYSTEM_PROMPTS[cmd] ?? null;

  const repoContext = repos.length
    ? repos.map((r) => {
        const branch = env === "production" ? r.production : env === "staging" || env === "stage" ? r.staging : r.dev;
        return `- ${r.name} (브랜치: ${branch ?? "unknown"})`;
      }).join("\n")
    : null;

  const threadContext = threadMessages
    .map((m) => `[${m.user ?? m.bot_id ?? "?"}] ${(m.text ?? "").slice(0, 300)}`)
    .join("\n");

  return [
    OUTPUT_INSTRUCTION,
    systemPrompt ? `\n---\n${systemPrompt}` : "",
    `\n---\n채널: ${channel ?? "unknown"}\n서비스: ${service ?? "unknown"}\n환경: ${env ?? "unknown"}`,
    sessionId ? `세션ID: ${sessionId}` : "",
    repoContext ? `\n레포:\n${repoContext}` : "",
    threadContext ? `\n---\n스레드 컨텍스트:\n${threadContext}` : "",
  ].join("\n").trim();
}

export async function executeCommand(cmd, context, gatewayUrl) {
  const sessionId = crypto.randomUUID().slice(0, 8);
  const prompt = buildPrompt(cmd, { ...context, sessionId });

  const sessionRes = await fetch(`${gatewayUrl}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });

  if (!sessionRes.ok) {
    const text = await sessionRes.text();
    throw new Error(`세션 생성 실패 (${sessionRes.status}): ${text}`);
  }

  const { id } = await sessionRes.json();

  const stream = await fetch(`${gatewayUrl}/sessions/${id}/stream`);
  if (!stream.ok) throw new Error(`스트림 연결 실패 (${stream.status})`);

  const reader = stream.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let raw = null;
  let streamDone = false;

  while (!streamDone) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop();
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const data = line.slice(6).trim();
      if (data === "null") { streamDone = true; break; }
      try {
        const msg = JSON.parse(data);
        if (msg.type === "result") {
          raw = (msg.result ?? "")
            .replace(/<thinking>[\s\S]*?<\/thinking>/g, "")
            .replace(/<think>[\s\S]*?<\/think>/g, "")
            .trim();
        }
      } catch {}
    }
  }

  const text = raw ?? "완료 (결과 없음)";
  const jsonMatch = text.match(/\{[\s\S]*"메시지"[\s\S]*"파일"[\s\S]*\}/);
  if (jsonMatch) {
    try {
      const parsed = JSON.parse(jsonMatch[0]);
      return {
        message: parsed["메시지"] ?? text,
        fileContent: parsed["파일"] ?? null,
      };
    } catch {}
  }
  return { message: text, fileContent: null };
}
