# openclaw-poc — 멀티-에이전트 PR 리뷰 시스템 설계 (Phase 1: 섀도우 모드)

이 문서는 PR 작성/리뷰를 자동화하는 멀티-에이전트 시스템의 1차 설계를 담는다. 구현 에이전트는 이 문서만 읽고도 Phase 1 (섀도우 모드) 의 골격을 만들 수 있어야 한다.

---

## 1. 프로젝트 목표

- 코드 수정/PR 작성 에이전트와 PR 리뷰 에이전트(여러 페르소나)를 두고, 루트(CTO) 에이전트가 **자동 머지 / 변경 요청 / 사람에게 에스컬레이션** 중 하나를 선택한다.
- 핵심 가치: 단순한 LLM 코드 리뷰가 아니라 **"사람이 봐야 할 PR을 정확히 골라내는" 판단 정확도**. 비용은 제약 사항이 아니다 (토큰을 써서라도 자동화로 생산성을 올리는 것이 우선).
- 따라서 핵심 난제는 *언제 자기 판단을 믿어도 되는가* 의 보정(calibration) 정확도이며, 단순 다수결·합의 봉합이 아니라 신뢰도 보정과 위험 감지에 초점을 둔다.

---

## 2. 단계별 롤아웃

전체 시스템은 4단계로 점진 롤아웃한다. **이 문서는 Phase 1 까지를 다룬다.** Phase 2 이후는 Phase 1 의 보정 데이터가 쌓인 뒤 결정한다.

| Phase | 동작 | 목적 |
|---|---|---|
| **1. 섀도우 모드** | 모든 PR 에 멀티-페르소나 리뷰 + CTO 판단을 실행. **아무 액션도 취하지 않음**. PR 코멘트로 결과 게시 + 전체 trace 를 DB 에 로깅. | CTO 판단과 사람 결정의 일치율 측정 → 보정 데이터 확보 |
| 2. 우선순위 태깅 | CTO 판단을 PR 라벨/우선순위로 노출. 사람은 여전히 모두 리뷰하지만 "안전해 보임" 태그가 붙은 PR 부터 처리. | 페르소나 가중치/프롬프트 보정 |
| 3. 화이트리스트 자동 머지 | 보정 데이터 기반으로 *낮은 위험 영역만* 자동 머지 활성화 (문서, 테스트 추가, 포매팅, 패치 버전 의존성 업뎃 등). | 안전한 영역에서 자동화 시작 |
| 4. 확장 | Phase 3 의 사후 롤백/핫픽스율 기반으로 화이트리스트 확장. | 자동화 비율 점진 증가 |

핵심 지표 **false-confident rate** (CTO 가 "auto-merge" 라 했는데 사람이 변경 요청한 비율) 가 0 에 수렴할 때까지 Phase 3 으로 넘어가지 않는다.

---

## 3. Phase 1 — 섀도우 모드 상세

### 트리거
- GitHub webhook: PR opened / synchronize (push to PR branch) / reopened.

### 파이프라인
```
PR 이벤트
  └─> 디스패처 (어떤 페르소나를 활성화할지 결정)
        └─> 활성화된 lead·specialist 병렬 실행
              └─> specialist → 자기 lead 로 출력 전달
                    └─> lead → specialist 출력 흡수·재해석 후 CTO 로 단일 출력 전달
                          └─> CTO → 하드 룰 적용 + LLM 판단 → 3-way decision
                                └─> PR 코멘트 게시 + 전체 trace DB 로깅
```

### Phase 1 에서 *하지 않는* 것
- **머지/거부/라벨링 등 어떠한 GitHub 상태 변경 액션도 하지 않는다.** 출력은 PR 코멘트 + 로그뿐.
- 사람의 리뷰 워크플로우에 개입하지 않는다 (리뷰어 자동 지정 X, 알림 X).

---

## 4. 페르소나 아키텍처

### 4.1 Tier 구조

