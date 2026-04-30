# Agent Workspace 셋업

코드를 직접 읽거나 수정하는 워크플로우 (`code_analyze`, `code_modify` 등) 는 *bare repo + git worktree* 패턴으로 세션 격리를 한다. 이 문서는 그 디스크 레이아웃과 셋업 절차를 정리한다.

> 구버전 `WORKSPACE.md` / `workspace/REPOS.md` 의 후속. 신규 아키텍처에서는 환경변수와 도커 볼륨으로 일관화됨.

---

## 1. 디렉토리 레이아웃

```
$AGENT_WORKSPACE_DIR/
├── repos/                        ← bare repos (git 객체만 보관)
│   ├── viv-monorepo.git/
│   ├── project-201-server.git/
│   └── ...
└── worktrees/                    ← 세션별 worktree (분석 후 자동 삭제)
    └── <repo>--<branch_slug>--<sessionID>/
```

- `repos/*.git` 은 직접 작업하지 않는다 (`HEAD` 가 없는 bare repo).
- 코드를 읽으려면 워크플로우가 `WorkspaceManager.mount()` 를 호출해 `worktrees/` 아래에 마운트한다 (자동 정리).
- 같은 브랜치에 여러 세션이 동시에 마운트해도 안전 — `--detach` 옵션으로 브랜치 ref 를 점유하지 않음.

## 2. 환경변수

| 변수 | 의미 | 기본값 |
|---|---|---|
| `AGENT_WORKSPACE_DIR` | 워크스페이스 루트 | `~/agent-workspace` (로컬), `/var/agent-workspace` (docker) |
| `GITHUB_TOKEN` | bare clone 시 URL 에 주입되는 토큰 | (없음 — public repo 만 가능) |

도커 환경에서는 `infra/docker-compose.yml` 의 `agents` 서비스에 `agent_workspace` 볼륨이 마운트되며, 동일 경로가 `AGENT_WORKSPACE_DIR` 로 노출된다.

## 3. 초기 셋업

### 3-1. 로컬 dev (bare 직접 clone)

토큰 인증 방법 두 가지:

**옵션 A — `gh` CLI (권장 for 로컬 dev)**

`gh` 가 git credential helper 로 동작 → 토큰을 URL 에 박지 않아도 됨. App 이 아직 모든 레포에 설치되지 않은 단계에서 *자기 GitHub 계정 권한*으로 clone 가능:

```bash
gh auth login                                  # 한 번만
gh auth setup-git                              # git 이 gh 자격증명 사용
export AGENT_WORKSPACE_DIR=~/agent-workspace
mkdir -p "$AGENT_WORKSPACE_DIR/repos"

repos=(viv-monorepo project-201-server project-201-flutter
       if-character-chat-server if-character-chat-client
       hokki-server hokki_flutter_app)
ORG=mesher-labs

for repo in "${repos[@]}"; do
  git clone --bare \
    "https://github.com/${ORG}/${repo}.git" \
    "$AGENT_WORKSPACE_DIR/repos/${repo}.git"
done
```

**옵션 B — 토큰 URL (CI / 헤드리스 환경)**

```bash
export GITHUB_TOKEN=<token>   # PAT 또는 GitHub App installation token
export AGENT_WORKSPACE_DIR=~/agent-workspace
mkdir -p "$AGENT_WORKSPACE_DIR/repos"

# repos / ORG 변수는 옵션 A 와 동일
for repo in "${repos[@]}"; do
  git clone --bare \
    "https://${GITHUB_TOKEN}@github.com/${ORG}/${repo}.git" \
    "$AGENT_WORKSPACE_DIR/repos/${repo}.git"
done
```

> 단일 진실 원천: 어떤 레포가 어떤 서비스에 속하고 어떤 브랜치 전략을 갖는지는 [`packages/config/agent_secretary_config/service_map.py`](../packages/config/agent_secretary_config/service_map.py) 의 `SERVICE_MAP` 참조. `all_repos()` 로 자동 생성도 가능 (구현 시 utility 작성).
>
> 보안 비교: 옵션 A 는 토큰이 git config 에 저장 안 됨 (gh 가 매번 helper 로 주입). 옵션 B 는 bare repo 의 `config` 에 평문 박힘 — 디스크 권한 600 권장.

### 3-2. 도커 (런타임 자동 clone)

`agents` 컨테이너가 처음 워크플로우를 실행할 때 `WorkspaceManager.ensure_bare_repo()` 가 누락된 bare repo 를 자동으로 clone 한다. 별도 사전 셋업 불필요. 단, `GITHUB_TOKEN` 이 환경에 들어있어야 private repo 접근 가능.

## 4. 주기적 동기화

워크플로우 실행 시 자동으로 `git fetch --all --prune` 이 실행된다 (`WorkspaceManager.mount(..., fetch_first=True)` 기본값). 별도 cron 불필요.

수동 동기화가 필요하면:

```bash
for r in "$AGENT_WORKSPACE_DIR"/repos/*.git; do
  git -C "$r" fetch --all --prune
done
```

## 5. 워크트리 잔여물 정리

비정상 종료 시 worktrees 가 남을 수 있다. 디버깅용:

```bash
for r in "$AGENT_WORKSPACE_DIR"/repos/*.git; do
  git -C "$r" worktree list
done

# 수동 정리
git -C "$AGENT_WORKSPACE_DIR/repos/<repo>.git" worktree remove --force "$AGENT_WORKSPACE_DIR/worktrees/<dir>"
```

`WorkspaceManager.mount()` 는 진입 시 같은 경로의 stale worktree 를 자동으로 제거하므로, 일반적인 운영에서는 수동 정리 불필요.

## 6. 보안 고려

- `GITHUB_TOKEN` 이 bare repo 의 `config` 에 평문으로 박힘 (clone URL 의 일부). 워크스페이스 디스크가 침해되면 토큰 노출. 권장: 단일-목적의 GitHub App 토큰을 사용하고, 디스크는 권한 600 으로 격리.
- 도커 볼륨 (`agent_workspace`) 은 호스트 권한에 종속. 운영 환경에서는 컨테이너 외부에서 접근 차단 권장.
