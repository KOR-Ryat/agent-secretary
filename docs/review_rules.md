# Review heuristic tuning per codebase

PR 리뷰 워크플로우의 *위험 메타데이터* (high-risk paths, test ratio, dependency changes) 는 두 층으로 결정된다:

1. **모듈 기본값** ([`packages/config/.../review_rules.py`](../packages/config/agent_secretary_config/review_rules.py)) — 어떤 코드베이스에도 보편적으로 적용되는 보수적 패턴.
2. **레포별 overrides** — `service_map` 의 각 `Repo` 에 `review_rules: ReviewRules(...)` 를 부착해 특정 레포의 관용을 명시.

이 문서는 **2층**을 채워가는 절차를 정리한다.

---

## 1. 왜 채워야 하나

`design.md §10` 의 *false-confident rate* 와 *false-escalate rate* 가 Phase 1 의 핵심 KPI 다. 일반 패턴만 적용하면:

- viv-monorepo 에서 `server/src/modules/auth/...` 가 변경되어도 high-risk 로 표시 안 됨 → CTO 가 자동 머지 후보로 잘못 분류 (false-confident).
- 모든 `*test*` 가 들어간 파일을 테스트로 인식 → 비-테스트 파일이 우연히 매칭되어 test_ratio 가 부풀려짐 → 코드 변경에 테스트 없는데도 머지 가능 신호.

레포별 정확한 패턴이 들어가야 신뢰할 수 있는 보정 데이터가 쌓임.

---

## 2. ReviewRules 필드

```python
class ReviewRules(BaseModel, frozen=True):
    high_risk_paths: tuple[str, ...] = ()        # auth/payments/migrations 등
    test_file_patterns: tuple[str, ...] = ()     # 테스트 파일 식별 substring
    dependency_file_patterns: tuple[str, ...] = ()  # lockfile / manifest 식별 substring
```

각 필드는 **비어 있으면 모듈 기본값으로 fallback**, 비어 있지 않으면 *해당 필드만* 레포 값으로 대체.

예: `high_risk_paths=("server/src/modules/auth/",)` → 그 레포에서는 `auth/` (default) 가 적용 안 되고 `server/src/modules/auth/` 만 적용. test/dependency 는 default 그대로.

---

## 3. 채우는 방법

[`packages/config/.../service_map.py`](../packages/config/agent_secretary_config/service_map.py) 의 `Repo` 객체에 `review_rules` 를 추가.

```python
Repo(
    name="mesher-labs/viv-monorepo",
    production="main",
    staging="stage",
    dev="dev",
    review_rules=ReviewRules(
        high_risk_paths=(
            "server/src/modules/auth/",
            "server/src/modules/payment/",
            "server/migrations/",
        ),
        test_file_patterns=(".test.ts", ".spec.ts"),
        # dependency_file_patterns 미지정 → default 사용
    ),
),
```

코드 변경 후 `uv run pytest tests/test_review_rules.py` 로 회귀 확인.

---

## 4. 패턴 작성 팁

### high_risk_paths

- **경로 prefix** 로 적되 슬래시까지 포함 — `auth/` 는 `auth/session.py` 에 매칭, `auth_helpers.py` 에는 X.
- 너무 짧게 잡지 말 것 — `payment` 는 `payments/`, `payment_helper.py`, `repayment.py` 에 모두 매칭됨. 의도하지 않은 매칭 주의.
- 레포의 *실제* 디렉토리 구조를 반드시 확인 — `server/src/modules/auth/` 인지 `src/auth/` 인지.

### test_file_patterns

- 언어/프레임워크별로 다름:
  - TS/JS (Jest/Vitest): `.test.ts`, `.spec.ts`, `__tests__/`
  - Python (pytest): `test_`, `_test.py`, `tests/`
  - Go: `_test.go`
  - Rust: `tests/`, `_test.rs`
  - Flutter/Dart: `_test.dart`, `test/`
- 모노레포는 여러 패턴 동시 등재.

### dependency_file_patterns

- lockfile + manifest 모두 포함 권장 — `package.json` 만 보면 lockfile 만 변경된 PR 을 놓침.
- 일반적: `package.json`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `requirements.txt`, `requirements-*.txt`, `poetry.lock`, `pyproject.toml` (deps section), `go.mod`, `go.sum`, `Cargo.toml`, `Cargo.lock`.

---

## 5. 검증 방법

레포별 룰을 채운 뒤:

1. **단위 테스트**: 위 `test_review_rules.py` 에 새 케이스 추가 — 해당 레포의 대표 변경 파일 리스트로 risk_metadata 가 기대대로 계산되는지.
2. **트레이스 분석**: 운영 시작 후 며칠치 trace 를 보고
   - high-risk 가 *과도하게* 빈번한 PR 에서 매칭 → 패턴이 너무 광범위
   - 명백히 위험한 PR이 high-risk 미표시 → 패턴이 너무 좁음
3. **사람 결정과의 일치율**: human_decision capture (Tier 2 D 항목) 가 가능해진 후엔 KPI 잡으로 자동 측정.

---

## 6. 현재 상태 (2026-04-30 기준)

7개 레포 모두 `review_rules` 미지정 — 모듈 기본값만 적용 중. 다음 작업 후보:

- viv-monorepo
- project-201-server / project-201-flutter
- if-character-chat-server / -client
- hokki-server / hokki_flutter_app

각 레포에 접근해 디렉토리 구조 + 테스트 컨벤션 + 의존성 매니저를 확인한 뒤 위 §3 양식대로 채울 것.
