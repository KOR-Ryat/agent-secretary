"""Specialist agent — parametrized PersonaAgent for all 19 specialists.

Specialists share the same code shape (prompt path, output model, parent
lead). Rather than 19 nearly-identical subclasses, we define them as data
in `SPECIALIST_CATALOG` and instantiate via the factory below.
"""
# ruff: noqa: E501 — the catalog rows are deliberately one-line for table-readability.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_secretary_schemas import PersonaOutput
from anthropic import AsyncAnthropic

from agents.personas._base import PersonaAgent


@dataclass(frozen=True)
class SpecialistSpec:
    name: str           # Korean name used by dispatcher (e.g., "DB·마이그레이션")
    persona_id: str     # snake_case stable id (e.g., "db_migrations")
    prompt_path: str    # path under prompts/, relative
    lead: str           # owning lead's Korean name (e.g., "운영")
    domain: str         # one of: security, ops, compatibility, product_ux


SPECIALIST_CATALOG: tuple[SpecialistSpec, ...] = (
    # 보안 산하
    SpecialistSpec("AuthN/AuthZ", "authn_authz", "specialists/security/authn_authz.md", "보안", "security"),
    SpecialistSpec("비밀·키 관리", "secrets_keys", "specialists/security/secrets_keys.md", "보안", "security"),
    SpecialistSpec("의존성·공급망", "dependencies", "specialists/security/dependencies.md", "보안", "security"),
    SpecialistSpec("입력 검증·인젝션", "input_validation", "specialists/security/input_validation.md", "보안", "security"),
    SpecialistSpec("암호화", "crypto", "specialists/security/crypto.md", "보안", "security"),
    SpecialistSpec("PII·데이터 노출", "pii", "specialists/security/pii.md", "보안", "security"),
    # 운영 산하
    SpecialistSpec("DB·마이그레이션", "db_migrations", "specialists/ops/db_migrations.md", "운영", "ops"),
    SpecialistSpec("성능·핫패스", "performance", "specialists/ops/performance.md", "운영", "ops"),
    SpecialistSpec("관측성", "observability", "specialists/ops/observability.md", "운영", "ops"),
    SpecialistSpec("인프라·IaC", "infrastructure", "specialists/ops/infrastructure.md", "운영", "ops"),
    SpecialistSpec("비동기·큐·재시도", "async_queue", "specialists/ops/async_queue.md", "운영", "ops"),
    SpecialistSpec("캐시·일관성", "cache", "specialists/ops/cache.md", "운영", "ops"),
    SpecialistSpec("비용", "cost", "specialists/ops/cost.md", "운영", "ops"),
    # 호환성 산하
    SpecialistSpec("외부 API", "external_api", "specialists/compatibility/external_api.md", "호환성", "compatibility"),
    SpecialistSpec("SDK", "sdk", "specialists/compatibility/sdk.md", "호환성", "compatibility"),
    SpecialistSpec("내부 RPC·메시지", "internal_rpc", "specialists/compatibility/internal_rpc.md", "호환성", "compatibility"),
    # 제품·UX 산하
    SpecialistSpec("사용자 흐름", "user_flow", "specialists/product_ux/user_flow.md", "제품·UX", "product_ux"),
    SpecialistSpec("접근성", "accessibility", "specialists/product_ux/accessibility.md", "제품·UX", "product_ux"),
    SpecialistSpec("i18n", "i18n", "specialists/product_ux/i18n.md", "제품·UX", "product_ux"),
)

SPECIALIST_BY_NAME: dict[str, SpecialistSpec] = {s.name: s for s in SPECIALIST_CATALOG}


class SpecialistAgent(PersonaAgent[PersonaOutput]):
    """Parametrized specialist persona — fields set in __init__."""

    output_model = PersonaOutput

    def __init__(
        self,
        spec: SpecialistSpec,
        client: AsyncAnthropic,
        prompts_dir: Path,
        model: str,
    ) -> None:
        self.persona_id = spec.persona_id
        self.prompt_path = spec.prompt_path
        self.model = model
        self._spec = spec
        super().__init__(client, prompts_dir)

    @property
    def lead_name(self) -> str:
        return self._spec.lead

    @property
    def display_name(self) -> str:
        return self._spec.name


def build_specialist(
    name: str,
    client: AsyncAnthropic,
    prompts_dir: Path,
    model: str,
) -> SpecialistAgent | None:
    spec = SPECIALIST_BY_NAME.get(name)
    if spec is None:
        return None
    return SpecialistAgent(spec, client, prompts_dir, model)