| Tier | 정의 | CTO 와의 관계 |
|---|---|---|
| **Tier 1 — 상시 도메인 lead** | 모든 PR 에 항상 활성화 | CTO 에 직통 |
| **Tier 2 — 조건부 도메인 lead** | 트리거 시에만 활성화 | CTO 에 직통 |
| **Tier 3 — Specialist** | lead 산하, 트리거 시에만 활성화 | 자기 lead 를 거침 (CTO 에 직접 가지 않음) |

### 4.2 페르소나 카탈로그

#### Tier 1 — 상시 lead (CTO 직통)

| 페르소나 | 도메인 | 거부권 범위 | 알려진 함정·가드레일 |
|---|---|---|---|
| **보안 lead** | 인증/인가, 입력 검증, 비밀 노출, 의존성 CVE, 로깅 PII | 보안 영역 변경에서만 blocking | 무익한 FUD 경향. *"구체적 위협 시나리오·공격 벡터를 댈 수 있을 때만 finding 을 올린다"* |
| **품질 lead** | 명백한 버그, 테스트 커버리지, 타입 안정성, 데드 코드, 에러 핸들링, 설정 분리 (specialist) | 명백한 버그 또는 새 로직에 테스트 0 인 경우만 | 끝없는 nitpick. *"blocking 으로 표시하려면 사용자 영향 또는 정확성 위반을 명시해야 한다"* |
| **운영 lead** | 릴리즈 안전성 종합 — 롤백, 배포, 피처 플래그, 모니터링/알림 | 비가역 변경, 핫패스 회귀 | specialist 활성 시 단순 패스스루 금지. 자기 도메인 시각으로 *재해석* 필요 |

#### Tier 2 — 조건부 lead (CTO 직통)

| 페르소나 | 활성화 트리거 | 도메인 |
|---|---|---|
| **호환성 lead** | `*.proto`, `openapi.yaml`/`swagger.json`, public 라우트 정의, SDK 패키지 export 변경 | API·SDK·RPC 의 breaking change 종합 |
| **제품·UX lead** | UI 컴포넌트/라우트/페이지/에러 메시지 파일 변경 | 사용자 흐름·접근성·i18n 종합 |

#### Tier 3 — Specialist (lead 경유)

##### 보안 lead 산하

| Specialist | 활성화 트리거 |
|---|---|
| AuthN/AuthZ | `auth/**`, middleware, session/token 관련 심볼 |
| 비밀·키 관리 | `.env*`, secret 패턴, KMS/Vault 클라이언트 호출 |
| 의존성·공급망 | `package-lock.json`, `poetry.lock`, `go.sum`, `requirements*.txt`, SBOM |
| 입력 검증·인젝션 | API 엔드포인트, 쿼리 빌더, shell exec, 파일 경로 처리 |
| 암호화 | `crypto/**`, hash/encrypt/sign 심볼, TLS 설정 |
| PII·데이터 노출 | 사용자 모델, 로깅·트레이싱 코드 변경 |

##### 운영 lead 산하

| Specialist | 활성화 트리거 |
|---|---|
| DB·마이그레이션 | `migrations/**`, `*.sql`, `schema.prisma`, `alembic/versions/**` |
| 성능·핫패스 | 핫패스 라벨링된 경로 (`@hotpath` 어노테이션 또는 사전 등록 디렉토리) |
| 관측성 | 로깅·메트릭·트레이싱 라이브러리 호출 변경 |
| 인프라·IaC | `*.tf`, `k8s/**`, `helm/**`, `Dockerfile`, CI 워크플로우 |
| 비동기·큐·재시도 | 큐/워커/job 디렉토리, retry/backoff 심볼 |
| 캐시·일관성 | `cache/**`, Redis/Memcached 클라이언트, 분산 락 심볼 |
| 비용 | IaC 신규 리소스, 새 외부 API 클라이언트, LLM SDK 호출 추가 |

