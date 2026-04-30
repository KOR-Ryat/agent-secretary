# 서비스-레포-브랜치 매핑

## 디렉토리 구조

```
agent-workspace/
├── REPOS.md                  ← 이 파일
├── repos/                    ← bare repos (git 객체 원본, 작업 X)
│   ├── viv-monorepo.git/
│   ├── project-201-server.git/
│   ├── project-201-flutter.git/
│   ├── if-character-chat-server.git/
│   ├── if-character-chat-client.git/
│   ├── hokki-server.git/
│   └── hokki_flutter_app.git/
└── worktrees/                ← 세션별 마운트 (분석 후 삭제)
    └── <레포>-<브랜치>-<세션ID>/
```

`repos/*.git`은 bare repo로 직접 작업하지 않는다. 코드를 읽으려면 반드시 아래 워킹트리 전략을 따른다.

---

## 레포별 브랜치 전략

| 레포 | bare repo 경로 | dev | staging | production |
|---|---|---|---|---|
| viv-monorepo | `repos/viv-monorepo.git` | `dev` | `stage` | `main` |
| project-201-server | `repos/project-201-server.git` | `dev` | `stage` | `main` |
| project-201-flutter | `repos/project-201-flutter.git` | `dev` | `stage` | `main` |
| if-character-chat-server | `repos/if-character-chat-server.git` | `dev` | `release/stage/cbt` | `release/main/cbt` |
| if-character-chat-client | `repos/if-character-chat-client.git` | `dev` | `stage` | `main` |
| hokki-server | `repos/hokki-server.git` | `dev` | `stage` | `master` |
| hokki_flutter_app | `repos/hokki_flutter_app.git` | `develop` | `develop` (겸직) | `main` |

> **hokki-server**: production 브랜치가 `master`.
> **hokki_flutter_app**: staging 전용 브랜치 없음, `develop`이 겸임.

---

## 서비스별 채널-환경 매핑

### if (이프 / project-201)
레포: `project-201-server`, `project-201-flutter`

| Slack 채널 | 환경 |
|---|---|
| if-dm-production | production |
| if-payment-production | production |
| if-sns-production | production |
| if-taskfail-production | production |
| if-taskfail-staging | staging |
| if-training-production | production |
| if-training-staging | staging |
| if-worldchat-production | production |

### ifcc (이프 캐릭터챗)
레포: `if-character-chat-server`, `if-character-chat-client`

| Slack 채널 | 환경 |
|---|---|
| ifcc-admin-production | production |
| ifcc-error-production | production |
| ifcc-error-stage | stage |
| ifcc-payment-production | production |
| ifcc-world-production | production |
| ifcc-world-stage | stage |
| ifcc-worldchat-production | production |
| ifcc-worldchat-stage | stage |

### viv (빕)
레포: `viv-monorepo`

| Slack 채널 | 환경 |
|---|---|
| viv-app-production | production |
| viv-chat-production | production |
| viv-error-production | production |
| viv-feed-production | production |
| viv-payment-production | production |

### zendi
레포: `hokki-server`, `hokki_flutter_app`

| Slack 채널 | 환경 |
|---|---|
| zendi-alarm-production | production |
| zendi-alarm-stage | stage |

---

## 워킹트리 전략

### 왜 워킹트리인가

- bare repo는 git 객체만 갖고 있어 직접 파일을 읽을 수 없음
- `git checkout`으로 bare repo 내 브랜치를 전환하면 동시 세션 간 충돌 발생
- `git worktree`를 쓰면 각 세션이 독립된 디렉토리에서 특정 브랜치를 마운트하므로 충돌 없음
- 세션ID suffix로 동일 브랜치에 대한 동시 세션도 격리됨

### 마운트 (분석 시작)

```bash
# 1. 최신 코드 fetch
git -C repos/<레포>.git fetch --all --prune

# 2. worktrees/ 디렉토리에 마운트
git -C repos/<레포>.git worktree add \
  "$(pwd)/worktrees/<레포>-<브랜치>-<세션ID>" \
  <브랜치>
```

예시 (세션ID: a1b2c3d4, viv production 분석):
```bash
git -C repos/viv-monorepo.git fetch --all --prune
git -C repos/viv-monorepo.git worktree add \
  "$(pwd)/worktrees/viv-monorepo-main-a1b2c3d4" \
  main
```

### 분석

`worktrees/viv-monorepo-main-a1b2c3d4/` 디렉토리에서 코드를 읽는다.

### 정리 (분석 완료 후 반드시)

```bash
git -C repos/<레포>.git worktree remove \
  "$(pwd)/worktrees/<레포>-<브랜치>-<세션ID>"
```

### 여러 레포가 필요한 경우

서비스가 서버+클라이언트 등 여러 레포를 갖는 경우 각각 마운트한다.
같은 세션ID를 쓰면 세션 단위로 일괄 정리하기 쉽다:

```bash
# if 서비스 staging 분석 — 서버 + 플러터 동시 마운트
git -C repos/project-201-server.git fetch --all --prune
git -C repos/project-201-server.git worktree add \
  "$(pwd)/worktrees/project-201-server-stage-a1b2c3d4" stage

git -C repos/project-201-flutter.git fetch --all --prune
git -C repos/project-201-flutter.git worktree add \
  "$(pwd)/worktrees/project-201-flutter-stage-a1b2c3d4" stage

# 정리
git -C repos/project-201-server.git worktree remove \
  "$(pwd)/worktrees/project-201-server-stage-a1b2c3d4"
git -C repos/project-201-flutter.git worktree remove \
  "$(pwd)/worktrees/project-201-flutter-stage-a1b2c3d4"
```

---

## 코드 분석 체크리스트

1. Slack 채널명에서 서비스와 환경을 확인한다.
2. 위 표에서 해당 레포와 브랜치를 확인한다.
3. fetch + worktree 마운트 (세션ID는 프롬프트에 주입된 값 사용).
4. `worktrees/` 아래 마운트된 디렉토리에서 코드를 읽고 분석한다.
5. 분석 완료 후 worktree를 제거한다.
