# 기능 테스트 체크리스트

전체 시스템의 사용자 가시 기능 + 내부 메커니즘. 자동 테스트가 가능한 건 모두 갖춰졌고, 라이브 의존성이 필요한 건 §10 의 수동 시나리오로 검증한다.

상태 표기:
- ✅ 자동 테스트 존재 (`tests/`)
- 🧪 자동 테스트로는 불충분 — 실제 외부 시스템 (Slack/GitHub/Anthropic API/Postgres/Redis) 으로 검증
- ⚠️ 갭 — 의도되었으나 아직 검증되지 않음
- 🚫 의도적으로 범위 외 (Phase 1 의 "액션 없음" 등)

현재 자동 테스트: **167 passing**.

---

## 1. PR 리뷰 파이프라인

### 1.1 GitHub webhook 수신 (ingress)

| 항목 | 상태 |
|---|---|
| HMAC SHA-256 서명 검증 통과 | ✅ `test_github_ingress.py` (parametrized) |
| 잘못된 서명 → 401 반환 | ✅ |
| `pull_request.opened` / `synchronize` / `reopened` 정규화 | ✅ |
| `ping` 이벤트 → ack 만, RawEvent 발행 X | ✅ |
| draft PR → 무시 | ✅ |
| `closed` 등 미지원 action → 무시 | ✅ |
| 미지원 이벤트 타입 → 무시 + 로그 | ✅ |
| `delivery_id` 없을 때 uuid fallback | ✅ |
| `response_routing.primary` 가 GitHub 채널 + repo/pr_number 보존 | ✅ |
| 수신 후 webhook 응답 < 2초 (즉시 ack, 비동기 publish) | 🧪 (라이브) |

### 1.2 Core 분류 (1:1 모드)

| 항목 | 상태 |
|---|---|
| `pr_*` 트리거 → `pr_review` task 발행 | ✅ |
| `manual` (CLI) 트리거 → 동일 처리 | ✅ |
| 알 수 없는 트리거 → DLQ | ✅ |
| `task_id` = `sha256(event_id + workflow)[:32]` 결정론적 | ✅ |

### 1.3 Agents — pr_review 워크플로우

| 항목 | 상태 |
|---|---|
| 디스패처 → 활성화 leads 결정 | ✅ |
| 활성화된 lead 만 호출 | ✅ |
| Specialist 활성화 시 lead 가 출력 흡수 | ✅ |
| CTO 가 `decision/confidence/reasoning` 산출 | ✅ |
| `risk_metadata` 결정론적 계산 (per-repo rules) | ✅ |
| Specialist–lead 의견 불일치 → `unresolved_specialist_dissent` | ⚠️ (스키마는 있으나 시나리오 테스트 없음) |
| CTO 가 *새 코드 우려를 만들지 않음* | 🧪 (프롬프트 가드레일) |
| `domain_relevance` 낮은 페르소나의 영향력 자동 감소 | 🧪 |
| 페르소나 출력 JSON 파싱 실패 시 → `PersonaCallError` | ✅ `test_persona_json_extraction.py` |
| `high_risk_paths_touched` 비어있지 않으면 escalate | 🧪 (LLM 거동) |

### 1.4 Agents — 페르소나 출력 가드레일

| 항목 | 상태 |
|---|---|
| 보안 lead: 구체적 위협 시나리오 없으면 finding 안 만듦 | 🧪 |
| 품질 lead: 스타일 nitpick blocking 금지 | 🧪 |
| 운영 lead: "롤백 계획 필요" 보일러플레이트 금지 | 🧪 |
| 호환성 lead: 신규 추가는 breaking 아님 | 🧪 |
| 제품·UX lead: 코드만으로 판단 어려우면 self_confidence 낮춤 | 🧪 |
| 설정 분리 specialist: 진짜 상수에 finding 안 만듦 | 🧪 |

### 1.5 Trace store (`pr_trace`)

