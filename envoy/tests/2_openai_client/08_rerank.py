"""Test 8 — a rerank alias puts the passage that answers the query first.

RERANK IS NOT AN OPENAI ROUTE. Cohere's shape is the common one — `query` and
`documents` in, `results` of `{index, relevance_score}` out — and settings.RERANK_URL
says where this gateway takes it. The client's own `post()` sends it, so the key and
the timeout are every other script's.

ONE SCRIPT, TWO DECLARED ANSWERS. `reranks` in settings.CONTRACT says which:
  True   the RANKING is checked: every document scored once, sorted, and the answer
         first by a wide margin.
  False  the ABSENCE is checked: the alias is not listed, and RERANK_URL answers 404
         for it. The day the gateway learns to rerank, this goes red and says to flip
         the line — an absence nobody checks is one somebody eventually assumes away.

NO `top_n` IS SENT. LiteLLM drops it on the way to TEI and returns every document
(2026-10-08), so sending it would fail on that quirk or assert nothing.

THE ALIAS IS settings.RERANK_MODEL, NOT --model: run_all.py hands every script a chat
alias. AI_GATEWAY_RERANK_MODEL overrides it.

Measured 2026-10-08, `tei-bge-reranker-m3` on LiteLLM: the answer scored 0.12 and
every other document under 0.0001.

    uv run 08_rerank.py
"""

import sys

from openai import NotFoundError

from common import CheckFailed, Gateway, check, client_for, run
from settings import RERANK_MODEL, RERANK_URL

QUERY = "How do I rotate an API key that leaked into a git repository?"
DOCUMENTS = [
    "Sourdough bread needs a long, cold fermentation before it is baked.",
    "The Danube flows through ten countries on its way to the Black Sea.",
    "Revoke the leaked key at the provider, issue a new one, and update every service that uses it.",
    "A heat pump moves heat from outside to inside instead of making it.",
]
ANSWER = 2

# The answer's score over the runner-up's. Measured above 4000; 10 leaves room for
# another cross-encoder without accepting a coin toss.
MARGIN = 10


def rerank(gateway: Gateway, model: str) -> dict:
    body = {"model": model, "query": QUERY, "documents": DOCUMENTS}
    return client_for(gateway).post(RERANK_URL, cast_to=object, body=body)


def ranking(gateway: Gateway, model: str) -> str:
    results = rerank(gateway, model).get("results") or []
    print("--- results:", [(item["index"], round(item["relevance_score"], 6)) for item in results], "---")
    check(
        sorted(item["index"] for item in results) == list(range(len(DOCUMENTS))),
        f"expected each of {len(DOCUMENTS)} documents scored once, got {results}",
    )
    scores = [item["relevance_score"] for item in results]
    check(scores == sorted(scores, reverse=True), f"the results are not sorted by relevance: {scores}")
    check(results[0]["index"] == ANSWER, f"document {results[0]['index']} ranked first, not the answer ({ANSWER})")
    check(scores[0] >= MARGIN * scores[1], f"the answer won by less than {MARGIN}x: {scores[0]:.6f} vs {scores[1]:.6f}")
    return f"the answer ranked first, {scores[0]:.4f} against {scores[1]:.6f}"


def absence(gateway: Gateway, model: str) -> str:
    if gateway.lists_models:
        listed = {item.id for item in client_for(gateway).models.list()}
        check(model not in listed, f"{model} is LISTED, so the gateway may rerank now — flip `reranks` in settings.py")
    try:
        reply = rerank(gateway, model)
    except NotFoundError:
        return f"absent as declared: {model} is not routed, and {RERANK_URL} answers 404"
    raise CheckFailed(f"{RERANK_URL} answered {reply} — the gateway reranks now; flip `reranks` in settings.py")


def scenario(gateway: Gateway, model: str) -> str:
    return ranking(gateway, model) if gateway.reranks else absence(gateway, model)


if __name__ == "__main__":
    sys.exit(run(scenario, "Test 8 — rerank: the answer first, or the declared absence", alias=RERANK_MODEL))
