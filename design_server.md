# Agent Secretary — 서버 아키텍처 설계

이 문서는 [`design.md`](design.md) 의 PR 리뷰 시스템을 일반화하여, 다양한 채널·작업 타입을 지원하는 4-레이어 파이프라인 아키텍처를 정의한다. 구현 에이전트는 이 문서와 `design.md`, `prompts/` 만 읽고도 PoC 골격을 만들 수 있어야 한다.

---

## 1. 개요

```
[외부 채널]                                                              [외부 채널]
    │                                                                          ▲
    │ webhook/event                                                  channel API│
    ▼                                                                          │
┌──────────────┐  ack    ┌─ Q1 ─┐    ┌──────────────┐    ┌─ Q2 ─┐    ┌──────────────┐    ┌─ Q3 ─┐    ┌──────────────┐
│  Ingress     │────────>│ raw  │───>│  Core        │───>│ task │───>│   Agents     │───>│result│───>│  Egress      │
│  server      │ <2초   │event │    │  server      │    │ specs│    │ (Claude Agent│    │events│    │  server      │
│              │        └──────┘    │ • 분류       │    └──────┘    │  SDK)        │    └──────┘    │              │
│ • 인증       │                    │ • 워크플로우 │                │ • 페르소나   │                │ • 채널별     │
│ • 정규화     │                    │   선택       │                │ • 워크플로우 │                │   포매팅     │
│ • 즉시 ack   │                    │              │                │   실행       │                │ • 재시도/DLQ │
└──────────────┘                    └──────────────┘                └──────────────┘                └──────────────┘
```

### 핵심 원칙

- **단방향 파이프라인**: 모든 단계는 큐로 분리. 동기 호출 없음.
- **단계마다 단일 책임**: ingress 는 받기만, core 는 분류만, agents 는 실행만, egress 는 보내기만.
- **At-least-once delivery + 멱등성**: 모든 큐는 at-least-once. agents 는 `task_id` 기반 dedup 으로 중복 처리 방지.
- **`response_routing` 캐리**: ingress 에서 결정된 응답 경로(들)이 RawEvent → TaskSpec → ResultEvent 까지 그대로 전달됨.

---

## 2. 레이어별 책임

| 레이어 | 입력 | 출력 | 책임 | 안 하는 것 |
|---|---|---|---|---|
| **Ingress** | HTTP webhook, CLI 호출 | Q1: `RawEvent` | 채널별 인증 검증, payload 정규화, 즉시 ack (< 2초) | 코드 분석, 분류, LLM 호출 |
| **Core** | Q1: `RawEvent` | Q2: `TaskSpec` | 작업 분류 (어떤 워크플로우?), 워크플로우 입력 구성 | 워크플로우 *실행* |
| **Agents** | Q2: `TaskSpec` | Q3: `ResultEvent` | 워크플로우 실행 (Claude Agent SDK), 페르소나/CTO 호출, 결과 생성 | 외부 채널 직접 호출 |
| **Egress** | Q3: `ResultEvent` | 외부 채널 API | 채널·메시지 타입별 포매팅, 채널 API 호출, 재시도/DLQ | 작업 내용 판단 |

---

## 3. Skill vs Workflow 경계

Agents 레이어가 한 작업을 *어떻게 처리할지* 의 경계 결정 룰:

> **다수 LLM 에이전트의 코디네이션이 필요한가?**
> - **No → Skill** (한 에이전트 안에서 도구 호출 한두 번)
> - **Yes → Core 가 소유한 Workflow** (별개 에이전트들의 순차/병렬 협업)

기준은 *작업 복잡도* 가 아닌 *에이전트 경계를 넘는가* 이다.

### 매핑 예시

| 작업 | 분류 | 이유 |
|---|---|---|
| GitHub PR 코멘트 게시 | Skill | 도구 호출 1번 |
| GitHub PR 등록 (브랜치 + 푸시 + open) | Skill | 도구 여러 번이지만 한 에이전트 세션 |
| 파일 읽고 분석 | Skill | 분석 에이전트의 자체 능력 |
| **PR 리뷰** | **Workflow** | 디스패처 → 페르소나 N개 → CTO (별개 에이전트) |
| **분석 → 자동 수정 → PR 등록** | **Workflow** | 분석 에이전트 → 수정 에이전트 (별개) |
| 코드 수정 단독 | Skill (수정 에이전트 안에서) | 한 에이전트가 자기 세션에서 완결 |