##### 호환성 lead 산하

| Specialist | 활성화 트리거 |
|---|---|
| 외부 API | `openapi.yaml`/`swagger.json`, public 라우트 정의 |
| SDK | SDK 패키지의 `index.ts`/`__init__.py` export, 버전 매니페스트 |
| 내부 RPC·메시지 | `*.proto`, GraphQL 스키마, 이벤트 페이로드 정의 |

##### 제품·UX lead 산하

| Specialist | 활성화 트리거 |
|---|---|
| 사용자 흐름 | 라우트 정의, 페이지 컴포넌트 변경 |
| 접근성(a11y) | 인터랙티브 UI 컴포넌트, 폼·모달·키보드 네비 |
| i18n | 번역 파일, locale-aware 포매팅 코드 |

##### 품질 lead 산하

| Specialist | 활성화 트리거 |
|---|---|
| 설정 분리 | 소스 코드 파일 변경 (`*.py`, `*.ts`/`*.tsx`, `*.js`/`*.mjs`, `*.go`, `*.rs`, `*.java`/`*.kt`, `*.rb`, `*.php`, `*.cs`, `*.cpp`/`*.c`/`*.h`, `*.swift`, `*.scala` 등). 순수 문서·설정·테스트 변경만 있는 PR 은 비활성. 매직 넘버·인라인 매핑·환경별 값의 도메인 상수/env/config 모듈 분리 검사 |

### 4.3 보류된 페르소나 (다른 페르소나 항목으로 흡수)

| 후보 | 흡수 위치 | 이유 |
|---|---|---|
| 라이선스 | 보안 lead → 의존성·공급망 specialist 항목 | 트리거가 동일 (lockfile) |
| 컴플라이언스(감사 로그·규제) | 보안 lead → PII·데이터 노출 specialist 항목 | PoC 단계 빈도 낮음 |
| 문서·디스커버러빌리티 | 품질 lead 항목 | 단독 페르소나 만들 깊이 부족 |
| 아키텍처·의존성 방향 | 품질 lead 항목 | 같은 검사 패턴 (코드 꼼꼼히 읽기) |
| 데이터 라이프사이클·보존 | 보안 lead → PII specialist 확장 | GDPR 같은 규제 도입 시 분리 |

---

## 5. 라우팅 토폴로지

```
                          ┌──────────┐
                          │   CTO    │ ← 메타 판단 (auto-merge / request-changes / escalate)
                          └────▲─────┘
                               │
        ┌──────────┬───────────┼───────────┬──────────────┐
        │          │           │           │              │
   ┌────┴────┐ ┌──┴───┐ ┌─────┴────┐ ┌────┴─────┐ ┌──────┴──────┐
   │ 보안 lead│ │품질  │ │운영 lead │ │호환성 lead│ │제품·UX lead │
   └────▲────┘ │ lead │ └────▲─────┘ └────▲─────┘ └──────▲──────┘
        │      └──▲───┘      │            │              │
   ┌────┴────────┐│ ┌────────┴───┐  ┌─────┴───┐    ┌─────┴─────┐
   │ 6 specialist││ │7 specialist│  │ 3 spec  │    │  3 spec   │
   └─────────────┘│ └────────────┘  └─────────┘    └───────────┘
                  │
              ┌───┴────┐
              │ 1 spec │  (설정 분리)
              └────────┘
```

### 라우팅 규칙

| 흐름 | 규칙 |
|---|---|
| Specialist → lead | **항상.** CTO 에 직접 가는 specialist 는 없다. |
| Lead → CTO | 모든 활성화된 lead 는 CTO 직통. 단일 출력. |
| CTO 입력 크기 | 최대 5 (lead 5개 한도). PR 마다 평균 3~4. |

---

## 6. 디스패처 (Dispatcher)

PR 이벤트가 들어오면 가장 먼저 호출되는 라우터. 어떤 페르소나를 활성화할지만 결정한다 — 코드 평가는 하지 않는다.

