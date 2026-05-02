"""GitHub ingress plugin tests.

Exercises HMAC verification, event filtering (ping / unsupported types /
draft / non-handled actions), and RawEvent normalization. Uses a real
FastAPI TestClient against the parser-registered router so we cover the
route handler too.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient


def _sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _make_client(secret: str | None) -> tuple[TestClient, AsyncMock]:
    from ingress.plugins.github import GithubChannelParser

    publisher = AsyncMock()
    parser = GithubChannelParser(secret, publisher)
    app = FastAPI()
    router = APIRouter()
    parser.register_routes(router)
    app.include_router(router)
    return TestClient(app), publisher


def _pr_payload(*, action: str = "opened", draft: bool = False, labels: list[str] | None = None) -> dict:
    return {
        "action": action,
        "pull_request": {
            "number": 42,
            "title": "fix: tighten input validation",
            "body": "Adds parameterized query.",
            "user": {"login": "alice"},
            "head": {"sha": "abc123"},
            "base": {"sha": "def456"},
            "html_url": "https://github.com/owner/repo/pull/42",
            "draft": draft,
            "labels": [{"name": lbl} for lbl in (labels or [])],
        },
        "repository": {
            "owner": {"login": "owner"},
            "name": "repo",
            "full_name": "owner/repo",
        },
        "installation": {"id": 99},
    }


def _label_payload(*, label: str = "agent:request-review", draft: bool = False) -> dict:
    return {
        "action": "labeled",
        "label": {"name": label},
        "pull_request": {
            "number": 42,
            "title": "fix: tighten input validation",
            "body": "Adds parameterized query.",
            "user": {"login": "alice"},
            "head": {"sha": "abc123"},
            "base": {"sha": "def456"},
            "html_url": "https://github.com/owner/repo/pull/42",
            "draft": draft,
        },
        "repository": {
            "owner": {"login": "owner"},
            "name": "repo",
            "full_name": "owner/repo",
        },
        "installation": {"id": 99},
    }


def _post(
    client: TestClient,
    *,
    body: bytes,
    event_type: str,
    signature: str | None,
    delivery: str | None = "del-1",
) -> TestClient.responses:
    headers = {"X-GitHub-Event": event_type}
    if signature is not None:
        headers["X-Hub-Signature-256"] = signature
    if delivery is not None:
        headers["X-GitHub-Delivery"] = delivery
    return client.post("/public/channels/github/webhook", content=body, headers=headers)


# --- HMAC ---------------------------------------------------------------


@pytest.mark.parametrize(
    "signature_factory,expected_status",
    [
        # Valid signature → handler reaches parse logic.
        (lambda secret, body: _sign(secret, body), 200),
        # Wrong signature → 401.
        (lambda secret, body: _sign("wrong-secret", body), 401),
        # Malformed prefix → 401.
        (lambda secret, body: "deadbeef", 401),
    ],
)
def test_signature_verification(signature_factory, expected_status):
    secret = "test_secret_xyz"
    client, publisher = _make_client(secret)

    body = json.dumps(_label_payload()).encode()
    res = _post(
        client,
        body=body,
        event_type="pull_request",
        signature=signature_factory(secret, body),
    )

    assert res.status_code == expected_status
    if expected_status == 200:
        publisher.publish.assert_awaited_once()
    else:
        publisher.publish.assert_not_awaited()


def test_signature_missing_returns_401():
    client, publisher = _make_client("test_secret_xyz")
    body = json.dumps(_pr_payload()).encode()
    res = _post(client, body=body, event_type="pull_request", signature=None)
    assert res.status_code == 401
    publisher.publish.assert_not_awaited()


def test_signature_check_skipped_when_secret_unset():
    """No secret → handler logs a warning but processes the request anyway.

    Useful for local dev without webhook auth; in production the secret
    is always set.
    """
    client, publisher = _make_client(None)
    body = json.dumps(_label_payload()).encode()
    res = _post(client, body=body, event_type="pull_request", signature=None)
    assert res.status_code == 200
    publisher.publish.assert_awaited_once()


# --- Event filtering ----------------------------------------------------


def test_ping_event_acks_without_publishing():
    secret = "s"
    client, publisher = _make_client(secret)
    body = b'{"zen": "Practicality beats purity."}'
    res = _post(
        client,
        body=body,
        event_type="ping",
        signature=_sign(secret, body),
    )
    assert res.status_code == 200
    assert res.json() == {"status": "skipped"}
    publisher.publish.assert_not_awaited()


def test_unsupported_event_type_skipped():
    """`push`, `issue_comment`, etc. — not part of Phase 1 scope."""
    secret = "s"
    client, publisher = _make_client(secret)
    body = json.dumps({"ref": "refs/heads/main"}).encode()
    res = _post(
        client,
        body=body,
        event_type="push",
        signature=_sign(secret, body),
    )
    assert res.status_code == 200
    assert res.json() == {"status": "skipped"}
    publisher.publish.assert_not_awaited()


@pytest.mark.parametrize(
    "action,should_publish",
    [
        ("opened", True),
        ("synchronize", True),
        ("reopened", True),
        ("closed", False),
        ("labeled", False),
        ("review_requested", False),
    ],
)
def test_pr_action_filtering(action, should_publish):
    secret = "s"
    client, publisher = _make_client(secret)
    body = json.dumps(_pr_payload(action=action)).encode()
    res = _post(
        client,
        body=body,
        event_type="pull_request",
        signature=_sign(secret, body),
    )

    assert res.status_code == 200
    if should_publish:
        publisher.publish.assert_awaited_once()
    else:
        publisher.publish.assert_not_awaited()


def test_prevent_label_skips_auto_pr():
    secret = "s"
    client, publisher = _make_client(secret)
    body = json.dumps(_pr_payload(action="opened", labels=["agent:prevent-request"])).encode()
    res = _post(client, body=body, event_type="pull_request", signature=_sign(secret, body))
    assert res.status_code == 200
    publisher.publish.assert_not_awaited()


def test_draft_pr_is_skipped():
    secret = "s"
    client, publisher = _make_client(secret)
    body = json.dumps(_pr_payload(action="opened", draft=True)).encode()
    res = _post(
        client,
        body=body,
        event_type="pull_request",
        signature=_sign(secret, body),
    )
    assert res.status_code == 200
    publisher.publish.assert_not_awaited()


# --- Normalization ------------------------------------------------------


def test_pr_label_request_normalizes_to_raw_event():
    secret = "s"
    client, publisher = _make_client(secret)
    body = json.dumps(_label_payload()).encode()
    res = _post(
        client,
        body=body,
        event_type="pull_request",
        signature=_sign(secret, body),
        delivery="abc-123",
    )

    assert res.status_code == 200
    assert res.json() == {"status": "accepted", "event_id": "abc-123"}

    publisher.publish.assert_awaited_once()
    event = publisher.publish.await_args.args[0]

    # Source identification.
    assert event.source_channel == "github"
    assert event.event_id == "abc-123"

    # Normalized fields.
    n = event.normalized
    assert n["trigger"] == "label_request"
    assert n["repo"] == {
        "owner": "owner",
        "name": "repo",
        "full_name": "owner/repo",
    }
    assert n["pr"]["number"] == 42
    assert n["pr"]["title"] == "fix: tighten input validation"
    assert n["pr"]["author"] == "alice"
    assert n["pr"]["head_sha"] == "abc123"
    assert n["pr"]["url"] == "https://github.com/owner/repo/pull/42"
    assert n["installation_id"] == 99

    # Response routing — egress reads this to post the comment back.
    target = event.response_routing.primary.target
    assert event.response_routing.primary.channel == "github"
    assert target["repo"] == "owner/repo"
    assert target["pr_number"] == 42
    assert target["installation_id"] == 99


def test_event_id_falls_back_to_uuid_when_delivery_header_missing():
    secret = "s"
    client, publisher = _make_client(secret)
    body = json.dumps(_label_payload()).encode()
    res = _post(
        client,
        body=body,
        event_type="pull_request",
        signature=_sign(secret, body),
        delivery=None,
    )
    assert res.status_code == 200
    event = publisher.publish.await_args.args[0]
    # uuid4 hex form is 36 chars (8-4-4-4-12 + dashes).
    assert len(event.event_id) == 36
    assert event.event_id.count("-") == 4