| 항목 | 상태 |
|---|---|
| DDL idempotent (`CREATE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS`) | 🧪 (실 Postgres 필요) |
| 모든 stage 출력 JSONB 컬럼에 저장 | ⚠️ (write 경로 단위 테스트 없음) |
| 같은 task_id 재실행 시 `ON CONFLICT UPDATE` | 🧪 |
| `detail_markdown` 컬럼 채워짐 | ⚠️ |
| **신규**: `token_usage` JSONB (per-model 토큰 + 캐시) | ✅ `test_usage_accumulator.py` (writer 자체는 🧪) |
| **신규**: `duration_ms` INTEGER | ✅ (집계는) / 🧪 (writer) |
| **신규**: `repo_full_name` TEXT (그룹별 집계용) | 🧪 |
| `human_decision` 은 NULL 로 시작 | 🚫 (D 항목 미구현) |

### 1.6 Egress (GitHub 코멘트)

| 항목 | 상태 |
|---|---|
| ResultEvent 받아 PR 코멘트 게시 | ⚠️ |
| `GITHUB_TOKEN` 미설정 시 skip + 경고 | ⚠️ |
| 재시도 (HTTP 4xx/5xx) | ⚠️ |
| DLQ 이동 (MAX_DELIVERIES 초과) | ⚠️ |
| **머지/거부/라벨링 안 함** (Phase 1 액션 없음) | 🚫 |

---

## 2. Slack 워크플로우

### 2.1 Slack ingress (Socket Mode)

| 항목 | 상태 |
|---|---|
| Socket Mode 연결 (`SLACK_APP_TOKEN`) | 🧪 |
| `app_mention` 키워드 분류 | ✅ |
| 키워드 매칭 → RawEvent 발행 + hourglass 반응 | ✅ `test_slack_ingress.py` |
| 키워드 미매칭 → 버튼 블록 게시 | ✅ |
| 빈 멘션 → 버튼 블록 게시 | ✅ |
| 버튼 클릭 (`cmd_debug`/`cmd_fix`/`cmd_issue`) → RawEvent 발행 | ✅ |
| 버튼 메시지 자동 삭제 | ✅ |
| 알 수 없는 action_id → 아무것도 안 함 | ✅ |
| 깨진 block_id → publish 안 함 (조용히 실패) | ✅ |
| 스레드 컨텍스트 fetch 실패 → 빈 리스트 (mention 처리 계속) | ✅ |
| 채널 ID → service_map 해석 | ✅ |
| `response_routing.primary.target` 에 timestamps 보존 | ✅ |

### 2.2 Slack egress (메시지 + 반응)

| 항목 | 상태 |
|---|---|
| `summary_markdown` 을 thread 메시지로 게시 | ✅ |
| `trace_url` 있을 때 `📄 <url\|Full report>` 링크 추가 | ✅ |
| 파일 업로드 코드 경로 *완전 제거* | ✅ |
| hourglass → ✅/❌ 반응 스왑 | ✅ |
| 에러 결과 → ❌ 반응 | ✅ |
| `SLACK_BOT_TOKEN` 미설정 시 skip | ✅ |
| `channel_id` 누락 시 skip | ✅ |
| Slack API 에러 → 로그 + DLQ | ⚠️ |

### 2.3 Workflow: code_analyze (실구현)

| 항목 | 상태 |
|---|---|
| service_resolution 의 repos 모두 worktree 마운트 | ✅ |
| env 별 적절한 브랜치 선택 | ✅ |
| Claude Agent SDK 호출 (`bypassPermissions`) | ⚠️ (mock 만; 실 호출 검증 필요) |
| `{메시지, 파일}` JSON 추출 | ✅ |
| service 미매칭 채널 → 에러 result | ✅ |
| 마운트된 worktree → context exit 시 자동 정리 | ✅ |

### 2.4 Workflow: code_modify / linear_issue (placeholder)

| 항목 | 상태 |
|---|---|
| `🚧 구현 중` 메시지 + detail 반환 | ✅ |
| WorkflowRunner 가 placeholder 로 라우트 (LLM 호출 없음) | ✅ |