### 6.1 구현 옵션

| 옵션 | 구성 | 장단 |
|---|---|---|
| A. 단일 LLM 디스패처 | 하드 룰을 프롬프트 안에 명시, LLM 이 적용 + 소프트 신호 판단 | 단순. LLM 이 하드 트리거를 놓칠 위험 0 이 아님 |
| B. 룰 엔진 + LLM 디스패처 | 코드로 하드 룰 적용 → LLM 은 *추가 활성화* 만 판단 | 결정론적 보장. 구현 두 단계 |

**Phase 1 권장: 옵션 A 로 시작**, 출력에 하드 룰 evidence 를 포함시켜 검증 가능하게 한다. 로깅에서 LLM 의 하드 트리거 누락이 관찰되면 옵션 B 로 분리.

### 6.2 디스패처 프롬프트

```
# 역할
당신은 PR 리뷰 시스템의 페르소나 디스패처입니다.
PR 정보를 받아, 어떤 리뷰 페르소나(lead·specialist)를 활성화할지 결정합니다.

당신은 코드를 평가하지 않습니다. 라우팅만 합니다.
도메인 깊이의 판단은 활성화될 페르소나가 수행합니다.

# 페르소나 카탈로그

## Tier 1 — 상시 lead (항상 활성화)
- 보안 lead          : 인증/인가, 입력 검증, 비밀, 의존성, PII 종합
- 품질 lead          : 명백한 버그, 테스트, 타입, 에러 핸들링
- 운영 lead          : 릴리즈 안전성 종합 (롤백·배포·모니터링)

## Tier 2 — 조건부 lead
- 호환성 lead
  하드 트리거: *.proto, openapi.yaml, swagger.json, public 라우트 정의 파일,
              SDK 패키지의 export 파일 변경
- 제품·UX lead
  하드 트리거: UI 컴포넌트 / 라우트 / 페이지 / 에러 메시지 파일 변경

## Tier 3 — Specialist (lead 산하, lead 활성 시에만 고려)

[보안 lead 산하]
- AuthN/AuthZ        : auth/**, middleware, session/token 심볼
- 비밀·키 관리        : .env*, KMS/Vault 클라이언트, 키 로테이션 코드
- 의존성·공급망      : lockfile, package manifest, SBOM
- 입력 검증·인젝션   : API 핸들러, 쿼리 빌더, shell exec, 파일 경로 처리
- 암호화             : crypto/**, hash/encrypt/sign 심볼, TLS 설정
- PII·데이터 노출    : 사용자 모델, 로깅·트레이싱 코드 변경

[품질 lead 산하]
- 설정 분리          : 소스 코드 파일 변경 (*.py, *.ts/*.tsx, *.js/*.mjs, *.go, *.rs,
                      *.java/*.kt, *.rb, *.php, *.cs, *.cpp/*.c/*.h, *.swift, *.scala 등).
                      순수 문서·설정·테스트만 변경된 PR 은 비활성

[운영 lead 산하]
- DB·마이그레이션    : migrations/**, *.sql, schema.prisma, alembic/versions/**
- 성능·핫패스        : 핫패스 라벨 디렉토리/어노테이션
- 관측성             : 로깅·메트릭·트레이싱 라이브러리 호출
- 인프라·IaC         : *.tf, k8s/**, helm/**, Dockerfile, CI 워크플로우
- 비동기·큐·재시도   : 큐/워커 디렉토리, retry/backoff 심볼
- 캐시·일관성        : cache/**, Redis/Memcached 클라이언트, 분산 락 심볼
- 비용               : IaC 신규 리소스, 새 외부 API 클라이언트, LLM SDK 호출 추가

[호환성 lead 산하]
- 외부 API           : openapi.yaml, public 라우트 정의
- SDK                : SDK 패키지 export, 버전 매니페스트
- 내부 RPC·메시지    : *.proto, GraphQL 스키마, 이벤트 페이로드 정의

[제품·UX lead 산하]
- 사용자 흐름        : 라우트 정의, 페이지 컴포넌트
- 접근성             : 인터랙티브 UI 컴포넌트, 폼·모달
- i18n               : 번역 파일, locale-aware 포매팅

# 활성화 규칙

1. Tier 1 lead 3개는 무조건 활성화한다.
2. Tier 2 lead 는 하드 트리거가 매칭되면 활성화한다.
   매칭되지 않더라도, PR 설명/제목에서 명백한 신호가 있으면 활성화 후보로 올리되,
   불확실하면 비활성화 + ambiguous_decisions 에 기록.
3. Specialist 는 해당 lead 가 활성화된 경우에만 고려한다.
   a. 하드 트리거가 매칭되면 반드시 활성화한다 (skip 불가).
   b. 하드 트리거가 매칭되지 않아도, diff 또는 PR 설명에서 그 specialist 의
      도메인 우려가 명백히 드러나면 활성화한다 (이유 명시 필수).
4. specialist 는 PR 당 최대 5개로 제한한다. 한도 초과 시:
   - hard 트리거 specialist 우선
   - soft 신호 specialist 는 신호 강도 순으로 컷
   - 컷된 specialist 는 skipped_specialists_with_reason 에 기록

# 가드레일

- 이유 없이 활성화하지 않는다. 모든 specialist 활성화는 trigger_evidence 를 가진다.
- 이유 없이 활성화 거부하지 않는다. 트리거 근접했으나 활성화 안 한 항목은
  skipped_specialists_with_reason 에 명시한다.
- PR 설명만으로 활성화 결정하지 않는다. 변경 파일/diff 에서 근거를 찾을 수
  없으면 ambiguous_decisions 로 분류.
- 자기 영역이 아닌 코드 평가를 하지 않는다 (보안 위협 분석, 성능 평가 등은
  활성화될 페르소나의 일이다).

# 입력
{
  "pr": {
    "title": "...",
    "description": "...",
    "author": "...",
    "changed_files": ["path/...", ...],
    "diff_stats": { "additions": N, "deletions": M, "files_changed": K },
    "diff": "..."   // 길이 제한 적용된 unified diff
  }
}

# 출력 (JSON)
{
  "activated_leads": [
    { "name": "보안", "tier": 1, "reason": "always-on" },
    { "name": "운영", "tier": 1, "reason": "always-on" },
    { "name": "품질", "tier": 1, "reason": "always-on" },
    { "name": "호환성", "tier": 2, "trigger_type": "hard",
      "trigger_evidence": "api/openapi.yaml 변경" }
  ],
  "activated_specialists": [
    {
      "name": "DB·마이그레이션",
      "lead": "운영",
      "trigger_type": "hard",
      "trigger_evidence": "migrations/2026_04_30_add_user_index.sql 신규",
      "reasoning": "마이그레이션 파일 패턴 매칭"
    },
    {
      "name": "비용",
      "lead": "운영",
      "trigger_type": "soft",
      "trigger_evidence": "diff 에 boto3 신규 S3 클라이언트 추가, infra/*.tf 변경",
      "reasoning": "외부 리소스/외부 API 추가가 합쳐져 비용 영향 가능성"
    }
  ],
  "skipped_specialists_with_reason": [
    {
      "name": "AuthN/AuthZ",
      "near_trigger_evidence": "PR 설명에 'login flow' 언급",
      "reason_not_activated": "변경 파일에 auth/ 경로 또는 session 심볼 변경 없음"
    }
  ],
  "ambiguous_decisions": [
    {
      "decision_point": "성능 specialist 활성화 여부",
      "what_was_unclear": "변경 함수가 핫패스인지 확인할 라벨 없음",
      "default_taken": "비활성화"
    }
  ],
  "dispatcher_confidence": 0.0
}
```