---

## 4. 데이터 모델

모두 Pydantic v2 모델. 공유 패키지 `packages/schemas/` 에 정의.

### `RawEvent` — Ingress 출력

```python
class RawEvent(BaseModel):
    event_id: str                  # uuid, dedup 키
    source_channel: str            # "github" | "slack" | "cli" | ...
    received_at: datetime
    raw_payload: dict              # 채널 원본 (디버깅·재처리용)
    normalized: dict               # 채널이 추출한 표준 필드
    response_routing: ResponseRouting

class ResponseRouting(BaseModel):
    primary: ChannelTarget         # 주 응답 경로
    additional: list[ChannelTarget] = []   # 추가 fanout (예: PR 코멘트 + Slack 알림)

class ChannelTarget(BaseModel):
    channel: str                   # "github" | "slack" | ...
    target: dict                   # 채널-특화 (예: github = {repo, pr_number, installation_id})
```

### `TaskSpec` — Core 출력

```python
class TaskSpec(BaseModel):
    task_id: str                   # 결정론적 해시 = hash(event_id + workflow), dedup 키
    event_id: str                  # RawEvent 참조
    workflow: str                  # "pr_review" | "code_analyze" | "analyze_modify" | ...
    workflow_input: dict           # 워크플로우-특화 입력 (예: pr_review 는 PR 데이터)
    response_routing: ResponseRouting   # RawEvent 에서 캐리
    created_at: datetime
```

PoC 단계는 **이벤트 1개 → task 1개 (1:1)**. task 그래프는 나중 확장.

### `ResultEvent` — Agents 출력

```python
class ResultEvent(BaseModel):
    result_id: str
    task_id: str
    event_id: str
    workflow: str
    output: dict                   # 워크플로우-특화 (예: pr_review 는 cto_decision)
    summary_markdown: str          # 채널 무관 요약, egress 가 그대로 사용 가능
    response_routing: ResponseRouting
    completed_at: datetime
    trace_url: str | None          # trace store 의 영구 링크
```

### 페르소나/CTO 출력 스키마

`design.md §7, §8, §9.3` 의 스키마를 그대로 `packages/schemas/personas.py` 에 Pydantic 으로 정의.

---

## 5. 큐 설계

### Q1, Q2, Q3 — Redis Streams

| 큐 | Producer | Consumer | 메시지 |
|---|---|---|---|
| `raw_events` | Ingress | Core | `RawEvent` |
| `tasks` | Core | Agents | `TaskSpec` |
| `results` | Agents | Egress | `ResultEvent` |

각 consumer 는 Redis Streams 의 consumer group 으로 읽음 (`XREADGROUP` + `XACK`):
- 처리 성공 시 `XACK`
- 처리 실패 또는 미응답 시 다른 consumer 가 다시 가져감 (at-least-once)

### 멱등성

- Agents 는 `task_id` 를 키로 *처리 결과 캐시* 를 둔다 (Postgres 또는 Redis).
- 이미 완료된 `task_id` 가 다시 들어오면 캐시에서 ResultEvent 를 꺼내 다시 publish (실제 LLM 재호출 없음).
- Egress 도 `result_id` 기반 dedup (이미 deliver 된 결과 재전송 방지).

### DLQ (Dead Letter Queue)

- 각 큐에 대응되는 `*_dlq` 스트림. 재시도 N회 (기본 3) 실패 시 DLQ 로 이동.
- DLQ 메시지는 사람이 검토. 자동 재처리 안 함.

---

## 6. 워크플로우 정의

### 위치

Core 안의 *Python 코드* 로 정의. PoC 단계엔 YAML/DSL 불필요.

### 단순 DAG executor 만 필요

PoC 에 필요한 기능:

1. **순차 실행**
2. **병렬 fanout** (한 stage 출력으로 N 개 에이전트 호출)
3. **이전 stage 출력의 다음 stage 입력 주입**

