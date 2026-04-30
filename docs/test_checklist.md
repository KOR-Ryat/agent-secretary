# 기능 테스트 체크리스트

전체 시스템의 사용자 가시 기능 + 내부 메커니즘을 카테고리별로 정리.

상태 표기:
- ✅ 자동 테스트 존재 (`tests/`)
- 🧪 자동 테스트로는 불충분 — 실제 외부 시스템 (Slack/GitHub/Anthropic API/Postgres/Redis) 으로 검증 필요
- ⚠️ 갭 — 의도되었으나 아직 검증되지 않음
- 🚫 의도적으로 범위 외 (Phase 1 의 "액션 없음" 등)

---

## 1. PR 리뷰 파이프라인 (이슈 Phase 1)

### 1.1 GitHub webhook 수신 (ingress)

| 항목 | 상태 |
|---|---|
| `pull_request.opened` / `synchronize` / `reopened` 이벤트 정규화 | ⚠️ (RawEvent 빌드 단위 테스트 부재) |
| HMAC SHA-256 서명 검증 통과 | ⚠️ |
| 잘못된 서명 → 401 반환 | ⚠️ |
| `ping` 이벤트 → ack 만, RawEvent 발행 X | ⚠️ |
| draft PR → 무시 | ⚠️ |
| `pull_request_review.submitted` 등 미지원 이벤트 → 무시 + 로그 | ⚠️ |
| 수신 후 webhook 응답 < 2초 (즉시 ack, 비동기 publish) | 🧪 |
| `response_routing.primary` 가 GitHub 채널 + repo/pr_number 보존 | ⚠️ |

### 1.2 Core 분류 (1:1 모드)

| 항목 | 상태 |
|---|---|
| `pr_*` 트리거 → `pr_review` task 발행 | ✅ `test_classifier_routes_slack_mention_to_code_analyze` 인근 |
| `manual` (CLI) 트리거 → 동일 처리 | ✅ |
| 알 수 없는 트리거 → `UnclassifiedEvent` → DLQ | ✅ `test_classifier_rejects_unknown_trigger` |
| `task_id` = `sha256(event_id + workflow)[:32]` 결정론적 | ✅ (간접 — 같은 event 반복 시 동일 task_id 가정) |

### 1.3 Agents — pr_review 워크플로우

| 항목 | 상태 |
|---|---|
| 디스패처 → 활성화 leads 결정 | ✅ `test_pipeline_clean_pr_routes_auto_merge` |
| 활성화된 lead 만 호출 (Tier 2 lead 의 조건부 활성) | ✅ |
| Specialist 활성화 시 lead 가 출력 흡수 | ✅ `test_pipeline_with_specialist_activation` |
| Specialist 와 lead 의견 불일치 → `unresolved_specialist_dissent` | ⚠️ (스키마는 있으나 시나리오 테스트 없음) |
| CTO 가 `decision/confidence/reasoning` 산출 | ✅ |
| CTO 가 *새 코드 우려를 만들지 않음* (페르소나 일 침범 X) | 🧪 (프롬프트 가드레일 — 실제 동작 검증 필요) |
| `domain_relevance` 낮은 페르소나의 영향력 자동 감소 | 🧪 |
| 페르소나 출력 JSON 파싱 실패 시 → `PersonaCallError` | ⚠️ |
| `risk_metadata` 결정론적 계산 (per-repo rules 적용) | ✅ `test_compute_risk_metadata_uses_repo_specific_paths` |
| `high_risk_paths_touched` 비어있지 않으면 escalate | 🧪 (CTO 프롬프트 룰 — 실제 LLM 검증 필요) |

### 1.4 Agents — 페르소나 출력 가드레일

| 항목 | 상태 |
|---|---|
| 보안 lead: 구체적 위협 시나리오 없으면 finding 안 만듦 | 🧪 |
| 품질 lead: 스타일 nitpick blocking 금지 | 🧪 |
| 운영 lead: "롤백 계획 필요" 보일러플레이트 금지 | 🧪 |
| 호환성 lead: 신규 추가는 breaking 아님 | 🧪 |
| 제품·UX lead: 코드만으로 판단 어려우면 self_confidence 낮춤 | 🧪 |
| 설정 분리 specialist: 진짜 상수 (HTTP 200, π 등) 에 finding 안 만듦 | 🧪 |

### 1.5 Trace store

