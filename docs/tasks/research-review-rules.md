# Task: populate per-repo review rules

> **For another agent.** This brief is self-contained — read top to bottom and you should be able to complete the task without follow-up questions.

## 1. Goal

For each of the 7 repos registered in [`packages/config/agent_secretary_config/service_map.py`](../../packages/config/agent_secretary_config/service_map.py), determine the correct values for the three `ReviewRules` fields and add them to the existing `Repo(...)` constructors. Then add per-repo test cases verifying behavior.

## 2. Why this matters

The PR review pipeline computes `risk_metadata` (high-risk paths touched, test ratio, dependency changes) using these rules. Without per-repo overrides, the pipeline applies *generic* defaults to every codebase — `auth/`, `payments/`, `migrations/`, etc. — which usually don't match the actual directory layout (e.g., viv-monorepo's auth lives at `server/src/modules/auth/`).

Generic defaults cause two failure modes:
- **false-confident**: a high-risk PR isn't flagged because the path didn't match → CTO auto-merges it.
- **false-escalate**: a benign PR matches a generic pattern by coincidence → unnecessary human review.

Per-repo tuning is the prerequisite for the Phase 1 calibration KPIs (`design.md §10`) to be meaningful.

## 3. Prerequisites

You need:

1. **agent-secretary repo cloned** with `uv sync --all-packages` already run.
2. **Bare clones of all 7 target repos** at `$AGENT_WORKSPACE_DIR/repos/`. If they aren't there yet, run [`docs/workspace.md §3-1`](../workspace.md) first — requires `GITHUB_TOKEN` with read access to `mesher-labs/*`.
3. **A research worktree per repo** mounted on the production branch (read-only inspection):

```bash
export AGENT_WORKSPACE_DIR=${AGENT_WORKSPACE_DIR:-~/agent-workspace}

# Production branch per repo (from service_map.py SERVICE_MAP):
declare -A REPO_PROD=(
  [viv-monorepo]=main
  [project-201-server]=main
  [project-201-flutter]=main
  [if-character-chat-server]=release/main/cbt
  [if-character-chat-client]=main
  [hokki-server]=master
  [hokki_flutter_app]=main
)

for repo in "${!REPO_PROD[@]}"; do
  bare="$AGENT_WORKSPACE_DIR/repos/${repo}.git"
  branch="${REPO_PROD[$repo]}"
  wt="$AGENT_WORKSPACE_DIR/worktrees/research--${repo}"
  [ -d "$wt" ] && continue
  git -C "$bare" fetch --all --prune
  git -C "$bare" worktree add --detach "$wt" "$branch"
  echo "mounted $repo @ $branch -> $wt"
done
```

After this you can `cd` into each `worktrees/research--<repo>/` and inspect normally.

When you're done, clean up:

```bash
for repo in "${!REPO_PROD[@]}"; do
  bare="$AGENT_WORKSPACE_DIR/repos/${repo}.git"
  wt="$AGENT_WORKSPACE_DIR/worktrees/research--${repo}"
  git -C "$bare" worktree remove --force "$wt" 2>/dev/null || true
done
```

## 4. The three fields you fill

[`packages/config/agent_secretary_config/review_rules.py`](../../packages/config/agent_secretary_config/review_rules.py) defines:

```python
class ReviewRules(BaseModel, frozen=True):
    high_risk_paths: tuple[str, ...] = ()
    test_file_patterns: tuple[str, ...] = ()
    dependency_file_patterns: tuple[str, ...] = ()
```

Each field, when *non-empty*, **replaces** the corresponding module default for that repo. Empty fields fall back to defaults — see `resolve_rules()`.

### `high_risk_paths`

Path *substrings* (typically directory prefixes ending in `/`) that mark "this PR touches code where wrong auto-merges are expensive". Categories to look for in each repo:

| Category | Hints to grep for |
|---|---|
| Auth / session | `auth`, `login`, `session`, `oauth`, `jwt`, `token` |
| Payment / billing | `payment`, `billing`, `invoice`, `subscription`, `purchase` |
| DB migrations | `migrations`, `migrate`, `alembic`, `prisma/migrations`, `flyway` |
| Secrets handling | `secrets`, `credentials`, `keys`, `vault` |
| Native build / signing (mobile) | `android/app/build.gradle`, `android/keystore`, `ios/Runner.xcodeproj`, `Podfile.lock` |
| Webhooks / payment gateway adapters | grep for `webhook`, `stripe`, `toss`, `port-one`, etc. |

