"""Replay store: serves real provider responses captured earlier.

Replay mode exists for reproducible demos and tests. Every response produced
from it is labelled mode="replay" with the original capture time and source.
Requests that were not captured fail explicitly; nothing is interpolated or
synthesised to fill gaps.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import ProviderError


class ReplayStore:
    def __init__(self, data: dict[str, Any], path: str | None = None):
        self.data = data
        self.path = path
        meta = data.get("meta") or {}
        self.meta = meta
        self.captured_at = datetime.fromisoformat(meta["captured_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
        self.synthetic = bool(meta.get("synthetic", False))

    @classmethod
    def load(cls, path: Path) -> "ReplayStore":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f), str(path))

    def label(self) -> dict[str, Any]:
        return {
            "captured_at": self.meta.get("captured_at"),
            "synthetic": self.synthetic,
            "description": self.meta.get("description"),
            "sources": self.meta.get("sources"),
        }

    def point(self, lat: float, lon: float) -> dict[str, Any]:
        best = None
        for p in self.data.get("points", []):
            dlat, dlon = abs(p["lat"] - lat), abs(p["lon"] - lon)
            if dlat <= 0.2 and dlon <= 0.2:
                d = dlat + dlon
                if best is None or d < best[0]:
                    best = (d, p)
        if best is None:
            raise ProviderError("replay", "not_captured", "this location was not captured in the replay fixture")
        return best[1]

    def cell(self, cid: str) -> dict[str, Any] | None:
        return (self.data.get("cells") or {}).get(cid)

    def geocode(self, q: str) -> list[dict[str, Any]]:
        q = q.strip().lower()
        out: list[dict[str, Any]] = []
        for key, results in (self.data.get("geocode") or {}).items():
            if key.startswith(q) or q.startswith(key):
                out.extend(results)
        seen, uniq = set(), []
        for r in out:
            k = (r["name"], round(r["lat"], 3), round(r["lon"], 3))
            if k not in seen:
                seen.add(k)
                uniq.append(r)
        return uniq

    def stations(self) -> dict[str, Any] | None:
        return self.data.get("stations")