### 6.3 디스패처 출력의 학습용 필드

- `skipped_specialists_with_reason` 와 `ambiguous_decisions` 는 *학습용*. 섀도우 모드 로그에서 "활성화 안 한 specialist 가 사후에 필요했는가" (사람 리뷰어가 그 영역에서 문제를 잡았는가) 를 분석하면 트리거 룰 보정의 1차 데이터가 된다.
- `dispatcher_confidence` 가 낮으면 CTO 의 자동 머지 confidence 도 자동으로 낮춰진다 — 라우팅이 의심스러운 PR 은 판단도 의심스럽다.

---

## 7. 페르소나 출력 스키마 (공통)

모든 페르소나(lead·specialist)는 같은 출력 스키마를 사용한다 — Phase 1 의 로깅에서 페르소나별 정확도를 일관되게 측정하기 위해.

```json
{
  "persona": "보안 lead",
  "domain": "security",
  "domain_relevance": 0.0,        // 이 PR이 내 영역과 관련 있는가
  "self_confidence": 0.0,         // 나는 이 PR을 충분히 이해했는가
  "findings": [
    {
      "severity": "info | warning | blocking",
      "location": "auth/session.py:42",
      "description": "...",
      "threat_or_impact": "..."
    }
  ],
  "summary": "..."
}
```