| 항목 | 상태 |
|---|---|
| `pr_trace` DDL idempotent (`CREATE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS`) | 🧪 (실제 Postgres 필요) |
| 모든 stage 출력 JSONB 컬럼에 저장 | ⚠️ (실 write 경로 단위 테스트 부재) |
| 같은 task_id 재실행 시 `ON CONFLICT UPDATE` | 🧪 |
| `detail_markdown` 컬럼 채워짐 (Slack 워크플로우, monolithic) | ⚠️ |
| `human_decision` 은 NULL 로 시작 (별도 webhook 이 채울 자리) | 🚫 (D 항목 미구현) |

### 1.6 Egress (GitHub 코멘트)

| 항목 | 상태 |
|---|---|
| ResultEvent 받아 PR 코멘트 게시 | ⚠️ |
| `GITHUB_TOKEN` 미설정 시 skip + 경고 | ⚠️ |
| 재시도 (HTTP 4xx/5xx) | ⚠️ |
| DLQ 이동 (MAX_DELIVERIES 초과) | ⚠️ |
| **머지/거부/라벨링 안 함** (Phase 1 액션 없음 원칙) | 🚫 (의도적 — 코드에 없음) |

---

## 2. Slack 워크플로우

### 2.1 Slack ingress (Socket Mode)

| 항목 | 상태 |
|---|---|
| Socket Mode 연결 (`SLACK_APP_TOKEN`) | 🧪 |
| `app_mention` 이벤트 분류 — 키워드 매칭 (디버깅/분석/수정/픽스/이슈+등록) | ✅ `test_classify_slack_text_*` (4 테스트) |
| 키워드 매칭 → RawEvent 발행 + hourglass 반응 | ⚠️ (publish 단위 통합 테스트 부재) |
| 키워드 미매칭 → 버튼 블록 게시 | ⚠️ |
| 버튼 클릭 (`cmd_debug`/`cmd_fix`/`cmd_issue`) → RawEvent 발행 | ⚠️ |
| 버튼 메시지 자동 삭제 (interactive 처리 후) | ⚠️ |
| 스레드 컨텍스트 fetch (`conversations.replies`) | ⚠️ |
| 채널 ID → service_map 해석 (known service / fallback) | ✅ `test_build_event_normalizes_known_channel` / `_unbound_channel_falls_back` |
| `response_routing.primary.target` 에 channel_id/thread_ts/mention_ts | ✅ (위 테스트로 간접 검증) |

### 2.2 Slack egress (메시지 + 반응)

| 항목 | 상태 |
|---|---|
| `summary_markdown` 을 thread 메시지로 게시 | ✅ `test_deliver_summary_only_when_no_trace_url` |
| `trace_url` 있을 때 `📄 <url\|Full report>` 링크 추가 | ✅ `test_deliver_appends_report_url_when_present` |
| 파일 업로드 코드 경로 *완전 제거* | ✅ `test_deliver_no_file_upload_attempted` |
| hourglass → ✅/❌ 반응 스왑 | ✅ `test_deliver_summary_only_when_no_trace_url` (간접) |
| 에러 결과 (`output.error`) → ❌ 반응 | ✅ `test_deliver_error_uses_x_reaction` |
| `SLACK_BOT_TOKEN` 미설정 시 skip | ✅ `test_deliver_no_token_skips` |
| `channel_id` 누락 시 skip | ✅ `test_deliver_missing_channel_skips` |
| Slack API 에러 → 로그 + DLQ | ⚠️ |

### 2.3 Workflow: code_analyze (실구현)

| 항목 | 상태 |
|---|---|
| service_resolution 의 repos 모두 worktree 마운트 | ✅ `test_code_analyze_returns_summary_and_detail` |
| env 별 적절한 브랜치 선택 (production/staging/dev) | ✅ `test_branch_for_env` (간접) |
| Claude Agent SDK 호출 (`bypassPermissions`) | ⚠️ (mock 만; 실 호출 검증 필요) |
| `{메시지, 파일}` JSON 추출 | ✅ `test_parse_output` 등 |
| service 미매칭 채널 (e.g. general) → 에러 result | ✅ `test_code_analyze_no_service_returns_error` |
| 마운트된 worktree → context exit 시 자동 정리 | ✅ `test_mount_cleanup_runs_even_on_exception` |

### 2.4 Workflow: code_modify / linear_issue (placeholder)

