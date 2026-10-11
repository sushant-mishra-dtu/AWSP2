from __future__ import annotations


class ProviderError(Exception):
    """A data provider could not supply a usable response."""

    def __init__(self, provider: str, kind: str, message: str, status: int | None = None):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.kind = kind  # timeout | network | rate_limited | http | bad_response | not_configured
        self.status = status
        self.message = message

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "kind": self.kind,
            "status": self.status,
            "message": self.message,
        }