### 핵심 필드

- **`domain_relevance`**: 백엔드 변경에 UX 페르소나가 강하게 말하면 안 됨. CTO 가 이 값을 가중치로 쓰며, 자기 영역 밖에서 떠드는 페르소나의 영향력을 자동으로 낮춘다.
- **`self_confidence`**: 페르소나 자신이 이 PR 을 충분히 이해했는가. 낮으면 CTO 는 그 의견을 약하게 반영.
- **`findings[*].severity`**:
  - `info`: 참고 사항
  - `warning`: 우려 있음, blocking 아님
  - `blocking`: 페르소나가 자기 도메인에서 거부권 행사. CTO 의 하드 룰 트리거.

---

## 8. Lead 의 책임

### 단순 패스스루 금지

Specialist 출력을 lead 가 *자기 도메인 시각으로 재해석* 해야 한다. 안 그러면 lead 가 단순 합성기/포워더가 되고 CTO 부담만 늘어난다.

- specialist findings → lead 자체 평가 텍스트로 재서술 (자기 confidence 와 결합)
- specialist 끼리 충돌하면 lead 가 도메인 우선순위로 재정렬 후 단일 의견화
- lead 가 specialist 와 *반대 결론*이 나면 그건 묵살하지 말고 출력에 명시 → CTO 에스컬레이션 신호

### Lead-Specialist 의견 불일치 처리

Lead 가 specialist 의 blocking 우려를 묵살해버리면 자동 머지에서 사고가 난다. Lead 의 출력 스키마에 추가 필드:

```json
{
  "persona": "보안 lead",
  "domain": "security",
  "domain_relevance": 0.0,
  "self_confidence": 0.0,
  "findings": [...],
  "summary": "...",
  "unresolved_specialist_dissent": [
    {
      "specialist": "AuthN/AuthZ",
      "their_finding": "...",
      "lead_reasoning_for_overruling": "..."
    }
  ]
}
```

CTO 는 `unresolved_specialist_dissent` 가 비어있지 않으면 자동 머지 후보에서 제외 → 자동 escalate. **즉 specialist 는 lead 를 거치지만, lead 가 묵살할 수는 없다 — 묵살 시도 자체가 에스컬레이션 트리거.**

---

## 9. CTO 의 책임

CTO 는 N+1 번째 리뷰어가 *아니라* 메타-판단자다. 가장 흔한 설계 실수는 CTO 에게 코드를 다시 읽혀서 자기 의견을 만들게 하는 것 — 그러면 페르소나가 놓친 걸 잡을 거란 환상에 빠지지만 실제로는 노이즈만 늘어난다.

### 9.1 CTO 책임 4단계