---

## 3. Workspace skill (bare repo + worktree)

| 항목 | 상태 |
|---|---|
| `AGENT_WORKSPACE_DIR` 미설정 → 즉시 RuntimeError | ✅ |
| 명시 설정 사용 | ✅ |
| `ensure_bare_repo` idempotent | ✅ |
| `mount` (`--detach`) 같은 브랜치 동시 마운트 가능 | ✅ |
| Context exit 시 worktree 정리 | ✅ |
| Context 내 예외 발생해도 정리됨 | ✅ |
| 브랜치명에 `/` 포함 → slug 변환 | ✅ |
| `GITHUB_TOKEN` 없을 때 plain HTTPS clone (gh credential helper) | 🧪 |
| Stale worktree 자동 제거 | ⚠️ |

---

## 4. Configuration / domain constants

### 4.1 service_map / channels / pricing

| 항목 | 상태 |
|---|---|
| 4 services × 7 unique repos × 23 service-bound channels | ✅ |
| `resolve_channel(known_service_channel)` → service + env + repos | ✅ |
| Known-other 채널 fallback | ✅ |
| Unknown 채널 → 원본 ID | ✅ |
| `find_repo` / `review_rules_for` | ✅ |
| **신규**: `MODEL_PRICES` + `cost_usd()` 함수 | ✅ `test_operations_aggregator.py` |
| 캐시 read 10% / write 125% 가격 | ✅ |
| 알 수 없는 모델 → cost 0 + unknown_models 리포트 | ✅ |

### 4.2 Per-repo review rules

| 항목 | 상태 |
|---|---|
| 7 레포 모두 review_rules 채워짐 (또는 의도적 omit + fallback) | ✅ |
| omit → fallback (`if-character-chat-client`) | ✅ |
| `_compute_risk_metadata` 가 repo 별 rules 사용 | ✅ |
| 미지의 repo → 모듈 default fallback | ✅ |

### 4.3 환경변수 검증

| 항목 | 상태 |
|---|---|
| `ANTHROPIC_API_KEY` 미설정 → agents RuntimeError | ✅ `test_agents_settings.py` |
| `AGENT_WORKSPACE_DIR` 동일 | ✅ |
| 빈 문자열 optional vars (`DATABASE_URL=""`) → None 처리 | ✅ |
| 도커 컴포즈에서 모든 env 가 적절히 전달 | 🧪 |

---

## 5. Dashboard

### 5.1 기본 (인덱스 + trace 목록 + 디테일)

| 항목 | 상태 |
|---|---|
| `/` 가 index.html 반환 | ✅ |
| `/api/traces` paginated | ✅ |
| `/api/traces/{task_id}` 존재/미존재 처리 | ✅ |
| `DATABASE_URL` 미설정 → 503 | ✅ |
| 클라이언트 30초 폴링 갱신 | 🧪 |
| ingress `/health` 응답 | ✅ `test_ingress_health.py` |

### 5.2 Trace 목록 필터 (B2)

| 항목 | 상태 |
|---|---|
| `decision` 필터 (auto-merge/request-changes/escalate-to-human/none) | ✅ |
| `workflow` 필터 (5 종) | ✅ |
| `range` 필터 (1h/6h/24h/7d/30d/all) | ✅ |
| 필터값 화이트리스트 검증 → 400 | ✅ |
| `none` 센티넬 → SQL `IS NULL` | ✅ |
| URL 쿼리스트링 sync (reload 시 유지) | 🧪 (브라우저) |

### 5.3 검색 (D1)

| 항목 | 상태 |
|---|---|
| `?q=` → task_id / event_id / pr_metadata::text ILIKE OR | ✅ |
| 빈/공백 q → 무필터로 처리 | ✅ |
| 250ms debounce | 🧪 (브라우저) |

### 5.4 KPI 요약 카드 (B1)