**Discipline:**
- Use the **actual prefix** observed in the repo. If auth lives at `server/src/modules/auth/`, use that exact string — not just `auth/`.
- Slash-terminate prefixes (`auth/`) so `auth_helpers.py` in another folder doesn't false-match.
- Don't include patterns that don't exist in this repo. Phantom patterns add noise without value.

### `test_file_patterns`

Substrings (case-insensitive) that mark a file as a test, used to compute `test_ratio`. Inspect a few real test files to learn the convention:

| Stack | Typical patterns |
|---|---|
| TS / NestJS | `.spec.ts` |
| TS / Jest | `.test.ts`, `.spec.ts`, `__tests__/` |
| Go | `_test.go` |
| Dart / Flutter | `_test.dart`, `test/` |
| Python pytest | `test_`, `_test.py`, `tests/` |

**Discipline:**
- Don't include patterns the repo doesn't use — false matches inflate `test_ratio` and create the illusion of test coverage.
- A monorepo may legitimately need multiple patterns.

### `dependency_file_patterns`

Substrings that mark dependency manifest/lockfile changes. Look at the repo root + any subpackages (monorepo).

| Manager | Files |
|---|---|
| npm | `package.json`, `package-lock.json` |
| yarn | `package.json`, `yarn.lock` |
| pnpm | `package.json`, `pnpm-lock.yaml` |
| Dart | `pubspec.yaml`, `pubspec.lock` |
| Python | `requirements.txt`, `pyproject.toml`, `poetry.lock` |
| Go | `go.mod`, `go.sum` |
| Rust | `Cargo.toml`, `Cargo.lock` |

Include manifest **and** lockfile — manifest-only PRs are a sign of careless dependency edits worth flagging too.

## 5. Repos to research

Each row gives you the starting hypothesis (likely stack) — **verify by inspection, don't trust**.

| # | Repo | Likely stack | Special notes |
|---|---|---|---|
| 1 | `mesher-labs/viv-monorepo` | TypeScript monorepo (probably NestJS server + flutter/web client) | "monorepo" implies multiple packages — paths likely have `server/`, `client/`, etc. prefixes. May have multiple test patterns / dep managers. |
| 2 | `mesher-labs/project-201-server` | TypeScript server (NestJS suspected) | NestJS convention is `.spec.ts` for tests. Look at `nest-cli.json` to confirm. |
| 3 | `mesher-labs/project-201-flutter` | Flutter / Dart | mobile build configs are sensitive (android signing, iOS provisioning). |
| 4 | `mesher-labs/if-character-chat-server` | TypeScript server | unusual prod branch `release/main/cbt` — possibly multi-track release. Auth/payment dirs may be inside cbt-specific subtrees. |
| 5 | `mesher-labs/if-character-chat-client` | unknown — likely Flutter or React | check `package.json` / `pubspec.yaml` to identify. |
| 6 | `mesher-labs/hokki-server` | TypeScript server (deploy YAML in CI) | prod branch is `master`. |
| 7 | `mesher-labs/hokki_flutter_app` | Flutter / Dart | prod is `main`, staging shares `develop` (no separate stage branch). |

For each, inspect the production-branch worktree mounted in §3 step 3.

Useful commands per repo:

```bash
WT=$AGENT_WORKSPACE_DIR/worktrees/research--<repo>

# Top-level layout
ls -la "$WT" && tree -L 2 "$WT" 2>/dev/null

# Find auth/payment/migration directories
find "$WT" -type d \( -iname "auth*" -o -iname "*payment*" -o -iname "*billing*" \
  -o -iname "*migration*" -o -iname "*secret*" \) | head -40

# Identify test convention
git -C "$WT" ls-files | grep -iE '(test|spec)' | head -20

# Identify dependency files
git -C "$WT" ls-files | grep -iE '(package\.json|package-lock|yarn\.lock|pnpm-lock|pubspec\.(yaml|lock)|requirements|pyproject|poetry\.lock|go\.(mod|sum)|Cargo\.(toml|lock))' | sort -u
```

