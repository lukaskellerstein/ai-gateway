# TEI — the embedder and the reranker

[Text Embeddings Inference](https://github.com/huggingface/text-embeddings-inference) from
Hugging Face, serving two models to the gateways:

| Model | Port | Alias | Started by |
|:--|:--|:--|:--|
| `nomic-ai/nomic-embed-text-v1.5` | 27000 | `tei-nomic-embed` | either gateway's `up` |
| `BAAI/bge-reranker-v2-m3` | 27001 | `tei-bge-reranker-m3` | LiteLLM's `up` only |

**This folder is not a compose project.** TEI runs natively on the host, like LMStudio,
Unsloth and Ollama, because that is the only way it reaches the GPU. Its GPU backends are CUDA
and Metal, and a Podman container on a Mac gets only a Vulkan device, so TEI in compose runs
on the CPU (checked 2026-10-08). Both gateways reach it at `host.containers.internal`.

**One model per process.** TEI serves exactly one model, so the embedder and the reranker are
two processes on two ports. Both bind `127.0.0.1`.

## How it starts and stops

**`podman compose up` starts it, and `down` stops it.** Each gateway's `compose.yml` has a
service `tei` that is not a container but a *provider*: Compose runs [`tei.sh`](tei.sh) on the
Mac. `tei.sh` is the one file the two gateways share.

| You run | TEI does |
|:--|:--|
| `up` in `litellm/` | starts the embedder and the reranker, unless they already answer |
| `up` in `envoy/` | starts the embedder only — Envoy cannot route a rerank to TEI |
| `up` on a config with no TEI alias (`GATEWAY_ENGINE=lms`, …) | starts nothing, and gives up what this gateway held, as `down` would |
| `down` in either | stops each model no running gateway asked for. One started by hand is left alone |
| `restart`, `start`, a reboot | **nothing** — Compose does not call a provider then. Run `up -d` again |

`tei.sh` keeps its state in `/tmp/ai-gateway-tei/`: one pid file per model, and one file per
gateway that asked for it. Each model logs to `/tmp/ai-gateway-tei-<model>.log`.

**Run compose from inside the gateway folder.** Compose resolves `../tei/tei.sh` from where you
stand, so `podman compose -f litellm/compose.yml up` from the repo root fails on `stat
../tei/tei.sh`. If TEI fails, `up` exits 1 and says why, and the gateway starts anyway — only
the `tei-*` aliases are missing.

## Install

```bash
brew install text-embeddings-inference
```

That is all. The first `up` downloads each model into `~/.cache/huggingface/hub`: 2.3 GB for
the reranker took 651 s here, 550 MB for the embedder 91 s. `up` waits 30 s and then reports
`still loading` rather than blocking; the alias answers once the download ends.

> **`brew install` may stop with `A brew install ... process has already locked
> .../Cellar/openssl@3`**, with no other brew running. That is Homebrew's openssl@3 → openssl@4
> move locking against itself (October 2026). `brew uninstall --force openssl@4`, then
> `brew unlink openssl@3`, then install again.

## Check it

```bash
curl -fsS localhost:27000/health && curl -fsS localhost:27001/health
grep -h "model on" /tmp/ai-gateway-tei-embed.log /tmp/ai-gateway-tei-rerank.log
```

The second line must say `Metal(MetalDevice(...))`. Anything else means TEI is on the CPU.

Then through a gateway:

```bash
curl -s localhost:24000/v1/embeddings -H "Authorization: Bearer $AI_GATEWAY_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"tei-nomic-embed","input":["search_query: hello"]}'

curl -s localhost:24000/rerank -H "Authorization: Bearer $AI_GATEWAY_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"tei-bge-reranker-m3","query":"rotate a leaked key","documents":["bake bread","revoke the key and issue a new one"]}'
```

`tests/2_openai_client/07_embeddings.py` and `08_rerank.py` in either project are the same
checks, run against whichever gateway the folder names.

To change a model, edit its `model_id` in `tei.sh`, `down` and `up` the gateways, and rename the
alias in both gateways — the alias names the model.

## What to know before you call it

- **Rerank is LiteLLM only.** LiteLLM translates Cohere's `documents` to TEI's `texts` and
  back. Envoy's one rerank route cannot reach TEI, and three ways were tried —
  [`../envoy/config/tei.yaml`](../envoy/config/tei.yaml) has them. TEI issue
  [#683](https://github.com/huggingface/text-embeddings-inference/issues/683) (a compatible
  route, milestone v1.10.0) would change that.
- **`top_n` is ignored.** Through LiteLLM every document comes back, ranked. Cut the list
  yourself.
- **At most 128 documents per rerank and 2048 inputs per embedding call.** TEI's own default is
  32 and it answers `422` above that, so `tei.sh` raises it.
- **nomic wants a task prefix** — `search_query: ` or `search_document: ` — on every input. TEI
  adds none.
- **Vectors do not mix across builds.** `tei-nomic-embed` runs the safetensors weights; the
  other three nomic aliases run GGUF builds. Query an index with the alias that built it.
- **Rerank time grows with the document count, about 40 ms per 179-token document.** Measured
  2026-10-08 on an M5 Max, straight to 27001, median of 3:

  | Documents | GPU idle | GPU 84% busy (Unsloth) |
  |--:|--:|--:|
  | 1 | 31 ms | ~55 ms |
  | 20 | 0.76 s | ~1.0 s |
  | 32 | 1.28 s | ~1.5 s |
  | 128 | 5.5 s | — |
  | 20 short (8 words) | 111 ms | ~250 ms |

  It shares the GPU with the chat engines, and `--dtype float16` made no difference. Rerank the
  top 20–30 hits of a first search, not the whole index.
- **The reranker holds about 4.9 GB of memory** while it runs — which is while LiteLLM is up.
- **A crashed model stays down until the next `up -d`.** Nothing restarts it by itself.
- **TEI's docs list M1–M4 only.** It runs on the M5 Max: the log says `Starting Bert model on
  Metal`. It does not use the M5's GPU neural accelerators.