| 항목 | 상태 |
|---|---|
| `/api/stats/decisions?range=…` 응답 | ✅ |
| total / per-decision counts / escalation_rate / avg_confidence | ✅ |
| Range token 화이트리스트 검증 | ✅ |
| 빈 테이블 → all zeros | ✅ |
| Range 변경 시 카드 + 히스토그램 동시 갱신 | 🧪 (브라우저) |

### 5.5 Confidence histogram (B3)

| 항목 | 상태 |
|---|---|
| `/api/stats/confidence` → 10 bins | ✅ |
| 클램프 (>1, <0 처리) | 🧪 (실 데이터로) |
| SVG 색 구분 (lo/mid/hi) | 🧪 (브라우저) |

### 5.6 A/B 비교 (B4)

| 항목 | 상태 |
|---|---|
| `/api/stats/ab?range=…` JOIN 결과 | ✅ |
| `/api/compare/{event_id}` 양쪽 trace | ✅ |
| 한쪽만 완료 시 200 + shadow=null | ✅ |
| `/compare/{event_id}` HTML 페이지 | ✅ |
| Trace 행에서 `A/B ↗` 링크 | 🧪 (브라우저) |
| Disagreement 만 강조 표시 | 🧪 (브라우저) |

### 5.7 Queue/DLQ health (C1)

| 항목 | 상태 |
|---|---|
| `/api/health/queues` 응답 | ✅ |
| Stream age = stream ID timestamp 파싱 | ✅ |
| 시계 skew 시 0 으로 클램프 | ✅ |
| 비정상 ID → None | ✅ |
| Snapshot 실패 → 503 (500 X) | ✅ |
| 비교 색 구분 (alert/crit) | 🧪 (브라우저) |
| 10초 폴링 | 🧪 |

### 5.8 Cost + latency (C3)

| 항목 | 상태 |
|---|---|
| `/api/stats/operations` 응답 | ✅ |
| Per-model 토큰 합산 | ✅ |
| Cost USD 계산 (cache 포함) | ✅ |
| p50 / p95 latency | ✅ |
| Null duration_ms 스킵 | ✅ |
| Unknown model 플래그 | ✅ |

### 5.9 Per-repo / per-channel breakdown (D2)

| 항목 | 상태 |
|---|---|
| `/api/stats/by_repo` decision 분포 | ✅ |
| `/api/stats/by_channel` 동일 | ✅ |
| escalation_rate 행별 계산 | ✅ |
| total=0 안전 (no zerodiv) | ✅ |
| 우측 패널 비어있을 때 표시 | 🧪 (브라우저) |
| Tab 스위치 (repo ↔ channel) | 🧪 (브라우저) |

### 5.10 Report viewer (`/static/reports/{task_id}`)

| 항목 | 상태 |
|---|---|
| HTML — 마크다운 → HTML | ✅ |
| Raw `.md` 라우트 (greedy 매치 우회) | ✅ |
| 미존재/빈 detail → 404 | ✅ |
| `DATABASE_URL` 미설정 → 503 | ✅ |
| Decision 별 CSS 클래스 | ✅ |
| CF Zero Trust 인증 | 🧪 (인프라) |

---

## 6. A/B 테스트 (페르소나 vs 모놀리식)

| 항목 | 상태 |
|---|---|
| `PR_REVIEW_AB_MODE=false` (기본) → task 1개 | ✅ |
| `PR_REVIEW_AB_MODE=true` → task 2개 (primary + shadow) | ✅ |
| Shadow 와 primary 의 `event_id` 동일, `task_id` 다름 | ✅ |
| Slack 워크플로우는 ab 모드와 무관 | ✅ |
| `TaskSpec.shadow=True` → publish_result 스킵 | ⚠️ (라이브로만 확인됨) |
| Shadow task 도 trace 에 기록 | ⚠️ |
| Monolithic 도 Opus 사용 | ✅ (코드 검증) |
| 비교 SQL JOIN | ✅ (`/api/stats/ab` + `/api/compare/{event_id}`) |

---

## 7. Cross-cutting

### 7.1 Redis Streams