| 항목 | 상태 |
|---|---|
| `🚧 구현 중` 메시지 + detail 반환 | ✅ `test_code_modify_placeholder_returns_message_and_detail` / `test_linear_issue_placeholder_returns_message_and_detail` |
| WorkflowRunner 가 placeholder 로 라우트 (LLM 호출 없음) | ✅ `test_runner_dispatches_placeholders` |

---

## 3. Workspace skill (bare repo + worktree)

| 항목 | 상태 |
|---|---|
| `AGENT_WORKSPACE_DIR` 미설정 → 즉시 RuntimeError | ✅ `test_from_env_requires_explicit_workspace_dir` |
| 명시 설정 사용 | ✅ `test_from_env_uses_explicit_value` |
| `ensure_bare_repo` idempotent | ✅ `test_mount_and_cleanup_around_real_branches` (간접) |
| `mount` (`--detach`) 같은 브랜치 동시 마운트 가능 | ✅ |
| Context exit 시 worktree 정리 | ✅ |
| Context 내 예외 발생해도 정리됨 | ✅ |
| 브랜치명에 `/` 포함 (`release/main/cbt`) → slug 변환 | ✅ `test_slug_replaces_slashes_and_spaces` |
| `GITHUB_TOKEN` 없을 때 plain HTTPS clone (gh credential helper 의존) | 🧪 (실 환경) |
| Stale worktree 자동 제거 | ⚠️ (로직은 있으나 시나리오 테스트 없음) |

---

## 4. Configuration / domain constants

### 4.1 service_map

| 항목 | 상태 |
|---|---|
| 4 services × 7 unique repos × 23 service-bound channels | ✅ `test_service_map_has_four_services` |
| `resolve_channel(known_service_channel)` → service + env + repos | ✅ `test_resolve_known_service_channel` |
| `resolve_channel(known_other_channel)` → CHANNEL_NAMES fallback | ✅ `test_resolve_known_channel_outside_service_map` |
| `resolve_channel(unknown_id)` → 원본 ID | ✅ `test_resolve_unknown_channel_falls_back_to_id` |
| `find_repo` / `review_rules_for` 동작 | ✅ |

### 4.2 Per-repo review rules

| 항목 | 상태 |
|---|---|
| 7 레포 모두 review_rules 채워짐 (또는 의도적 omit + fallback) | ✅ 7 per-repo tests |
| `if-character-chat-client` test_file_patterns omit → fallback | ✅ `test_if_character_chat_client_review_rules_falls_back_for_tests` |
| 워크플로우의 `_compute_risk_metadata` 가 repo 별 rules 사용 | ✅ `test_compute_risk_metadata_uses_repo_specific_paths` |
| 미지의 repo → 모듈 default fallback | ✅ `test_compute_risk_metadata_unknown_repo_falls_back_to_defaults` |

### 4.3 환경변수 검증

| 항목 | 상태 |
|---|---|
| `ANTHROPIC_API_KEY` 미설정 → agents 시작 시 RuntimeError | ⚠️ (Settings.from_env 단위 테스트 없음) |
| `AGENT_WORKSPACE_DIR` 동일 | ✅ |
| 도커 컴포즈에서 모든 env 가 적절히 전달되는지 | 🧪 |

---

## 5. Dashboard + 보고서 뷰어

### 5.1 Dashboard (`/`, `/api/traces`, `/api/traces/{id}`)

| 항목 | 상태 |
|---|---|
| `/` 가 index.html 반환 | ✅ `test_index_html_is_served` |
| `/api/traces` 정상 (paginated) | ✅ `test_api_traces_lists_rows` |
| `DATABASE_URL` 미설정 → 503 | ✅ `test_api_traces_503_when_no_db` |
| `/api/traces/{task_id}` — 존재 시 row 반환 | ✅ `test_api_trace_detail_returns_row` |
| 미존재 시 404 | ✅ `test_api_trace_detail_404_when_missing` |
| datetime → ISO 문자열 직렬화 | ✅ |
| 클라이언트 (브라우저) 30초 폴링 갱신 | 🧪 |

### 5.2 Report viewer (`/static/reports/{task_id}`)

