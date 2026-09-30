"""This gateway's own record of each request, for run_cache.py. LITELLM ONLY.

LiteLLM keeps one spend-log row per request — `GET /spend/logs?summarize=false` —
with everything run_cache.py needs and nothing to switch on:

    startTime, endTime      the request, as the gateway saw it
    completionStartTime     the first token back — meaningful only when the client
                            streamed, which proxy_server_request.stream says
    prompt_tokens, ...      the counts the upstream reported
    usage_object            the usage the CLIENT was sent, cached tokens included
                            when the engine reported any
    spend                   the cost, at the route's price or OpenRouter's own figure

THE ROWS ARE WRITTEN IN BATCHES, a few seconds after the request, so `finish()`
waits for the count to stop growing rather than reading once.

The master key reads /spend/logs; a virtual key may not. Envoy's copy of this file
reads Envoy's access log and metrics instead — the one file per project that knows
how its gateway records a request, so run_cache.py itself stays byte-identical.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from gateway import ROOT_URL

MASTER_KEY = os.environ.get("LITELLM_MASTER_KEY") or "sk-litellm-master"

# Rows land in batches; this long with no new row means the batch is in.
SETTLE_SECONDS = 12
GIVE_UP_SECONDS = 90


class Recorder:
    """The requests one alias made between `start()` and `finish()`."""

    def __init__(self, alias: str) -> None:
        self.alias = alias
        # Envoy's copy fills this with per-session token sums; every row here
        # already carries its own counts.
        self.totals: dict[str, float] | None = None

    def start(self) -> None:
        """Nothing to snapshot: every row carries its own time."""

    def finish(self, started: float, finished: float) -> list[dict]:
        rows, deadline = [], time.monotonic() + GIVE_UP_SECONDS
        while time.monotonic() < deadline:
            time.sleep(SETTLE_SECONDS)
            latest = self._rows(started, finished)
            if rows and len(latest) == len(rows):
                break
            rows = latest
        return rows

    def _rows(self, started: float, finished: float) -> list[dict]:
        day = datetime.fromtimestamp(started, timezone.utc).date()
        url = (
            f"{ROOT_URL}/spend/logs?summarize=false"
            f"&start_date={day.isoformat()}&end_date={(day + timedelta(days=1)).isoformat()}"
        )
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {MASTER_KEY}"})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
        rows = payload if isinstance(payload, list) else payload.get("data", [])
        mine = [
            _request_of(row)
            for row in rows
            if row.get("model_group") == self.alias and started - 2 <= _seconds(row.get("startTime")) <= finished + 2
        ]
        return sorted(mine, key=lambda request: request["start"])


def _seconds(value: str | None) -> float:
    if not value:
        return 0.0
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _request_of(row: dict) -> dict:
    usage = (row.get("metadata") or {}).get("usage_object") or {}
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens") or usage.get("cache_read_input_tokens") or 0
    start, end = _seconds(row.get("startTime")), _seconds(row.get("endTime"))
    first = _seconds(row.get("completionStartTime"))
    # THE CLIENT'S OWN BODY SAYS IF IT STREAMED. completionStartTime alone does not:
    # on a call that did not stream it sits 0-1 ms before endTime, and read as a first
    # token it made tokens/s come out at 44000 (2026-09-30).
    streamed = bool((row.get("proxy_server_request") or {}).get("stream"))
    return {
        "start": start,
        "route": row.get("call_type"),
        "seconds": round(end - start, 3),
        "ttft_s": round(first - start, 3) if streamed else None,
        "prompt_tokens": row.get("prompt_tokens"),
        "completion_tokens": row.get("completion_tokens"),
        "cached_reported": cached,
        "cost_usd": row.get("spend"),
    }