| 항목 | 상태 |
|---|---|
| Consumer group 생성 idempotent | ⚠️ |
| `XREADGROUP` 으로 메시지 소비 | 🧪 |
| 정상 처리 시 `XACK` | 🧪 |
| 실패 + `delivery >= MAX_DELIVERIES` → DLQ | ⚠️ |
| Pending list 재배달 | 🧪 |
| At-least-once + idempotency (현재 dedup 캐시 미구현) | 🧪 |

### 7.2 워크플로우 dispatcher

| 항목 | 상태 |
|---|---|
| `pr_review` → PrReviewRunner | ✅ |
| `pr_review_monolithic` → MonolithicReviewRunner | ✅ |
| `code_analyze` → CodeAnalyzeRunner | ✅ |
| placeholders → PlaceholderRunner | ✅ |
| 알 수 없는 workflow → DLQ | ⚠️ |

### 7.3 Token usage 회계 (C2)

| 항목 | 상태 |
|---|---|
| `usage_scope()` 컨텍스트 내 자동 record | ✅ |
| 두 task 동시 실행 시 분리 (contextvars) | ✅ |
| 외부에서 record → no-op | ✅ |
| Per-model 분류 (opus/sonnet) | ✅ |
| Cache tokens (read/write) 합산 | ✅ |
| 빈 scope → 모든 0 (None X) | ✅ |
| Nested scope isolation | ✅ |

### 7.4 lifecycle (start/stop)

| 항목 | 상태 |
|---|---|
| Ingress: 모든 plugin start/stop | ⚠️ |
| Slack plugin: socket connect/disconnect | 🧪 |
| TraceReader connect/close | 🧪 |
| QueueHealth connect/close | 🧪 |
| 실패 시에도 cleanup (finally) | ⚠️ |

---

## 8. 운영 절차

| 항목 | 상태 |
|---|---|
| `docker-compose up` 으로 모든 서비스 부팅 | 🧪 |
| ingress `/health` 응답 | ✅ |
| Postgres 가 올라온 뒤 agents/ingress 시작 | 🧪 |
| `agent_workspace` 도커 볼륨 영구 보존 | 🧪 |
| 로그 구조화 JSON | 🧪 |
| GitHub webhook 도달 (CF / 터널링) | 🧪 |
| Slack Socket Mode 자동 재연결 | 🧪 |

---

## 9. 명시적 제외 (Phase 1)

| 항목 | 상태 |
|---|---|
| GitHub PR 자동 머지 / 라벨링 / 상태 변경 | 🚫 |
| `human_decision` 캡처 | 🚫 |
| KPI 일일 잡 | 🚫 |
| Trace 보존 정책 | 🚫 |
| `code_modify` / `linear_issue` 실구현 | 🚫 |

---

## 10. 수동 테스트 시나리오 (라이브)

운영 진입 전 한 번씩 돌려보면 좋은 시나리오. 위에 🧪 로 표시된 것들의 거의 전부가 여기 포함됨.

### 10.1 부팅 + 헬스 체크 (3분)

준비:
```bash
docker-compose up -d
docker-compose ps  # 모든 서비스 healthy
```

확인:
- [ ] `curl http://localhost:8000/health` → `{"status":"ok"}`
- [ ] `curl http://localhost:8000/` → 대시보드 HTML
- [ ] Postgres 연결: `docker-compose logs ingress | grep dashboard.trace_reader.connected`
- [ ] Redis 연결: `docker-compose logs ingress | grep dashboard.queue_health.connected`
- [ ] 5 stream 상태: `docker-compose exec redis redis-cli XLEN raw_events tasks results raw_events_dlq tasks_dlq results_dlq`

### 10.2 GitHub PR 골든 패스 (10분)

준비:
- 테스트 레포 (예: `mesher-labs/sandbox`) 의 webhook 을 ingress 에 연결
- 단순한 PR 1개 open

