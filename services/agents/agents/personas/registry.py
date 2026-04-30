"""Registry mapping dispatcher's persona names → persona classes.

The dispatcher prompt outputs Korean lead/specialist names (e.g., "보안",
"DB·마이그레이션"). The registry resolves those to the concrete PersonaAgent
subclasses.
"""

from __future__ import annotations

from pathlib import Path

from anthropic import AsyncAnthropic

from agents.personas._base import PersonaAgent
from agents.personas.leads.compatibility import CompatibilityLead
from agents.personas.leads.ops import OpsLead
from agents.personas.leads.product_ux import ProductUxLead
from agents.personas.leads.quality import QualityLead
from agents.personas.leads.security import SecurityLead

# Korean lead names from the dispatcher prompt → lead classes.
LEAD_BY_NAME: dict[str, type[PersonaAgent]] = {
    "보안": SecurityLead,
    "품질": QualityLead,
    "운영": OpsLead,
    "호환성": CompatibilityLead,
    "제품·UX": ProductUxLead,
}

# Map to which lead synthesizes a given specialist (for Stage B; not yet wired).
SPECIALIST_TO_LEAD: dict[str, str] = {
    # security
    "AuthN/AuthZ": "보안",
    "비밀·키 관리": "보안",
    "의존성·공급망": "보안",
    "입력 검증·인젝션": "보안",
    "암호화": "보안",
    "PII·데이터 노출": "보안",
    # ops
    "DB·마이그레이션": "운영",
    "성능·핫패스": "운영",
    "관측성": "운영",
    "인프라·IaC": "운영",
    "비동기·큐·재시도": "운영",
    "캐시·일관성": "운영",
    "비용": "운영",
    # compatibility
    "외부 API": "호환성",
    "SDK": "호환성",
    "내부 RPC·메시지": "호환성",
    # product_ux
    "사용자 흐름": "제품·UX",
    "접근성": "제품·UX",
    "i18n": "제품·UX",
}


def build_lead(
    name: str,
    client: AsyncAnthropic,
    prompts_dir: Path,
    model: str,
) -> PersonaAgent | None:
    cls = LEAD_BY_NAME.get(name)
    if cls is None:
        return None
    return cls(client, prompts_dir, model)
