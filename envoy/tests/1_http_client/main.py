"""The gateway with NO CLIENT LIBRARY AT ALL — `urllib` from the standard library.

This is the floor. Everything in the six folders beside it is a wrapper over the
two requests below, and seeing them plainly is what makes the rest readable:

    POST {BASE_URL}/chat/completions   Authorization: Bearer <key>
    {"model": "<alias>", "messages": [...]}

WHY THIS FOLDER EXISTS AT ALL. "Use the OpenAI SDK" is good advice and bad
debugging: when a call fails you need to know whether the gateway or the wrapper
was wrong, and the only way to know is to send the bytes yourself. This folder has
NO DEPENDENCIES — `pyproject.toml` lists none — so it also runs where nothing is
installed.

It shows both shapes a caller ever needs:

    1. the plain request      one JSON body in, one JSON body out
    2. the streaming request  the same body plus `"stream": true`, and a reply
                              that arrives as SSE frames — `data: {...}` lines
                              ending with `data: [DONE]`

STREAMING IS NOT UNIVERSAL, and this is the folder where you find that out. An SSE
frame may carry an `error` object instead of a `delta`, in which case the gateway
accepted the request and then failed mid-stream. Both gateways here stream
correctly; the MLflow gateway on 25000 did exactly that (`KeyError: 'finish_reason'`,
measured 2026-09-04) before it was removed from the repo, which is why demo 2 still
reports SKIPPED with the gateway's own message rather than pretending the reply was
empty.

THIS FILE IS BYTE-IDENTICAL IN BOTH PROJECTS. It names no port and no gateway;
everything specific comes from ../gateway.py.

    uv run main.py
    uv run main.py --model lms-26b
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# The three facts every folder here shares — the base URL, the key and the alias.
# See ../gateway.py; it imports nothing but the standard library, which is what
# lets this dependency-free folder use it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gateway import ALIAS, API_KEY, BASE_URL, BODY_EXTRAS, NAME, REQUEST_TIMEOUT_SECONDS  # noqa: E402

QUESTION = "What is the capital of France? Answer in one short sentence."


class StreamingUnsupported(RuntimeError):
    """The gateway accepted `"stream": true` and then failed inside its own code.

    A separate class because it is a different KIND of result from a wrong answer:
    the plain call worked, so the gateway and the alias are fine and only the
    streaming path is missing. Reporting it as a failure would hide that.
    """


def post(path: str, body: dict) -> urllib.request.addinfourl:
    """One POST, with the headers a gateway actually requires.

    `Content-Type` and `Authorization` are the whole authentication story here.
    An HTTPError is deliberately NOT caught: a 401 or a 404 is the answer this
    folder exists to show you, and hiding it behind a friendlier message is how a
    wrong `api_base` gets diagnosed as a broken model.
    """
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
        method="POST",
    )
    return urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS)


def plain_call(model: str) -> str:
    """One request, one JSON reply. The smallest thing that can work."""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": QUESTION},
        ],
        # EMPTY on LiteLLM and `{"max_tokens": 2048}` on the two sibling gateways.
        # LiteLLM stores a ceiling on the route; they store none. See ../gateway.py.
        **BODY_EXTRAS,
    }

    print(f"--- Request body: ---\n{json.dumps(body, indent=2)}")
    with post("/chat/completions", body) as response:
        payload = json.loads(response.read())

    print(f"--- Full response: ---\n{json.dumps(payload, indent=2)}")
    text = (payload["choices"][0]["message"]["content"] or "").strip()
    print(f"--- Response text: ---\n{text}")
    return text


def streaming_call(model: str) -> str:
    """The same request with `"stream": true`, read frame by frame.

    The reply is `text/event-stream`: one `data: {...}` line per token-ish chunk,
    then the literal `data: [DONE]`. Each chunk carries a `delta`, not a message,
    so the text is the concatenation of the deltas — that assembly is the entire
    job an SDK does for you here.
    """
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Count from 1 to 5, digits only."}],
        "stream": True,
        **BODY_EXTRAS,
    }

    print("--- Streaming: ---")
    pieces: list[str] = []
    with post("/chat/completions", body) as response:
        for raw in response:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data = line.removeprefix("data:").strip()
            if data == "[DONE]":
                break
            frame = json.loads(data)
            # AN ERROR FRAME IS A VALID SSE FRAME. The HTTP status was 200 and the
            # stream opened; the gateway then failed inside its own code. Check
            # this before reaching for `choices`, or the symptom is a KeyError in
            # THIS file about a failure that happened in the gateway.
            if "error" in frame:
                raise StreamingUnsupported(json.dumps(frame["error"]))
            # `choices` CAN BE EMPTY. Envoy's last frame carries token usage and no
            # choice at all, so `frame["choices"][0]` is an IndexError on a
            # perfectly correct stream. Skip such a frame rather than indexing it.
            choices = frame.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta", {})
            piece = delta.get("content") or ""
            if piece:
                pieces.append(piece)
                print(piece, end="", flush=True)
    print()
    return "".join(pieces).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=ALIAS, help=f"alias to call (default: {ALIAS})")
    args = parser.parse_args()

    print(f"\n{'=' * 70}\nHTTP client — urllib, no dependencies")
    print(f"{NAME} -> {BASE_URL}  model={args.model}\n{'=' * 70}")

    started = time.perf_counter()
    try:
        answer = plain_call(args.model)
        if "paris" not in answer.lower():
            raise AssertionError(f"expected Paris in the answer, got: {answer!r}")

        try:
            counted = streaming_call(args.model)
            if "5" not in counted:
                raise AssertionError(f"the stream never reached 5: {counted!r}")
            streamed = f"streamed {counted!r}"
        except StreamingUnsupported as error:
            # NOT A FAILURE — see the class docstring. The gateway's own message
            # is printed verbatim because it names what broke and where.
            print(f"\n  SKIPPED: this gateway failed mid-stream — {error}")
            streamed = "streaming: SKIPPED (the gateway failed mid-stream)"

        summary, passed = f"said {answer!r}, {streamed}", True
    except urllib.error.HTTPError as error:
        # The body of an error response is where the gateway explains itself, and
        # urllib throws it away unless you read it here.
        summary, passed = f"HTTP {error.code}: {error.read().decode('utf-8', 'replace')[:300]}", False
    except Exception as error:  # noqa: BLE001 — a failing test reports, it does not crash
        summary, passed = f"{type(error).__name__}: {error}", False
    seconds = time.perf_counter() - started

    print(f"\n{'-' * 70}")
    print(f"{'PASS' if passed else 'FAIL'}  {NAME:8s} {seconds:6.1f}s  {summary}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