확인:
- [ ] webhook 응답 < 2초 (curl-trace 또는 GitHub UI 의 delivery 리스트)
- [ ] `XLEN raw_events` 1 증가 → 잠시 후 0 (core 가 소비)
- [ ] `XLEN tasks` 1 증가 → 0 (agents 소비)
- [ ] `XLEN results` 1 증가 → 0 (egress 소비)
- [ ] PR 에 봇 코멘트 게시됨 (decision 포함)
- [ ] 대시보드 (`/`) 새 trace 행 등장
- [ ] 행 클릭 → 우측에 detail 표시 (Summary, CTO output, Risk metadata, Lead/Specialist outputs 모두)
- [ ] **신규**: KPI 카드 total/auto-merge/request-changes/escalate 숫자 갱신
- [ ] **신규**: Confidence 히스토그램에 한 막대 등장
- [ ] **신규**: ops 카드에 cost (>$0) + duration_ms 표시
- [ ] **신규**: queues 카드 모두 0 / 정상

### 10.3 Slack 골든 패스 (10분)

준비:
- 등록된 채널 (`if-payment-production` 등) 에 봇 초대

확인:
- [ ] `@봇 분석` 멘션 → hourglass 즉시 추가
- [ ] 잠시 후 hourglass → ✅ 스왑, summary 메시지 게시
- [ ] 메시지 끝 `📄 <url|Full report>` 링크 클릭 → CF Zero Trust 인증 → 마크다운 렌더 페이지
- [ ] 페이지의 코드 펜스/테이블/decision badge 모두 정상
- [ ] 빈 멘션 (`@봇`) → 버튼 블록 게시
- [ ] 버튼 (`debug` / `fix` / `issue`) 클릭 → 버튼 메시지 자동 삭제 + hourglass 시작
- [ ] 알 수 없는 채널에서 멘션 → service_resolution=null → 에러 메시지 + ❌

### 10.4 A/B 모드 (15분)

준비:
```bash
PR_REVIEW_AB_MODE=true docker-compose up -d core agents
```

확인:
- [ ] 테스트 PR open → tasks 큐에 *2개* (primary + shadow)
- [ ] Slack/PR 코멘트는 *primary 만* (shadow 는 무음)
- [ ] 대시보드 trace 목록에 두 행 (workflow=`pr_review`, `pr_review_monolithic`)
- [ ] **신규**: 두 행에 `A/B ↗` 링크 표시
- [ ] **신규**: 링크 클릭 → `/compare/{event_id}` 페이지 양쪽 정상 렌더
- [ ] **신규**: 결정 일치 시 `✓ AGREE` badge, 다르면 `✗ DISAGREE`
- [ ] **신규**: 메인 대시보드 ab-row 에 agreement rate + disagreement 링크 표시
- [ ] 한쪽만 완료된 상태에서 `/compare/{event_id}` → `한쪽 워크플로우만 완료됨` 메시지

### 10.5 대시보드 인터랙션 (10분)

확인:
- [ ] 헤더 검색 박스에 task_id (앞 8자) → 한 행만 표시
- [ ] event_id 입력 → 같은 동작
- [ ] repo full_name (예: `mesher-labs/project-201`) 부분 입력 → 해당 repo 행만
- [ ] 검색 후 URL `?q=…` 추가됨 → 새 탭에 같은 URL 붙여넣기 → 동일 결과
- [ ] decision 필터 = `auto-merge` → auto-merge 만
- [ ] workflow 필터 = `pr_review_monolithic` → shadow 만
- [ ] range 1h/6h/24h/… 변경 → KPI / 히스토그램 / ops / breakdown 모두 갱신
- [ ] `clear` → 필터/검색 모두 초기화 + URL 깨끗
- [ ] 우측 패널 (no selection) → repo 별 breakdown 테이블
- [ ] `by channel` 탭 클릭 → channel 별 테이블
- [ ] 행 클릭 → trace detail 표시, deselect 후 다시 breakdown
- [ ] 헤더 `↻ refresh` → 모든 카드 즉시 재요청

