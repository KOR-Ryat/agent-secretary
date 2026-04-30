# Agent Workspace 세팅

## 1. 디렉토리 구조

```
viv-monorepo/
├── claude-agent-sdk-test/    ← 인그레스 서버
│   ├── DESIGN.md
│   ├── WORKSPACE.md          ← 이 파일
│   ├── service-map.md
│   └── ...
└── agent-workspace/          ← 에이전트 작업 디렉토리
    ├── REPOS.md              ← 레포-브랜치 매핑 + 워킹트리 전략
    ├── EXAMPLE_DEBUG.md      ← result.md 출력 예시
    ├── repos/                ← bare repos
    │   ├── viv-monorepo.git/
    │   ├── project-201-server.git/
    │   ├── project-201-flutter.git/
    │   ├── if-character-chat-server.git/
    │   ├── if-character-chat-client.git/
    │   ├── hokki-server.git/
    │   └── hokki_flutter_app.git/
    └── worktrees/            ← 세션별 마운트 (자동 생성/삭제)
```

---

## 2. 초기 세팅

### 2-1. agent-workspace 디렉토리 생성

```bash
mkdir -p viv-monorepo/agent-workspace/repos
```

### 2-2. bare repo 클론

GitHub 토큰이 포함된 URL로 클론한다. 토큰은 환경변수에서 읽는다:

```bash
cd viv-monorepo/agent-workspace

GITHUB_TOKEN=<token>
ORG=mesher-labs

repos=(
  viv-monorepo
  project-201-server
  project-201-flutter
  if-character-chat-server
  if-character-chat-client
  hokki-server
  hokki_flutter_app
)

for repo in "${repos[@]}"; do
  git clone --bare \
    "https://${GITHUB_TOKEN}@github.com/${ORG}/${repo}.git" \
    "repos/${repo}.git"
done
```

### 2-3. 참조 문서 확인

- `agent-workspace/REPOS.md` — 레포별 브랜치 전략 및 워킹트리 사용법
- `agent-workspace/EXAMPLE_DEBUG.md` — 에이전트 result.md 출력 예시

---

## 3. 인그레스 서버 실행

### 환경변수

| 변수 | 설명 |
|------|------|
| `SLACK_APP_TOKEN` | Slack Socket Mode 앱 토큰 (`xapp-...`) |
| `SLACK_BOT_TOKEN` | Slack 봇 토큰 (`xoxb-...`) |
| `GATEWAY_URL` | agent gateway 주소 (기본값: `http://localhost:3456`) |
| `ANTHROPIC_API_KEY` | Anthropic API 키 |

### 실행

```bash
cd viv-monorepo/claude-agent-sdk-test

# gateway (에이전트 실행 서버)
node server.mjs

# ingress (Slack 이벤트 수신)
node ingress.mjs
```

---

## 4. bare repo 업데이트

레포 목록 전체 fetch (최신 코드 동기화):

```bash
for r in viv-monorepo/agent-workspace/repos/*.git; do
  git -C "$r" fetch --all --prune
done
```

에이전트가 분석 시작 시 해당 레포를 fetch하므로 수동 실행은 필수가 아니다.

---

## 5. 워킹트리 잔여물 정리

에이전트가 비정상 종료된 경우 worktrees가 남을 수 있다:

```bash
# 잔여 워킹트리 확인
for r in viv-monorepo/agent-workspace/repos/*.git; do
  git -C "$r" worktree list
done

# 수동 정리
git -C repos/<레포>.git worktree remove --force worktrees/<경로>
```