조건 분기·루프·동적 stage 추가는 *필요할 때* 추가. 미리 만들면 죽은 추상화.

### `pr_review` 워크플로우

```python
# services/agents/src/agents/workflows/pr_review.py
async def pr_review(workflow_input: PrReviewInput) -> PrReviewOutput:
    # Stage 1: 디스패처
    activation = await call_agent("dispatcher", workflow_input.pr)

    # Stage 2: 활성화된 페르소나 병렬 실행
    persona_outputs = await asyncio.gather(*[
        call_agent(persona_name, workflow_input.pr, activation)
        for persona_name in activation.activated_leads + activation.activated_specialists
    ])

    # 2-1: specialist 출력을 lead 에 전달
    lead_outputs = synthesize_specialists_into_leads(persona_outputs)

    # Stage 3: CTO
    risk_metadata = compute_risk_metadata(workflow_input.pr)  # 결정론적
    cto_output = await call_agent(
        "cto",
        workflow_input.pr,
        activation,
        lead_outputs,
        risk_metadata,
    )

    return PrReviewOutput(cto_output=cto_output, ...)
```

각 페르소나의 시스템 프롬프트는 `prompts/leads/`, `prompts/specialists/`, `prompts/cto.md` 에서 로드 (Claude Agent SDK 의 system prompt 인자).

### 다른 워크플로우 (Phase 2+ 후보)

| 워크플로우 | 설명 |
|---|---|
| `code_analyze` | 단일 분석 에이전트 + skills (파일 읽기, grep). Workflow 가 아닌 단순 에이전트로도 표현 가능 — 분류 시 워크플로우 vs 단순 에이전트 호출 결정 |
| `analyze_modify` | 분석 에이전트 → 수정 에이전트 → (PR 등록은 수정 에이전트의 skill) |

---

## 7. `design.md` 와의 매핑

`design.md` 의 PR 리뷰 시스템은 이 아키텍처에서 **`pr_review` 워크플로우** 가 된다:

| design.md 컴포넌트 | 이 아키텍처에서의 위치 |
|---|---|
| 디스패처 (`design.md §6`) | `pr_review` 워크플로우의 Stage 1 — `dispatcher` 에이전트 |
| 페르소나 (lead·specialist) (`design.md §4`) | `pr_review` 워크플로우의 Stage 2 — 각 페르소나가 별도 에이전트 |
| CTO (`design.md §9`) | `pr_review` 워크플로우의 Stage 3 — `cto` 에이전트 |
| 페르소나 출력 스키마 (`design.md §7, §8`) | `packages/schemas/personas.py` 의 Pydantic 모델 |
| `risk_metadata` (`design.md §9.1`) | Core 또는 Agents 가 결정론적으로 계산 후 CTO 에이전트에 주입 |
| `pr_trace` 데이터 모델 (`design.md §11`) | Trace store (Postgres) 의 테이블 |
| 측정 지표 (`design.md §10`) | Trace store 에서 daily 잡으로 산출 |

---

## 8. 기술 스택

| 컴포넌트 | 선택 |
|---|---|
| 언어 | Python 3.11+ |
| Ingress 프레임워크 | FastAPI |
| Core / Agents / Egress | asyncio 기반 consumer 루프 (각 서비스 독립 프로세스) |
| 큐 | Redis Streams |
| Trace store | Postgres |
| 캐시 (멱등성) | Redis (별도 DB 또는 Postgres 와 공유) |
| LLM SDK | Anthropic SDK + **Claude Agent SDK** (페르소나 = subagent) |
| LLM 모델 매핑 | **CTO: `claude-opus-4-7`** / **그 외 (디스패처·lead·specialist): `claude-sonnet-4-6`** |
| 스키마 | Pydantic v2 (`packages/schemas/`) |
| 로깅 | structlog (구조화 JSON) |
| 컨테이너 | Docker + docker-compose (PoC), k8s (나중) |

---

## 9. 레포 구조 (모노레포)

