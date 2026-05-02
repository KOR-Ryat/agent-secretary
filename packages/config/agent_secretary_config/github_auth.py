"""GitHub App authentication helper.

Generates short-lived installation access tokens from App credentials.
Tokens are cached and refreshed automatically 5 minutes before expiry.

Usage:
    auth = GitHubAppAuth.from_env()
    token = await auth.get_token()  # "ghs_..."
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field

import httpx
import jwt


@dataclass
class GitHubAppAuth:
    app_id: int
    installation_id: int
    private_key: str

    _token: str | None = field(default=None, repr=False, init=False)
    _expires_at: float = field(default=0.0, repr=False, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, init=False)

    @classmethod
    def from_env(cls) -> GitHubAppAuth:
        app_id = os.environ.get("GITHUB_APP_ID")
        installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID")
        private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY")
        if not app_id or not installation_id or not private_key:
            raise RuntimeError(
                "GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, and "
                "GITHUB_APP_PRIVATE_KEY are all required."
            )
        return cls(
            app_id=int(app_id),
            installation_id=int(installation_id),
            private_key=private_key,
        )

    async def get_token(self) -> str:
        async with self._lock:
            if self._token and time.time() < self._expires_at:
                return self._token
            self._token, self._expires_at = await self._fetch_token()
            return self._token

    def _make_jwt(self) -> str:
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 540, "iss": str(self.app_id)}
        return jwt.encode(payload, self.private_key, algorithm="RS256")

    async def _fetch_token(self) -> tuple[str, float]:
        app_jwt = self._make_jwt()
        url = f"https://api.github.com/app/installations/{self.installation_id}/access_tokens"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        token: str = data["token"]
        # expires_at is ISO 8601; cache until 5 min before actual expiry.
        from datetime import datetime
        expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        cache_until = expires_at.timestamp() - 300
        return token, cache_until
