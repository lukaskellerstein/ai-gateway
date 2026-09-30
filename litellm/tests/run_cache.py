"""Measure the prompt cache and the speed of every agent, on the aliases you name.

    uv run run_cache.py --aliases lms-gemma4-26b,lms-qwen38-27b
    uv run run_cache.py --aliases unsloth-qwen38-27b --agents claude,claude-tuned
    uv run run_cache.py --aliases openrouter-gemma4-26b --out cache-results/paid.jsonl

ONE SESSION PER ALIAS PER AGENT: each agent's own multi-turn scenario, run exactly
as the test suite runs it, with the thinking level held at `medium` (gateway.py §
REASONING_EFFORT). Nothing is replayed — the model steers every conversation.

THE NUMBERS COME FROM WHAT ALREADY RECORDS EVERY REQUEST, read for the time window
of one session. Sessions run one after another, so a window belongs to one session:

    this gateway    gateway_records.py — the gateway's own record of each request,
                    which is also what a client is TOLD about the cache
    LMStudio        `lms log stream`: what the engine REALLY reused (`Prompt cache
                    restore`), its time to first token and decode speed, and the
                    thinking level its template received

The two cache counts differ, and that is the point of keeping both: LMStudio hits
its cache on /v1/chat/completions but reports no cached tokens there at all.

Claude runs twice. `claude` is the CLI as shipped; `claude-tuned` sets the two
variables that stop it rewriting the prompt — a billing header at the top of the
system prompt, and a `<total_tokens>` system message after every tool result, which
lands in the system block, in front of the tool list and every message. Measured
2026-09-30 with the SDK's bundled CLI 2.1.259 on LMStudio, both gateways: the last
turn reused 22% (Gemma 4 26B) and 0% (Qwen 3.8 27B) as shipped, 76-93% tuned. The
header's suffix changes per conversation, not per request, in that version.

Where a prompt stops matching the earlier one, the engine log's own text around that
point is kept (`parts_at`), so a miss names its cause.

One JSON line per session goes to --out, the first line describing the machine.
`benchmark/cache_report.py`, at the repo root, turns the files into a table. Standard library only,
like gateway.py, so it runs in any venv.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# gateway.py resolves a DEFAULT alias at import and exits when GATEWAY_ENGINE names
# no single engine (`all`, `lukas`). This script names every alias itself and hands
# each session its own, so the default is never used here.
os.environ.setdefault("AI_GATEWAY_TEST_MODEL", "chosen-per-session-by-run_cache.py")

import gateway_records  # noqa: E402
from gateway import NAME  # noqa: E402

# The level every session runs at. `medium` because Qwen 3.8 defaults to `xhigh`,
# where one agent step took 693 s and answered nothing (gateway.py).
DEFAULT_EFFORT = "medium"

# A session that runs longer than this is recorded as a timeout, not waited for.
SESSION_TIMEOUT_SECONDS = 45 * 60

# How long to wait for another client's request on the same LMStudio model to end.
# Each model runs one request at a time here, so a busy model would queue ours and
# the queue would count as our time.
IDLE_WAIT_SECONDS = 600

CLAUDE_CACHE_SETTINGS = {"CLAUDE_CODE_ATTRIBUTION_HEADER": "0", "CLAUDE_CODE_TOTAL_TOKENS_REMINDER": "off"}


@dataclass(frozen=True)
class Agent:
    name: str
    folder: str
    script: str
    env: dict = field(default_factory=dict)
    unset: tuple = ()


# Each folder's multi-turn scenario — the one where a second request can reuse the
# first one's prompt. Order is the teaching order, as in run_all.py.
#
# CLAUDE RUNS ITS TOOL SCENARIO, NOT ITS SESSION ONE. The `<total_tokens>` reminder
# is added after a tool RESULT, and 02_session.py calls no tool — so on it the second
# setting had nothing to switch off (2026-09-30).
AGENTS = (
    Agent("http", "1_http_client", "main.py"),
    Agent("openai", "2_openai_client", "02_tools_call.py"),
    Agent("langchain", "3_langchain_langgraph", "main.py"),
    Agent("deepagents", "4_deepagents", "04_tools.py"),
    Agent("claude", "5_claude_agent_sdk", "03_sdk_mcp.py", unset=tuple(CLAUDE_CACHE_SETTINGS)),
    Agent("claude-tuned", "5_claude_agent_sdk", "03_sdk_mcp.py", env=CLAUDE_CACHE_SETTINGS),
    Agent("codex", "6_codex_sdk", "02_session.py"),
    Agent("opencode", "7_opencode_sdk", "02_session.py"),
)

# LMStudio's own id for each `lms-*` alias — what config/lms.yaml sends as
# `lm_studio/<id>`. The engine logs under this id, never under the alias.
LMS_MODEL_IDS = {
    "lms-gemma4-e4b": "google/gemma-4-e4b",
    "lms-gemma4-26b": "google/gemma-4-26b-a4b-qat",
    "lms-qwen38-27b": "qwen/qwen3.8-27b",
}

CACHE_RESTORE = re.compile(r"Prompt cache restore: cached_tokens=(\d+) uncached_tokens=(\d+)")
# Qwen 3.8 writes the level into the prompt for every level but `medium`.
EFFORT_LINE = re.compile(r"Reasoning effort is set to (\w+)")


# ---------------------------------------------------------------------------
# LMStudio — what the engine really did
# ---------------------------------------------------------------------------


class LmsLog:
    """Two `lms log stream` processes for the length of one session.

    A thread drains each one, so a long prompt echoed on the input stream can
    never fill a pipe and stall LMStudio's logger.
    """

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.lines: dict[str, list[str]] = {"model": [], "runtime": []}
        self.processes: list[subprocess.Popen] = []

    def __enter__(self) -> LmsLog:
        for source, extra in (("model", ["--stats"]), ("runtime", [])):
            process = subprocess.Popen(
                ["lms", "log", "stream", "-s", source, "--json", *extra],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            threading.Thread(target=self._drain, args=(process, self.lines[source]), daemon=True).start()
            self.processes.append(process)
        time.sleep(2)  # the stream attaches asynchronously; a request before that is lost
        return self

    def __exit__(self, *_: object) -> None:
        time.sleep(2)  # the last output event lands after the HTTP reply
        for process in self.processes:
            process.terminate()
            process.wait(timeout=10)

    @staticmethod
    def _drain(process: subprocess.Popen, into: list[str]) -> None:
        for line in process.stdout:
            into.append(line)

    def requests(self) -> list[dict]:
        """One entry per request this model served, in order."""
        inputs, outputs, restores = [], [], []
        for line in self.lines["model"]:
            data = _event(line)
            if data.get("modelIdentifier") != self.model_id:
                continue
            if data.get("type") == "llm.prediction.input":
                text = data.get("input", "")
                found = EFFORT_LINE.search(text[:2000])
                earlier = [previous["text"] for previous in inputs]
                inputs.append(
                    {"text": text, "effort_in_prompt": found.group(1) if found else "none written", **_parting(text, earlier)}
                )
            elif data.get("type") == "llm.prediction.output":
                outputs.append(data.get("stats", {}))
        for line in self.lines["runtime"]:
            data = _event(line)
            found = CACHE_RESTORE.search(data.get("message", ""))
            if found and data.get("modelIdentifier") == self.model_id:
                restores.append((int(found.group(1)), int(found.group(2))))

        count = max(len(inputs), len(outputs), len(restores))
        return [
            {
                "cached": restores[i][0] if i < len(restores) else None,
                "uncached": restores[i][1] if i < len(restores) else None,
                "ttft_s": outputs[i].get("timeToFirstTokenSec") if i < len(outputs) else None,
                "decode_tok_s": outputs[i].get("tokensPerSecond") if i < len(outputs) else None,
                "prompt_tokens": outputs[i].get("promptTokensCount") if i < len(outputs) else None,
                "completion_tokens": outputs[i].get("predictedTokensCount") if i < len(outputs) else None,
                **({key: value for key, value in inputs[i].items() if key != "text"} if i < len(inputs) else {}),
            }
            for i in range(count)
        ]


# Characters of prompt kept on each side of the point where it parts from an earlier one.
PARTING_CONTEXT = 60


def _parting(text: str, earlier: list[str]) -> dict:
    """How much of this prompt an earlier prompt of the session already had.

    The engine can only reuse a shared PREFIX, so this is the most it could have
    reused. When the prompt does not contain the whole earlier one, the client
    rewrote something before the end, and `parts_at` shows the text around the
    point where they part — the cause of the miss, in the prompt's own words.
    """
    best = max(earlier, key=lambda other: len(os.path.commonprefix([text, other])), default="")
    shared = len(os.path.commonprefix([text, best]))
    rewritten = bool(best) and shared < len(best)
    return {
        "prompt_chars": len(text),
        "shared_chars": shared if best else None,
        "earlier_chars": len(best) if best else None,
        "parts_at": text[max(0, shared - PARTING_CONTEXT) : shared + PARTING_CONTEXT] if rewritten else "",
    }


def _event(line: str) -> dict:
    if not line.startswith("{"):
        return {}
    try:
        return json.loads(line).get("data", {})
    except json.JSONDecodeError:
        return {}


def lms_state(model_id: str) -> dict:
    for model in json.loads(_output(["lms", "ps", "--json"]) or "[]"):
        if model.get("identifier") == model_id:
            return model
    return {}


def wait_until_idle(model_id: str) -> dict:
    """Wait for another client's request to finish. Returns what was seen first."""
    first = lms_state(model_id)
    deadline = time.monotonic() + IDLE_WAIT_SECONDS
    state = first
    while state and (state.get("status") != "idle" or state.get("queued")) and time.monotonic() < deadline:
        time.sleep(5)
        state = lms_state(model_id)
    return {"status": first.get("status"), "queued": first.get("queued"), "waited_until_idle": state.get("status")}


