"""Test 7 — an embedding alias returns one vector per input, and the vectors mean something.

A 200 with vectors is not enough: a route answering with the wrong model's vectors,
or with noise, passes a shape check. So the question is semantic — the query must
land nearer the passage that answers it than the passage that does not.

THE ALIAS IS settings.EMBED_MODEL, NOT --model: run_all.py hands every script a chat
alias, and a chat alias embeds nothing. AI_GATEWAY_EMBED_MODEL overrides it.

NOMIC WANTS A TASK PREFIX on every input — `search_query: ` or `search_document: ` —
and no engine adds one, so the inputs below carry it. Other embedders ignore it.

NOTHING FROM body_extras GOES ALONG: a ceiling and a thinking level are chat fields,
and Envoy would pass them straight to an embedder that has neither.

Measured 2026-10-08, `tei-nomic-embed`, both gateways: 768 dimensions.

    uv run 07_embeddings.py
"""

import math
import sys

from common import Gateway, check, client_for, run
from settings import EMBED_MODEL

QUERY = "search_query: How do I rotate an API key that leaked into git?"
ANSWER = "search_document: Revoke the leaked key at the provider, issue a new one, and update every service that uses it."
UNRELATED = "search_document: Sourdough bread needs a long, cold fermentation before it is baked."


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def scenario(gateway: Gateway, model: str) -> str:
    response = client_for(gateway).embeddings.create(model=model, input=[QUERY, ANSWER, UNRELATED])
    vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
    check(len(vectors) == 3, f"3 inputs went in and {len(vectors)} vectors came back")
    size = len(vectors[0])
    check(size > 0 and all(len(vector) == size for vector in vectors), "the vectors are empty or differ in length")

    near, far = cosine(vectors[0], vectors[1]), cosine(vectors[0], vectors[2])
    print(f"--- {size} dims; cosine(query, answer)={near:.4f}, cosine(query, unrelated)={far:.4f} ---")
    check(near > far, f"the query landed nearer the unrelated passage ({far:.4f}) than the answer ({near:.4f})")
    return f"{size} dims, the answer nearer than the unrelated passage ({near:.3f} > {far:.3f})"


if __name__ == "__main__":
    sys.exit(run(scenario, "Test 7 — embeddings: one vector per input, and they mean something", alias=EMBED_MODEL))