1. **위험 메타데이터 수집** (LLM 호출 전, 결정론적):
   - 변경 경로의 risk tag (`auth/`, `payments/`, `migrations/` 등)
   - 변경 라인 수
   - 테스트 추가 비율
   - 의존성 변경 여부
2. **하드 룰 우선 적용** (LLM 호출 전):
   - 페르소나 1개라도 자기 도메인에서 `blocking` finding → escalate 또는 request-changes
   - 어떤 lead 라도 `unresolved_specialist_dissent` 비어있지 않음 → escalate
   - high-risk 경로 포함 → 무조건 escalate
   - 100+ 줄 변경 + 테스트 0 → 최소 request-changes
3. **LLM 판단** (하드 룰 통과한 PR 에만): 페르소나 출력 + 위험 메타를 종합해 confidence 산출.
4. **3-way 결정**: confidence + 페르소나 합의도 + 위험 등급의 조합으로 결정. **Phase 1 에서는 결정만 산출, 실제 액션은 취하지 않는다.**

### 9.2 CTO 가 절대 하지 말 것

- 페르소나 의견을 단순 평균/다수결로 처리
- 자기가 새로운 코드 우려를 만들어내기 (페르소나의 일을 침범)
- 모호한 케이스를 "그래도 머지 가능"으로 봉합 — 모호한 건 정확히 escalate 의 영역

### 9.3 CTO 출력 스키마

```json
{
  "decision": "auto-merge | request-changes | escalate-to-human",
  "confidence": 0.0,
  "reasoning": "...",
  "trigger_signals": [
    "운영 페르소나 blocking (마이그레이션 비가역)",
    "변경 영역: payments/ (high-risk)",
    "페르소나 도메인 합의도 0.42 (낮음)"
  ],
  "unresolved_disagreements": [
    {
      "persona_a": "보안",
      "concern_a": "...",
      "persona_b": "품질",
      "counter_b": "..."
    }
  ],
  "risk_metadata": {
    "high_risk_paths_touched": [...],
    "lines_changed": N,
    "test_ratio": 0.0,
    "dependency_changes": false
  }
}
```

`unresolved_disagreements` 를 *봉합하지 않고 명시*하는 게 중요하다. CTO 가 봉합하려 들면 자동 머지 모드에서 사고가 난다.

---

## 10. 측정 지표 (섀도우 모드 KPI)

Phase 1 이 의미 있으려면 시작부터 다음 지표들을 로깅해야 한다.

| 지표 | 정의 | 임계 |
|---|---|---|
| **CTO–사람 일치율** | CTO 결정 vs 사람의 실제 결정의 일치율. 전체 / 결정 종류별 / risk tier 별 | 추세만 모니터, 절대값 임계 X |
| **False-confident rate** | CTO 가 "auto-merge" 라 했는데 사람이 변경 요청한 비율 | **가장 위험. Phase 3 이행 조건은 이 지표가 0 에 수렴** |
| **False-escalate rate** | CTO 가 escalate 했는데 사람이 그냥 통과시킨 비율 | 생산성 손실 지표. 추세만 모니터 |
| **페르소나 도메인 정확도** | 각 페르소나 finding 중 사람 리뷰어가 동의한 비율 | 페르소나별 가중치/프롬프트 보정 |
| **Domain relevance 자체 정확도** | 페르소나가 "관련 있다"라고 판단한 PR 이 실제로 그 영역인가 | 페르소나 프롬프트 보정 |
| **디스패처 누락률** | `skipped_specialists_with_reason` 중 사후에 필요했던 specialist 비율 | 디스패처 트리거 룰 보정 |

---

## 11. 데이터 모델 (로깅)

PR 한 건당 다음 trace 가 저장된다. 후속 분석 (페르소나별 정확도, 디스패처 누락률 등) 의 1차 자료.

