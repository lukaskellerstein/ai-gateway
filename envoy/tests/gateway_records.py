"""This gateway's own record of each request, for run_cache.py. ENVOY ONLY.

Envoy keeps two records, and run_cache.py needs both:

    the access log     one JSON line per request — start, duration, input, output
                       and reasoning tokens (config/<engine>.yaml § accessLog). It
                       reaches `podman logs` ONLY with AIGW_DEBUG=true. It carries
                       NO cached tokens and NO time to first token.
    26064/metrics      `gen_ai_client_token_usage`, a histogram per alias and token
                       type — `cached_input` included. Its SUM before and after a
                       session is the session's cached total.

So an Envoy row has per-request timing and token counts, and the cached tokens
only per session. Measured 2026-09-30: both records present with AIGW_DEBUG=true.

LiteLLM's copy of this file reads /spend/logs instead — the one file per project
that knows how its gateway records a request, so run_cache.py stays byte-identical.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.request
from datetime import datetime

from gateway import ADMIN_URL

# compose's own name for the one service, in the project `ai-gateway-envoy`.
CONTAINER = "ai-gateway-envoy-envoy-1"

# Envoy writes an access line when a reply ENDS and flushes it on its own clock,
# so a streamed request's line can land seconds after the client has its answer.
FLUSH_POLL_SECONDS = 3
FLUSH_GIVE_UP_SECONDS = 30

TOKEN_METRIC = re.compile(
    r'^gen_ai_client_token_usage_(?P<stat>sum|count)\{(?P<labels>[^}]*)\} (?P<value>[0-9.e+]+)$'
)
LABEL = re.compile(r'(\w+)="([^"]*)"')


class Recorder:
    """The requests one alias made between `start()` and `finish()`."""

    def __init__(self, alias: str) -> None:
        # Folder 5 calls the `-anthropic` twin of the alias; it is the same model.
        self.names = {alias, f"{alias}-anthropic"}
        self.before: dict[str, float] = {}
        self.totals: dict[str, float] | None = None

    def start(self) -> None:
        self.before = self._token_sums()

    def finish(self, started: float, finished: float) -> list[dict]:
        after = self._token_sums()
        self.totals = {kind: after.get(kind, 0) - self.before.get(kind, 0) for kind in after}
        return self._access_lines(started, finished, expected=int(self.totals.get("requests", 0)))

    def _token_sums(self) -> dict[str, float]:
        """So far for this alias: tokens by type (input, cached_input, output, ...),
        and `requests` — how many requests reported an input count."""
        with urllib.request.urlopen(f"{ADMIN_URL}/metrics", timeout=10) as response:
            text = response.read().decode()
        sums: dict[str, float] = {}
        for line in text.splitlines():
            found = TOKEN_METRIC.match(line)
            if not found:
                continue
            labels = dict(LABEL.findall(found.group("labels")))
            if labels.get("gen_ai_original_model") not in self.names:
                continue
            kind = labels.get("gen_ai_token_type", "?")
            if found.group("stat") == "count":
                kind = "requests" if kind == "input" else None
            if kind:
                sums[kind] = sums.get(kind, 0) + float(found.group("value"))
        return sums

    def _access_lines(self, started: float, finished: float, expected: int) -> list[dict]:
        """Every access line of the session — polled until the metrics' count is in."""
        deadline = time.monotonic() + FLUSH_GIVE_UP_SECONDS
        requests = self._read_access_lines(started, finished)
        while len(requests) < expected and time.monotonic() < deadline:
            time.sleep(FLUSH_POLL_SECONDS)
            requests = self._read_access_lines(started, finished)
        return requests

    def _read_access_lines(self, started: float, finished: float) -> list[dict]:
        # A UNIX TIMESTAMP, not an ISO one: podman read "…Z" as LOCAL time and so
        # asked for logs two hours in the future — zero lines, no error (2026-09-30).
        since = str(int(started - 2))
        logs = subprocess.run(
            ["podman", "logs", "--since", since, CONTAINER], capture_output=True, text=True, timeout=60
        )
        requests = []
        for line in (logs.stdout + logs.stderr).splitlines():
            if '"gen_ai.request.model"' not in line or not line.startswith("{"):
                continue
            entry = json.loads(line)
            start = datetime.fromisoformat(entry["start_time"].replace("Z", "+00:00")).timestamp()
            if entry.get("gen_ai.request.model") in self.names and started - 2 <= start <= finished + 2:
                requests.append(_request_of(entry, start))
        return sorted(requests, key=lambda request: request["start"])


def _request_of(entry: dict, start: float) -> dict:
    return {
        "start": start,
        "route": entry.get("request.path"),
        "status": entry.get("response_code"),
        "seconds": round((entry.get("duration") or 0) / 1000, 3),
        "ttft_s": None,  # the access log has no time to first token
        "prompt_tokens": entry.get("gen_ai.usage.input_tokens"),
        "completion_tokens": entry.get("gen_ai.usage.output_tokens"),
        "reasoning_tokens": entry.get("gen_ai.usage.reasoning_tokens"),
        "cached_reported": None,  # per session only — see Recorder.totals
    }
