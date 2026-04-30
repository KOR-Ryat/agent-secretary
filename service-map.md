# 서비스-채널-레포 매핑

## if (이프 / project-201)

| 채널 | 환경 |
|------|------|
| if-dm-production | production |
| if-payment-production | production |
| if-sns-production | production |
| if-taskfail-production | production |
| if-taskfail-staging | staging |
| if-training-production | production |
| if-training-staging | staging |
| if-worldchat-production | production |

| 레포 | production 브랜치 | staging 브랜치 |
|------|------------------|---------------|
| mesher-labs/project-201-server | `main` | `stage` |
| mesher-labs/project-201-flutter | `main` | `stage` |

---

## ifcc (이프 캐릭터챗)

| 채널 | 환경 |
|------|------|
| ifcc-admin-production | production |
| ifcc-error-production | production |
| ifcc-error-stage | stage |
| ifcc-payment-production | production |
| ifcc-world-production | production |
| ifcc-world-stage | stage |
| ifcc-worldchat-production | production |
| ifcc-worldchat-stage | stage |

| 레포 | production 브랜치 | staging 브랜치 |
|------|------------------|---------------|
| mesher-labs/if-character-chat-server | `release/main/cbt` | `release/stage/cbt` |
| mesher-labs/if-character-chat-client | `main` | `stage` |

> if-character-chat-backoffice: 빈 레포, 제외

---

## viv (빕)

| 채널 | 환경 |
|------|------|
| viv-app-production | production |
| viv-chat-production | production |
| viv-error-production | production |
| viv-feed-production | production |
| viv-payment-production | production |

| 레포 | production 브랜치 | staging 브랜치 |
|------|------------------|---------------|
| mesher-labs/viv-monorepo | `main` | `stage` |

---

## zendi

| 채널 | 환경 |
|------|------|
| zendi-alarm-production | production |
| zendi-alarm-stage | stage |

| 레포 | production 브랜치 | staging 브랜치 |
|------|------------------|---------------|
| mesher-labs/hokki-server | `master` | `stage` |
| mesher-labs/hokki_flutter_app | `main` | `develop` ⚠️ 추정, 확인 권장 |