```
pr_trace {
  pr_id, repo, pr_number, sha,
  timestamp,
  pr_metadata: { title, description, author, changed_files, diff_stats },
  dispatcher_output: { /* §6.2 출력 */ },
  persona_outputs: [
    { persona, role: "lead|specialist", parent_lead, output: { /* §7 스키마 */ } },
    ...
  ],
  cto_output: { /* §9.3 스키마 */ },
  human_decision: {  // 사람이 실제로 한 결정 (이후 webhook 으로 채워짐)
    final_state: "merged | closed | changes_requested",
    review_comments: [...],
    blocking_review_count: N,
    timestamp
  }
}
```

`human_decision` 은 PR 닫힘 시점에 채워지며, 이걸로 §10 의 모든 지표가 계산된다.

---

## 12. 미정 결정점 (Open Decisions)

Phase 1 구현 시작 전 / 구현 중에 정해야 할 것들. 이 문서에서는 *질문* 으로만 남긴다.

1. **페르소나의 LLM 모델 선택**: lead/specialist 모두 동일 모델인가, 페르소나별로 다른가? (예: 보안만 더 강한 모델)
2. **활성화 트리거 패턴의 코드베이스별 정밀화**: §4.2 의 트리거 패턴은 일반적 예시. 대상 레포 (예: `openclaw-src`, `hokki-client`, `vivy`) 에 맞게 구체화 필요.
3. **핫패스 라벨링 방법**: §4.2 의 성능 specialist 트리거는 라벨/어노테이션 의존. PoC 단계에서 어떻게 라벨링할지 — 사전 등록된 디렉토리 리스트 / 어노테이션 문법 / 보류.
4. **`high-risk_paths` 정의**: §9.1 의 하드 룰에 쓰임. 코드베이스별로 누가 정의하는가.
5. **`unresolved_specialist_dissent` 의 lead 측 판단 방식**: lead 가 묵살할 권한은 있되 묵살 시 자동 escalate 된다. 그렇다면 lead 가 묵살을 *시도*하는 것 자체를 막아야 하나? (현재 설계: 시도 가능, 결과는 escalate)
6. **PR 코멘트 게시 형식**: 사람이 읽기 쉬운 요약 + 전체 trace 링크 / JSON dump / 단순 라벨링. UX 결정.
7. **재실행 정책**: PR 에 새 커밋이 푸시되면 처음부터 다시 돌리는가, 변경분만 다시 도는가.
8. **레이스 컨디션**: 사람이 빠르게 머지해버린 PR 에 대해서는 trace 만 남기고 측정에서 제외할 것인가.

---

## 13. 우선 순위 정렬된 구현 작업 (제안)

이 순서로 구현하면 가장 빨리 *동작하는* 섀도우 모드 PoC 가 나온다.

1. **GitHub webhook 수신 + PR 메타 추출** — diff/파일 목록을 표준 입력 포맷으로 정규화.
2. **데이터 모델 + 로깅 스토어** — §11 의 `pr_trace` 를 저장할 DB. SQLite 도 충분.
3. **디스패처 구현** — §6.2 프롬프트로 1회 LLM 호출. 출력 검증.
4. **페르소나 한 명 (예: 품질 lead) 의 단독 동작 검증** — specialist 없이 가장 단순한 페르소나로 출력 스키마 정합성 확인.
5. **나머지 lead 3명 (보안·운영, 그리고 Tier 2 lead 필요 시) 추가** — 모두 specialist 없이 단독 동작.
6. **specialist 추가 + lead 의 합성 로직** — `unresolved_specialist_dissent` 포함 검증.
7. **CTO 구현** — 하드 룰 + LLM 판단 + 3-way 출력.
8. **PR 코멘트 게시 + `human_decision` 채우는 webhook** — 측정의 양 끝.
9. **지표 계산 잡** — §10 의 KPI 를 daily 로 산출.

각 단계에서 *액션 없음* 원칙은 변하지 않는다. Phase 1 의 산출물은 trace + 코멘트뿐.