| 항목 | 상태 |
|---|---|
| HTML 페이지 — 마크다운 → HTML 렌더 | ✅ `test_html_renders_markdown_to_styled_page` |
| 테이블·코드펜스·헤딩 모두 정상 렌더 | ✅ (위 테스트 + smoke) |
| Raw `.md` 라우트 | ✅ `test_raw_returns_markdown_text` |
| `.md` 라우트가 `{task_id}` greedy 매치 우회 | ✅ (위 테스트) |
| 미존재 task_id → 404 (HTML, raw 모두) | ✅ `test_404_when_task_id_unknown` |
| `detail_markdown=NULL` task → 404 | ✅ `test_404_when_detail_is_empty` |
| `DATABASE_URL` 미설정 → 503 | ✅ `test_503_when_no_db` |
| Decision 별 CSS 클래스 (auto-merge / escalate / request-changes) | ✅ `test_decision_class_applied_to_html` |
| CF Zero Trust 뒤에서 인증된 사용자만 도달 | 🧪 (인프라 — 운영 시점) |

---

## 6. A/B 테스트 (페르소나 vs 모놀리식)

| 항목 | 상태 |
|---|---|
| `PR_REVIEW_AB_MODE=false` (기본) → task 1개 | ✅ `test_classifier_ab_mode_emits_shadow_monolithic_task` |
| `PR_REVIEW_AB_MODE=true` → task 2개 (primary + shadow) | ✅ |
| Shadow task 의 `event_id` 가 primary 와 동일 (JOIN 가능) | ✅ |
| Shadow task 의 `task_id` 는 primary 와 다름 | ✅ |
| Slack 워크플로우는 ab 모드와 무관 (1:1) | ✅ `test_classifier_ab_mode_does_not_double_slack_workflows` |
| `TaskSpec.shadow=True` → publish_result 스킵 | ⚠️ (main.py 분기 — 단위 테스트 없음, 라이브 검증 필요) |
| Shadow task 도 trace 에 기록 | ⚠️ (위와 동일) |
| Monolithic 워크플로우 `MonolithicReviewOutput` 파싱 | ✅ `test_parse_output_*` (4 테스트) |
| Monolithic 도 Opus 사용 (모델 capability 변수 통제) | ✅ `MonolithicReviewRunner.__init__` 코드 검증 (단위 테스트로는 model 인자 확인 안 함) |
| 비교 SQL JOIN (event_id) | 🧪 |

---

## 7. Cross-cutting (공통 메커니즘)

### 7.1 Redis Streams

| 항목 | 상태 |
|---|---|
| Consumer group 생성 idempotent | ⚠️ (코드는 BUSYGROUP 무시 처리, 실 Redis 검증 필요) |
| `XREADGROUP` 으로 메시지 소비 | 🧪 |
| 정상 처리 시 `XACK` | 🧪 |
| 처리 실패 + `delivery >= MAX_DELIVERIES` → DLQ 이동 + ack | ⚠️ |
| Pending list (un-ack 된 메시지) 재배달 | 🧪 |
| At-least-once 보장 (재배달 시 `task_id` 기반 idempotency 가 처리) | 🧪 (idempotency 키 dedup 캐시 자체가 미구현 — `design_server.md §5` 참조) |

### 7.2 워크플로우 dispatcher

| 항목 | 상태 |
|---|---|
| `pr_review` → PrReviewRunner | ✅ |
| `pr_review_monolithic` → MonolithicReviewRunner | ✅ `test_runner_dispatches_via_workflow_runner` |
| `code_analyze` → CodeAnalyzeRunner | ✅ |
| `code_modify` / `linear_issue` → PlaceholderRunner | ✅ |
| 알 수 없는 workflow → `UnknownWorkflowError` → DLQ | ⚠️ |

### 7.3 lifecycle (start/stop)

| 항목 | 상태 |
|---|---|
| Ingress: 모든 plugin start/stop 호출 | ⚠️ |
| Slack plugin: socket connect/disconnect | 🧪 |
| TraceReader connect/close | 🧪 |
| 실패 시에도 cleanup (finally) | ⚠️ |

---

## 8. 운영 절차

| 항목 | 상태 |
|---|---|
| `docker-compose up` 으로 5 서비스 + redis + postgres 부팅 | 🧪 |
| ingress `/health` 응답 | ⚠️ (라우트는 있으나 단위 테스트 없음) |
| Postgres 가 올라온 뒤 agents/ingress 시작 (depends_on healthy) | 🧪 |
| `agent_workspace` 도커 볼륨 영구 보존 | 🧪 |
| 로그 형식: 구조화 JSON (structlog) | 🧪 (실 로그 확인) |
| ingress 에서 GitHub webhook 도달 (CF / 터널링) | 🧪 |
| Slack Socket Mode 연결 유지 + 자동 재연결 | 🧪 |

