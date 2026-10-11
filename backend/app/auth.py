"""Coordinator authentication.

* cognito: API Gateway's JWT authorizer validates the Cognito ID token before
  the Lambda runs; we read the verified claims from the API Gateway event.
  Requests without verified claims are rejected (defence in depth).
* local:   a LOCAL DEVELOPMENT sign-in (HMAC-signed token, no password) so the
  workflow can be exercised offline. It is labelled as such in /api/runtime
  and in the UI, and is refused when AUTH_MODE=cognito.

Authentication only identifies the user. Organisation ownership is enforced
separately in campus.py for every organisation-scoped request.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class User:
    sub: str
    name: str
    email: str | None = None
    groups: tuple[str, ...] = field(default_factory=tuple)
    method: str = "local"  # cognito | local

    def as_dict(self) -> dict:
        return {"sub": self.sub, "name": self.name, "email": self.email, "groups": list(self.groups), "method": self.method}


class LocalTokens:
    """HMAC tokens for local development only."""

    def __init__(self, secret: bytes):
        self.secret = secret

    @classmethod
    def from_file(cls, path: Path, env_secret: str = "") -> "LocalTokens":
        if env_secret:
            return cls(env_secret.encode())
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(secrets.token_hex(32), encoding="utf-8")
        return cls(path.read_text(encoding="utf-8").strip().encode())

    def issue(self, name: str, ttl_s: int = 12 * 3600) -> tuple[str, User]:
        clean = " ".join(name.split())[:60] or "Coordinator"
        sub = "local-" + hashlib.sha256(clean.lower().encode()).hexdigest()[:16]
        payload = {"sub": sub, "name": clean, "exp": int(time.time()) + ttl_s}
        body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
        sig = hmac.new(self.secret, body.encode(), hashlib.sha256).hexdigest()
        return f"{body}.{sig}", User(sub=sub, name=clean, method="local")

    def verify(self, token: str) -> User | None:
        try:
            body, sig = token.rsplit(".", 1)
            expected = hmac.new(self.secret, body.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):
                return None
            payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            if int(payload["exp"]) < time.time():
                return None
            return User(sub=payload["sub"], name=payload["name"], method="local")
        except (ValueError, KeyError, TypeError):
            return None

    def sign(self, message: str) -> str:
        return hmac.new(self.secret, message.encode(), hashlib.sha256).hexdigest()


def _groups(raw) -> tuple[str, ...]:
    if isinstance(raw, list):
        return tuple(str(g) for g in raw)
    if isinstance(raw, str) and raw:
        return tuple(g for g in raw.strip("[]").replace(",", " ").split() if g)
    return ()


def cognito_user_from_event(event: dict | None) -> User | None:
    claims = (((event or {}).get("requestContext") or {}).get("authorizer") or {}).get("jwt", {}).get("claims")
    if not claims or not claims.get("sub"):
        return None
    if claims.get("token_use") not in (None, "id"):
        return None
    return User(
        sub=str(claims["sub"]),
        name=str(claims.get("name") or claims.get("email") or "Coordinator"),
        email=claims.get("email"),
        groups=_groups(claims.get("cognito:groups")),
        method="cognito",
    )


def resolve_user(request: Request, auth_mode: str, tokens: LocalTokens | None) -> User | None:
    if auth_mode == "cognito":
        return cognito_user_from_event(request.scope.get("aws.event"))
    header = request.headers.get("authorization", "")
    if tokens and header.lower().startswith("bearer "):
        return tokens.verify(header[7:].strip())
    return None


def require(user: User | None) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    return user