### 10.6 Queue 헬스 카드 시뮬레이션 (10분)

준비:
- agents 만 멈춤: `docker-compose stop agents`
- 새 PR open

확인:
- [ ] queues 카드 `tasks` 막대가 빨강/노랑으로 변함 (depth + age 증가)
- [ ] `pending` 카운트 증가 (XREADGROUP 으로 읽었지만 ack 안 함)
- [ ] agents 다시 켜기: `docker-compose start agents` → 잠시 후 0 으로 회복
- [ ] DLQ 강제 시뮬레이션: redis-cli 로 broken 메시지 직접 publish → 재시도 후 dlq_x 증가 → 카드에 빨강 + dlq 표시

### 10.7 Operations 카드 검증 (5분)

확인:
- [ ] PR 1개 처리 후 ops 카드: `1 run`, cost 표시, p50=p95=avg (1개 샘플)
- [ ] AB 모드 PR → cost 가 1개 PR 대비 ~50-60% 증가 (Opus 1회 추가)
- [ ] 대시보드 `unknown model` 경고 안 보임 (`MODEL_PRICES` 에 모두 등록되어 있어야)
- [ ] DB 직접 쿼리: `SELECT token_usage, duration_ms FROM pr_trace ORDER BY created_at DESC LIMIT 1;` → JSONB + ms 모두 채워짐

### 10.8 실패 모드 (15분)

준비 + 확인:
1. **Postgres 죽이기** → 새 PR 처리 → trace.write 실패 → ResultEvent publish *되지 않음* (fail-stop), ack 안 됨 → Postgres 회복 후 재배달 정상
2. **Anthropic 5xx 시뮬레이션** (네트워크 차단 등) → 3회 재시도 후 DLQ → 대시보드 queue 카드 dlq 빨강
3. **Slack 토큰 만료** → egress 가 slack API 에러 → results DLQ
4. **HMAC 위조** webhook 직접 호출 → 401 (Slack 헤더 없는 것도 동일)
5. **GitHub draft PR 생성** → 무시됨 (raw_events 큐 안 늘어남)

---

## 11. 갭 정리 (운영 진입 전)

자동 테스트로 메꿀 수 있는 잔여 갭 (모두 ⚠️):

| # | 항목 | 위치 |
|---|---|---|
| 1 | Trace store `write()` 단위 테스트 (psycopg async mock 또는 실 DB) | 1.5 |
| 2 | Egress GitHub plugin 테스트 (PR 코멘트 게시 + DLQ) | 1.6 |
| 3 | DLQ 이동 시나리오 통합 테스트 (모든 큐) | 7.1, 1.6, 2.2 |
| 4 | `agents/main.py` shadow 분기 단위 테스트 | 6 |
| 5 | Specialist–lead 의견 불일치 시나리오 | 1.3 |
| 6 | Stale worktree 자동 제거 시나리오 | 3 |
| 7 | UnknownWorkflowError → DLQ | 7.2 |
| 8 | 라이프사이클 finally 경로 | 7.4 |

각 1-2시간이면 채울 수 있음. 그 외 🧪 는 운영 환경에서만 검증 가능.

---

## 12. 자동 테스트 현황 한 눈에

```
$ uv run pytest -q
167 passed
```

서비스/패키지별 분포:
- `test_github_ingress.py` — 16
- `test_slack_ingress.py` — 16 (분류 + mention/interactive)
- `test_slack_egress.py` — 8
- `test_persona_json_extraction.py` — 10
- `test_dashboard.py` — 38
- `test_operations_aggregator.py` — 8
- `test_usage_accumulator.py` — 9
- `test_reports.py` — 7
- `test_review_rules.py`, `test_service_map.py` — 17
- `test_pipeline_smoke.py`, `test_code_analyze.py`, `test_workspace_skill.py`, `test_monolithic_review.py`, `test_shadow_task.py`, `test_placeholder_workflows.py` — 28
- `test_agents_settings.py` — 4
- `test_ingress_health.py` — 2
- 기타 — 4
