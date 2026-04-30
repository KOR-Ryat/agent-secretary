"""Service ↔ repo ↔ Slack channel mapping.

Static config used by:
  - the slack ingress plugin (resolve channel → service + repos for context)
  - code-touching workflows (resolve service → repos to mount as worktrees)
  - the dashboard (display channel names)

Per-codebase tuning is intentional. Changes here are config edits, not
code changes — review them as you would any data file.
"""
# ruff: noqa: E501 — service-map rows are deliberately one-line for table-readability.

from __future__ import annotations

from pydantic import BaseModel

from agent_secretary_config.channel_names import CHANNEL_NAMES


class Repo(BaseModel, frozen=True):
    """A repository with its branch-strategy across deploy environments."""

    name: str            # e.g. "mesher-labs/project-201-server"
    production: str
    staging: str
    dev: str

    @property
    def short_name(self) -> str:
        return self.name.rsplit("/", 1)[-1]


class Channel(BaseModel, frozen=True):
    """A Slack channel that maps onto a service environment."""

    id: str              # Slack channel ID (e.g. "C099J0X5ZPF")
    name: str            # human-readable channel name
    env: str             # "production" | "staging" | "stage" — preserved verbatim from legacy data


class Service(BaseModel, frozen=True):
    """A logical service: a set of repos and the channels that talk about them."""

    key: str             # e.g. "if", "ifcc", "viv", "zendi"
    repos: tuple[Repo, ...]
    channels: tuple[Channel, ...]


class ChannelResolution(BaseModel, frozen=True):
    """Result of `resolve_channel(channel_id)`."""

    service: str | None         # None when the channel is not part of any service
    env: str | None
    channel_name: str           # human-readable; falls back to raw ID if unknown
    repos: tuple[Repo, ...]


# --- Data ----------------------------------------------------------------

# Note: legacy data uses both "staging" and "stage" for env values. Preserved
# verbatim so channel naming stays stable; downstream code should match
# either spelling when asking "is this a non-prod channel?".

SERVICE_MAP: dict[str, Service] = {
    "if": Service(
        key="if",
        repos=(
            Repo(name="mesher-labs/project-201-server", production="main", staging="stage", dev="dev"),
            Repo(name="mesher-labs/project-201-flutter", production="main", staging="stage", dev="dev"),
        ),
        channels=(
            Channel(id="C099J0X5ZPF", name="if-dm-production", env="production"),
            Channel(id="C099XH6QR97", name="if-payment-production", env="production"),
            Channel(id="C099HLE93DY", name="if-sns-production", env="production"),
            Channel(id="C09DLE2MQR2", name="if-taskfail-production", env="production"),
            Channel(id="C09DKHDTV4L", name="if-taskfail-staging", env="staging"),
            Channel(id="C09C2EDPJMD", name="if-training-production", env="production"),
            Channel(id="C09DGJ46N3Y", name="if-training-staging", env="staging"),
            Channel(id="C099NF04J76", name="if-worldchat-production", env="production"),
        ),
    ),
    "ifcc": Service(
        key="ifcc",
        repos=(
            Repo(name="mesher-labs/if-character-chat-server", production="release/main/cbt", staging="release/stage/cbt", dev="dev"),
            Repo(name="mesher-labs/if-character-chat-client", production="main", staging="stage", dev="dev"),
        ),
        channels=(
            Channel(id="C0ADCFJG0SE", name="ifcc-admin-production", env="production"),
            Channel(id="C0A3NNRNCDS", name="ifcc-error-production", env="production"),
            Channel(id="C0A3CP2RNF5", name="ifcc-error-stage", env="stage"),
            Channel(id="C0ADCBLRJ9G", name="ifcc-payment-production", env="production"),
            Channel(id="C0AB9CXEXT6", name="ifcc-world-production", env="production"),
            Channel(id="C0AB9CZJ45A", name="ifcc-world-stage", env="stage"),
            Channel(id="C0A3Y36N4KB", name="ifcc-worldchat-production", env="production"),
            Channel(id="C0A3K4UCC9Y", name="ifcc-worldchat-stage", env="stage"),
        ),
    ),
    "viv": Service(
        key="viv",
        repos=(
            Repo(name="mesher-labs/viv-monorepo", production="main", staging="stage", dev="dev"),
        ),
        channels=(
            Channel(id="C0AP99YFQNN", name="viv-app-production", env="production"),
            Channel(id="C0AP5T2DH9B", name="viv-chat-production", env="production"),
            Channel(id="C0AP2U4AFQB", name="viv-error-production", env="production"),
            Channel(id="C0AP9A27D5Y", name="viv-feed-production", env="production"),
            Channel(id="C0AP1PV59GT", name="viv-payment-production", env="production"),
        ),
    ),
    "zendi": Service(
        key="zendi",
        repos=(
            Repo(name="mesher-labs/hokki-server", production="master", staging="stage", dev="dev"),
            Repo(name="mesher-labs/hokki_flutter_app", production="main", staging="develop", dev="develop"),
        ),
        channels=(
            Channel(id="C07K26G5CNB", name="zendi-alarm-production", env="production"),
            Channel(id="C07K7E44A73", name="zendi-alarm-stage", env="stage"),
        ),
    ),
}


# --- Lookup helpers ------------------------------------------------------

# Build reverse index once at import time.
_CHANNEL_INDEX: dict[str, tuple[Service, Channel]] = {}
for _service in SERVICE_MAP.values():
    for _channel in _service.channels:
        _CHANNEL_INDEX[_channel.id] = (_service, _channel)


def resolve_channel(channel_id: str) -> ChannelResolution:
    """Look up a Slack channel ID.

    For channels that belong to a known service, returns the service key,
    its env, the channel's name, and the service's repos.

    For other channels, returns a resolution with `service=None` and a
    human-readable channel name (from CHANNEL_NAMES) or the raw ID.
    """
    hit = _CHANNEL_INDEX.get(channel_id)
    if hit is not None:
        service, channel = hit
        return ChannelResolution(
            service=service.key,
            env=channel.env,
            channel_name=channel.name,
            repos=service.repos,
        )
    return ChannelResolution(
        service=None,
        env=None,
        channel_name=CHANNEL_NAMES.get(channel_id, channel_id),
        repos=(),
    )


def all_repos() -> tuple[Repo, ...]:
    """Flatten every service's repos. Useful for setup scripts (bare clone)."""
    seen: dict[str, Repo] = {}
    for service in SERVICE_MAP.values():
        for repo in service.repos:
            seen.setdefault(repo.name, repo)
    return tuple(seen.values())