# ---------------------------------------------------------------------------
# One session
# ---------------------------------------------------------------------------


def run_session(agent: Agent, alias: str, effort: str | None) -> dict:
    environment = {key: value for key, value in os.environ.items() if key not in ("VIRTUAL_ENV", *agent.unset)}
    environment.update(agent.env)
    environment["AI_GATEWAY_TEST_MODEL"] = alias  # gateway.py reads it at import
    if effort:
        environment["AI_GATEWAY_REASONING_EFFORT"] = effort

    model_id = LMS_MODEL_IDS.get(alias)
    engine_before = wait_until_idle(model_id) if model_id else None
    recorder = gateway_records.Recorder(alias)
    command = ["uv", "run", "--directory", str(HERE / agent.folder), agent.script, "--model", alias]

    with LmsLog(model_id) if model_id else contextlib.nullcontext() as log:
        recorder.start()
        started = time.time()
        try:
            process = subprocess.run(
                command, env=environment, capture_output=True, text=True, timeout=SESSION_TIMEOUT_SECONDS
            )
            outcome = "pass" if process.returncode == 0 else "fail"
            output = process.stdout + process.stderr
        except subprocess.TimeoutExpired as expired:
            outcome, output = "timeout", f"{expired.stdout or ''}{expired.stderr or ''}"
        finished = time.time()

    return {
        "kind": "session",
        "gateway": NAME,
        "alias": alias,
        "agent": agent.name,
        "effort_sent": effort,
        "outcome": outcome,
        "seconds": round(finished - started, 1),
        "started": datetime.fromtimestamp(started, timezone.utc).isoformat(),
        "engine_before": engine_before,
        "gateway_requests": recorder.finish(started, finished),
        "gateway_totals": recorder.totals,
        "engine_requests": log.requests() if log else None,
        "output_tail": "" if outcome == "pass" else output[-3000:],
    }