```
agent-secretary/
├── design.md
├── design_server.md                     # 이 문서
├── prompts/                             # 페르소나 시스템 프롬프트 (이미 있음)
├── pyproject.toml                       # workspace root
├── packages/
│   └── schemas/                         # 공유 Pydantic 모델
│       ├── pyproject.toml
│       └── agent_secretary_schemas/
│           ├── events.py                # RawEvent, ResponseRouting, ChannelTarget
│           ├── tasks.py                 # TaskSpec
│           ├── results.py               # ResultEvent
│           └── personas.py              # PersonaOutput, LeadOutput, CtoOutput
├── services/
│   ├── ingress/
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   └── src/ingress/
│   │       ├── main.py                  # FastAPI app
│   │       ├── plugins/                 # 채널별 input 어댑터
│   │       │   ├── _base.py             # ChannelParser ABC
│   │       │   ├── github.py
│   │       │   └── cli.py
│   │       └── publisher.py             # raw_events 스트림 publish
│   ├── core/
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   └── src/core/
│   │       ├── main.py                  # consumer loop
│   │       ├── classifier.py            # RawEvent → workflow 결정
│   │       └── publisher.py             # tasks 스트림 publish
│   ├── agents/
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   └── src/agents/
│   │       ├── main.py                  # consumer loop
│   │       ├── runner.py                # 워크플로우 dispatch
│   │       ├── workflows/
│   │       │   └── pr_review.py
│   │       ├── personas/                # 페르소나 = 에이전트
│   │       │   ├── _base.py             # PersonaAgent base (Claude Agent SDK 래퍼)
│   │       │   ├── dispatcher.py
│   │       │   ├── leads/
│   │       │   ├── specialists/
│   │       │   └── cto.py
│   │       ├── skills/                  # 공유 skill (도구)
│   │       │   ├── github_pr.py
│   │       │   └── filesystem.py
│   │       ├── trace.py                 # Trace store 쓰기
│   │       └── publisher.py             # results 스트림 publish
│   └── egress/
│       ├── pyproject.toml
│       ├── Dockerfile
│       └── src/egress/
│           ├── main.py                  # consumer loop
│           ├── plugins/                 # 채널별 output 어댑터
│           │   ├── _base.py             # ChannelDeliverer ABC
│           │   ├── github.py
│           │   ├── slack.py
│           │   └── cli.py
│           └── retry.py                 # 재시도/DLQ
└── infra/
    ├── docker-compose.yml
    └── k8s/                             # Phase 2+
```

### 채널 플러그인 구조

PoC 단계엔 ingress/egress 가 각자 자기 plugins 디렉토리를 가짐. 같은 채널이 양쪽에 코드 (예: `ingress/plugins/github.py`, `egress/plugins/github.py`) — 약간의 중복 있지만 단순. 통합 채널 패키지로 리팩토링은 나중에.

---

## 10. 로컬 개발 환경

```yaml
# infra/docker-compose.yml (개요)
services:
  redis:
    image: redis:7
    ports: ["6379:6379"]

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: agent_secretary
      POSTGRES_USER: agent
      POSTGRES_PASSWORD: agent
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]

  ingress:
    build: ../services/ingress
    environment:
      REDIS_URL: redis://redis:6379
      GITHUB_WEBHOOK_SECRET: ${GITHUB_WEBHOOK_SECRET}
    ports: ["8080:8080"]
    depends_on: [redis]

  core:
    build: ../services/core
    environment:
      REDIS_URL: redis://redis:6379
    depends_on: [redis]

  agents:
    build: ../services/agents
    environment:
      REDIS_URL: redis://redis:6379
      DATABASE_URL: postgresql://agent:agent@postgres/agent_secretary
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
    depends_on: [redis, postgres]

  egress:
    build: ../services/egress
    environment:
      REDIS_URL: redis://redis:6379
      GITHUB_TOKEN: ${GITHUB_TOKEN}
      SLACK_TOKEN: ${SLACK_TOKEN}
    depends_on: [redis]

volumes:
  pgdata:
```

핫리로드는 각 서비스의 src/ 를 볼륨 마운트 + uvicorn `--reload` (ingress) / watchdog 기반 재시작 (다른 서비스).

---

## 11. 결정 정리

### 정해진 것 (이 문서가 가정)

