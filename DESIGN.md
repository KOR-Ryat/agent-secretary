# Agent Ingress Design

## 1. 트리거 구조

### 빈 멘션
- 커맨드 버튼 블록 3개 반환
  - 🔍 버그 분석
  - 🔧 버그 수정
  - 📋 이슈 등록

### 키워드 멘션
| 키워드 | 커맨드 |
|--------|--------|
| '디버깅' or '분석' | 버그 분석 |
| '수정' or '픽스' | 버그 수정 |
| '이슈' and '등록' | 이슈 등록 |

- 프롬프트는 분기 판단용으로만 사용
- 실제 에이전트 컨텍스트는 스레드 메시지에서 읽어서 전달

---

## 2. 아웃풋 구조

모든 커맨드 공통 포맷:

```json
{
  "메시지": "<사용자에게 보여줄 간결한 결과 요약>",
  "파일": "<전체 상세 내역 마크다운>"
}
```

- `메시지` → Slack 스레드 메시지로 전송
- `파일` → `result.md` 마크다운 파일로 첨부

---

## 3. 에이전트 워킹 디렉토리 & 워킹트리 전략

```
viv-monorepo/agent-workspace/
├── repos/          ← bare repos (git 객체 원본)
│   ├── viv-monorepo.git/
│   ├── project-201-server.git/
│   └── ...
└── worktrees/      ← 세션별 마운트 (분석 후 삭제)
    └── <레포>-<브랜치>-<세션ID>/
```

### bare repo 선택 이유

- `git checkout`은 동시 세션 간 브랜치 충돌 발생
- `git worktree`는 세션마다 독립 디렉토리로 마운트 → 충돌 없음
- bare repo는 git 객체만 보관하고 실제 파일은 worktree에만 존재

### 세션 격리 메커니즘

```bash
# 마운트 (세션ID suffix로 동일 브랜치 동시 접근 허용)
git -C repos/<레포>.git fetch --all --prune
git -C repos/<레포>.git worktree add \
  "$(pwd)/worktrees/<레포>-<브랜치>-<세션ID>" <브랜치>

# 정리
git -C repos/<레포>.git worktree remove \
  "$(pwd)/worktrees/<레포>-<브랜치>-<세션ID>"
```

- 세션ID는 `commands.mjs`에서 생성해 프롬프트에 주입
- 상세 명령 및 멀티 레포 예시: `agent-workspace/REPOS.md`

---

## 4. 커맨드 정의

### 버그 분석
- 채널명에서 서비스명 + 환경 추출
- 해당 서비스 레포의 환경 브랜치 기준으로 코드 분석
- 스레드 컨텍스트(에러 로그 등)를 바탕으로 버그 원인 분석
- 시스템 프롬프트: TBD

### 버그 수정
- 버그 분석과 동일한 컨텍스트
- 원인 파악 후 코드 수정안 제시
- 시스템 프롬프트: TBD

### 이슈 등록
- 스레드 컨텍스트 기반으로 Linear 이슈 생성
- 시스템 프롬프트: TBD

---

## 5. 서비스-레포 매핑 및 브랜치 전략

상세 채널 매핑: `service-map.mjs` / `service-map.md` 참조

| 레포 | production | staging | 신뢰도 | 근거 |
|------|-----------|---------|--------|------|
| project-201-server | `main` | `stage` | ★★★ | `.github/workflows/deploy-prod.yml` L4-5 `on.push.branches: [main]`, `deploy-staging.yml` L4-5 `on.push.branches: [stage]` |
| project-201-flutter | `main` | `stage` | ★★ | CI 없음. 머지 체인으로 추론 — PR #261 `stage→main`, PR #260 `dev→stage`. README/CLAUDE.md Flutter 플레이버 production/stage 명시 |
| if-character-chat-server | `release/main/cbt` | `release/stage/cbt` | ★★★ | `deploy-main.yml` L4-5 `on.push.branches: [release/main/cbt]`, `deploy-stage.yml` L4-5 `on.push.branches: [release/stage/cbt]` |
| if-character-chat-client | `main` | `stage` | ★★ | CI 없음. 머지 체인으로 추론 — PR #226 `stage→main`, PR #225 `dev→stage` |
| if-character-chat-backoffice | — | — | — | 빈 레포 (size: 0, 단 한 번도 push 없음) |
| viv-monorepo | `main` | `stage` | ★★★ | `prod-server-deploy.yml` `on.push.branches: [main]`, `stage-server-deploy.yml` `on.push.branches: [stage]` |
| hokki-server | `master` | `stage` | ★★★ | `deploy_production.yaml` `on.push.branches: - master`, `deploy_stage.yaml` `on.push.branches: - stage`. README/CLAUDE.md에도 명시 |
| hokki_flutter_app | `main` | `develop` | ★ | CI 없음. git-flow 추정 — release/0.0.1 머지 메시지에서 `develop→release` 흐름 확인. ⚠️ hokki-server(master/stage)와 컨벤션 불일치, 모바일 담당자 확인 권장 |