# ---------------------------------------------------------------------------
# The machine, once per file
# ---------------------------------------------------------------------------


def _output(command: list[str], cwd: Path | None = None) -> str:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=120, cwd=cwd).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def unsloth_state() -> dict:
    key = os.environ.get("UNSLOTH_API_KEY", "")
    request = urllib.request.Request("http://localhost:8888/v1/status", headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = json.load(response)
    except OSError:
        return {}
    wanted = ("active_model", "gguf_variant", "context_length", "parallel_slots", "cache_type_kv")
    return {name: status.get(name) for name in wanted}


def _in_venv(folder: str, code: str) -> str:
    return _output(["uv", "run", "python", "-c", code], cwd=HERE / folder)


def header(effort: str | None) -> dict:
    return {
        "kind": "header",
        "gateway": NAME,
        "at": datetime.now(timezone.utc).isoformat(),
        "effort": effort,
        # THE SDK RUNS ITS OWN BUNDLED CLI, not the `claude` on PATH: the prompt said
        # `cc_version=2.1.259` while `claude --version` said 2.1.285 (2026-09-30).
        "claude_sdk_cli": _in_venv(
            "5_claude_agent_sdk", "from claude_agent_sdk._cli_version import __cli_version__; print(__cli_version__)"
        ),
        "openai_codex": _in_venv("6_codex_sdk", "import importlib.metadata as m; print(m.version('openai-codex'))"),
        "opencode": _output(["opencode", "--version"]),
        "lmstudio": [
            {key: model.get(key) for key in ("identifier", "contextLength", "parallel", "status")}
            for model in json.loads(_output(["lms", "ps", "--json"]) or "[]")
        ],
        "unsloth": unsloth_state(),
    }


# ---------------------------------------------------------------------------


def summary(row: dict) -> str:
    engine = row["engine_requests"] or []
    later = [request for request in engine[1:] if request.get("cached") is not None]
    if later:
        cached = sum(request["cached"] for request in later)
        total = cached + sum(request["uncached"] for request in later)
        last = later[-1]
        cache = (
            f"engine reused {cached}/{total} after the first request, "
            f"{last['cached']}/{last['cached'] + last['uncached']} on the last"
        )
    else:
        cache = "no engine log"
    speeds = [request["decode_tok_s"] for request in engine if request.get("decode_tok_s")]
    speed = f"{statistics.median(speeds):.0f} tok/s" if speeds else ""
    return f"{len(row['gateway_requests'])} requests, {cache} {speed}"


def main() -> int:
    names = [agent.name for agent in AGENTS]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--aliases", required=True, help="comma-separated aliases, run in this order")
    parser.add_argument("--agents", default=",".join(names), help=f"comma-separated, from: {', '.join(names)}")
    parser.add_argument("--effort", default=DEFAULT_EFFORT, help="thinking level for every session; 'unset' sends none")
    parser.add_argument("--out", help="JSONL file (default: cache-results/<gateway>-<time>.jsonl)")
    args = parser.parse_args()

    unknown = set(args.agents.split(",")) - set(names)
    if unknown:
        parser.error(f"unknown agent(s): {', '.join(sorted(unknown))}")
    agents = [agent for agent in AGENTS if agent.name in args.agents.split(",")]
    effort = None if args.effort == "unset" else args.effort
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else HERE / "cache-results" / f"{NAME}-{stamp}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("a", encoding="utf-8") as sink:
        sink.write(json.dumps(header(effort)) + "\n")
        for alias in args.aliases.split(","):
            for agent in agents:
                row = run_session(agent, alias, effort)
                sink.write(json.dumps(row) + "\n")
                sink.flush()
                print(f"{row['outcome'].upper():7s} {NAME:8s} {alias:24s} {agent.name:13s} {row['seconds']:7.1f}s  {summary(row)}", flush=True)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