## 6. Output: how to write the values

Edit [`packages/config/agent_secretary_config/service_map.py`](../../packages/config/agent_secretary_config/service_map.py). The file is at the top of `# ruff: noqa: E501` so long single-line entries are OK.

For each `Repo(...)` constructor in `SERVICE_MAP`, **add** a `review_rules=ReviewRules(...)` argument. Don't change anything else. Example:

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
            "server/src/migrations/",
        ),
        test_file_patterns=(".test.ts", ".spec.ts"),
        dependency_file_patterns=("package.json", "pnpm-lock.yaml"),
    ),
),
```

Add `from agent_secretary_config.review_rules import ReviewRules` at the top of `service_map.py` if it isn't already imported (it currently is — it's used as a default factory).

### Field omission policy

- **High-risk paths**: if you genuinely cannot find any high-risk directory in a repo (e.g., a thin client lib with no payment/auth code), it's OK to omit `high_risk_paths` entirely (defaults will apply, none of which match either — that's fine). **Do not** invent paths.
- **Test patterns**: omit only if you can't determine the convention. Better to be slightly broad (default `("test", "spec")`) than wrong.
- **Dependency patterns**: always include if the repo has any manifest. Defaults are reasonable but include the *exact* lockfile name for precision.

## 7. Tests to add

Append to [`tests/test_review_rules.py`](../../tests/test_review_rules.py). One test per repo, asserting on the most distinctive value you set:

```python
def test_viv_monorepo_review_rules_have_modules_auth():
    rules = review_rules_for("mesher-labs/viv-monorepo")
    resolved = resolve_rules(rules)
    assert "server/src/modules/auth/" in resolved.high_risk_paths
    assert ".spec.ts" in resolved.test_file_patterns
```

If you omit a field for a repo, write a test confirming the *fallback* still works:

```python
def test_thin_client_falls_back_for_high_risk_paths():
    rules = review_rules_for("mesher-labs/some-thin-client")
    resolved = resolve_rules(rules)
    assert resolved.high_risk_paths == HIGH_RISK_PATH_TAGS  # default
```

## 8. Validation (must pass before delivery)

```bash
uv run ruff check .                    # clean
uv run pytest tests/                   # all green (currently 49; should rise with your additions)
```

## 9. Boundaries — do NOT do these

- Do not touch the *structure* of `service_map.py` beyond adding `review_rules=` arguments. Keep `name`/`production`/`staging`/`dev` exactly as-is.
- Do not modify `review_rules.py` defaults.
- Do not edit the dispatcher prompt or specialist trigger patterns — that's a separate task.
- Do not commit the cloned bare repos or the research worktrees (they live outside this repo).
- Do not guess. If a repo's directory structure surprises you (e.g., no recognizable auth dir), note it in the commit message and *omit* `high_risk_paths` for that repo rather than fabricating.

## 10. Deliverable

A single commit on `main` (or a PR branch — your call) titled:

```
feat: populate per-repo review rules
```

Containing:
- Edited `packages/config/agent_secretary_config/service_map.py`
- New tests in `tests/test_review_rules.py`
- Commit message body that briefly notes anything **surprising** per repo (e.g., "if-character-chat-server has auth scattered across `cbt/` subdirs; high_risk_paths reflect that").

If a repo is genuinely empty / minimal / not yet structured, say so in the message and skip its `review_rules`.

## 11. Reference

Read these *before* starting:

- [`docs/review_rules.md`](../review_rules.md) — concept + tips
- [`docs/workspace.md`](../workspace.md) — bare-repo / worktree setup
- [`packages/config/agent_secretary_config/review_rules.py`](../../packages/config/agent_secretary_config/review_rules.py) — model definitions
- [`packages/config/agent_secretary_config/service_map.py`](../../packages/config/agent_secretary_config/service_map.py) — the file you'll edit
- [`tests/test_review_rules.py`](../../tests/test_review_rules.py) — existing test patterns to follow