- ✅ 4-레이어 분리 (Ingress / Core / Agents / Egress)
- ✅ 4 서비스 (옵션 C) — 모노레포, docker-compose
- ✅ Redis Streams 큐 (Q1, Q2, Q3) + DLQ
- ✅ Postgres trace store
- ✅ Core 가 워크플로우 owner. Skill 은 에이전트 내부.
- ✅ 페르소나당 에이전트 1개 (Claude Agent SDK)
- ✅ 1:1 task 매핑 (PoC). 그래프는 나중.
- ✅ at-least-once 큐 + `task_id` / `result_id` 기반 멱등성
- ✅ **LLM 모델 매핑** — CTO: `claude-opus-4-7` / 그 외: `claude-sonnet-4-6`
- ✅ **Slack 채널 플러그인** (Socket Mode + 양방향 어댑터, ingress/egress 분리 유지)
- ✅ **Workspace skill** — bare repo + worktree (`AGENT_WORKSPACE_DIR`, [`docs/workspace.md`](docs/workspace.md) 참조)
- ✅ **Slack-트리거 워크플로우** — `code_analyze` (실구현, Claude Agent SDK), `code_modify` / `linear_issue` (placeholder)
- ✅ **Dashboard** — ingress 안에 정적 HTML + `/api/traces` JSON API. 폴링 기반 (SSE 아님)

### 미정 (Open)

이 문서가 가정하지 않은, 구현 시작 전 또는 진행 중 결정 필요한 것들:

1. **Trace store 스키마 세부.** `pr_trace` 를 단일 테이블로 두고 있음. Slack 워크플로우 메타데이터(채널/서비스 컨텍스트)를 위한 별도 컬럼 분리는 보류.
2. **GitHub App vs OAuth.** 운영 환경에서 단일 GitHub App 방식 권장 (webhook + 코멘트 게시 권한).
3. **CLI 의 결과 수신 메커니즘.** 비동기 파이프라인에 동기 클라이언트가 붙는 방법: polling / SSE / WS.
4. **워크플로우 버전 관리.** 워크플로우 코드 변경 시 이미 큐에 있는 task 와의 호환성.
5. **`linear_issue` / `code_modify` 실구현.** 현재 placeholder. Linear API 통합 + 자동 PR 생성 로직 추가 필요.
6. **`design.md §12` 의 미정 결정점들.** 그쪽에 정의된 그대로 유효.

---

## 12. 우선순위 정렬된 구현 작업

이 순서로 구현하면 가장 빨리 *동작하는* PoC 가 나온다.

1. **모노레포 초기화** — `pyproject.toml`, 4 services 의 빈 골격, `packages/schemas/` 의 Pydantic 모델.
2. **infra/docker-compose.yml + Redis + Postgres** — 의존 인프라부터.
3. **Ingress 의 GitHub 플러그인** — webhook 수신, HMAC 검증, RawEvent 정규화, raw_events 스트림 publish, ack 응답.
4. **Core 의 분류기** — RawEvent 받아 `pr_review` workflow 로 라우팅, TaskSpec 생성, tasks 스트림 publish.
5. **Agents 의 `pr_review` 워크플로우 + 단일 페르소나 (예: 품질 lead) 만 동작** — Claude Agent SDK 호출, persona 출력 스키마 검증, ResultEvent publish.
6. **Egress 의 GitHub 플러그인** — ResultEvent 받아 PR 에 코멘트 게시, 재시도/DLQ.
7. **나머지 lead 4개 + dispatcher + cto 에이전트 추가**.
8. **specialist 에이전트 추가 + lead 의 specialist 출력 흡수 로직 구현**.
9. **Trace store 쓰기** — agents 가 모든 stage 출력을 Postgres 의 `pr_trace` 에 저장.
10. **CLI 채널 플러그인** — 수동 dry-run.
11. **`human_decision` 채우는 webhook + KPI 계산 잡** — `design.md §10` 의 측정 지표 산출.

각 단계에서 `design.md` 의 *Phase 1 액션 없음* 원칙은 변하지 않는다 — Egress 의 GitHub 플러그인은 PR 코멘트만 게시, 머지/거부/라벨링 X.