---

## 9. 명시적 제외 (Phase 1 의도)

| 항목 | 상태 |
|---|---|
| GitHub PR 자동 머지 / 라벨링 / 상태 변경 | 🚫 |
| `human_decision` 캡처 (Tier 2 D) | 🚫 (별도 작업) |
| KPI 일일 잡 (Tier 2 E) | 🚫 |
| Trace 보존 정책 (Tier 3 H) | 🚫 |
| `code_modify` / `linear_issue` 실구현 | 🚫 (placeholder 의도) |
| 비용·관측성 dashboard | 🚫 |

---

## 10. 라이브 통합 검증 시나리오 (수동, 한 번씩)

운영 진입 전 한 번씩 돌려보면 좋은 시나리오 — 모두 🧪 (자동 안 됨, 수동):

### 10.1 GitHub PR 흐름
1. 테스트 레포에 PR open → ingress webhook 수신 + 정규화 정상
2. raw_events 큐에 publish 됨 (redis-cli `XINFO STREAM`)
3. core 가 분류 → tasks 큐에 publish
4. agents 가 PR 리뷰 워크플로우 실행 → trace 기록 + results 큐 publish
5. egress 가 PR 코멘트 게시
6. 대시보드 (`/`) 에 새 trace 등장
7. `/api/traces/{task_id}` JSON 응답 정상

### 10.2 Slack 흐름
1. 테스트 채널 (`if-payment-production` 등 등록된 것) 에서 `@봇 분석` 멘션
2. ingress slack plugin 이 hourglass 반응 추가
3. raw_events → tasks → agents 가 code_analyze 실행 (worktree 마운트 → Claude Agent SDK)
4. agents 가 결과 publish
5. egress 가 hourglass → ✅ 스왑 + summary + 📄 link 메시지 게시
6. 메시지의 link 클릭 → CF Zero Trust 인증 → `/static/reports/{task_id}` 가 detail_markdown 렌더링
7. 빈 멘션 (`@봇`) 시 → 버튼 블록 게시 → 클릭 → 동일 흐름

### 10.3 A/B 모드
1. `PR_REVIEW_AB_MODE=true` 로 docker-compose 재시작
2. 테스트 PR open → primary + shadow 두 task 모두 실행
3. Slack/PR 코멘트는 *primary 만* 게시 (shadow 는 안 보임)
4. trace 에 두 행 (event_id 동일, workflow 다름)
5. 비교 SQL JOIN 실행 → 양쪽 decision/confidence 비교 가능

### 10.4 실패 시나리오
1. ingress 만 실행 (core/agents 죽임) → webhook 받고 큐에 쌓임 → core 살리면 처리됨 (큐 영속성)
2. Postgres 죽이고 PR 처리 → trace.write 실패 → ResultEvent publish *되지 않음* (현재 동작 — trace 가 fail-stop)
3. Anthropic API 5xx → workflow 실패 → DLQ 이동 (delivery 3회 후)
4. Slack 토큰 만료 → egress 가 slack API 에러 → DLQ

---

## 11. 갭 우선순위

위 ⚠️ 표시 중 *실 운영 전에* 메꾸면 좋은 것:

1. **GitHub plugin webhook 정규화 단위 테스트** — HMAC 위조·draft·ping 등 엣지 케이스 (1.1)
2. **Slack ingress 의 `_on_mention`/`_on_interactive` 단위 테스트** — 키워드 매칭은 있지만 publish 까지 가는 통합 테스트 부재 (2.1)
3. **`agents/main.py` 의 shadow 분기 단위 테스트** — 코드 경로가 라이브로만 확인됨 (6)
4. **Settings.from_env 미설정 검증** — `ANTHROPIC_API_KEY` 누락 시 RuntimeError 검증 (4.3)
5. **DLQ 이동 시나리오** — 모든 큐의 max_deliveries 초과 동작 (7.1, 1.6, 2.2)

이 5개는 코드 변경 없이 *테스트만 추가*하면 갭 메꿀 수 있음. 운영 진입 전 한두 시간 작업.
