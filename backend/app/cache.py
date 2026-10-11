"""Bounded in-memory TTL cache with explicit stale fallback.

A cached value is "fresh" for `ttl_s`. After that it may still be served, but
only when a fresh fetch fails, only up to `max_stale_s`, and always flagged as
stale with its original retrieval time. Nothing is ever synthesised.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Hashable

from .errors import ProviderError


@dataclass
class Entry:
    value: Any
    stored_at: float  # epoch seconds


class TTLCache:
    def __init__(self, maxsize: int, ttl_s: float, max_stale_s: float, clock: Callable[[], float] = time.time):
        self.maxsize = maxsize
        self.ttl_s = ttl_s
        self.max_stale_s = max_stale_s
        self._clock = clock
        self._data: OrderedDict[Hashable, Entry] = OrderedDict()
        self._lock = threading.Lock()

    def _get(self, key: Hashable, max_age: float) -> Entry | None:
        with self._lock:
            e = self._data.get(key)
            if e is None:
                return None
            age = self._clock() - e.stored_at
            if age > self.max_stale_s:
                del self._data[key]
                return None
            if age > max_age:
                return None
            self._data.move_to_end(key)
            return e

    def get_fresh(self, key: Hashable) -> Entry | None:
        return self._get(key, self.ttl_s)

    def get_stale(self, key: Hashable) -> Entry | None:
        return self._get(key, self.max_stale_s)

    def set(self, key: Hashable, value: Any) -> Entry:
        with self._lock:
            e = Entry(value=value, stored_at=self._clock())
            self._data[key] = e
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)
            return e

    def __len__(self) -> int:
        return len(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


def cache_meta(entry: Entry, status: str, error: str | None = None) -> dict[str, Any]:
    from datetime import datetime, timezone

    return {
        "status": status,  # "miss" (fetched now), "hit" (fresh cache), "stale" (fetch failed)
        "stale": status == "stale",
        "retrieved_at": datetime.fromtimestamp(entry.stored_at, timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "error": error,
    }


async def cached_fetch(
    cache: TTLCache, key: Hashable, fetch: Callable[[], Awaitable[Any]]
) -> tuple[Any, dict[str, Any]]:
    """Return (value, meta). Raises ProviderError if no usable value exists."""
    e = cache.get_fresh(key)
    if e is not None:
        return e.value, cache_meta(e, "hit")
    try:
        value = await fetch()
    except ProviderError as err:
        stale = cache.get_stale(key)
        if stale is not None:
            return stale.value, cache_meta(stale, "stale", str(err))
        raise
    e = cache.set(key, value)
    return value, cache_meta(e, "miss")
