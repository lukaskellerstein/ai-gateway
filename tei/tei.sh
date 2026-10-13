#!/bin/sh
# TEI — Hugging Face Text Embeddings Inference — started and stopped by `podman compose`.
#
# WHY A SCRIPT AND NOT A CONTAINER: TEI reaches the GPU only through Metal or CUDA, and a
# Podman container on this Mac gets a Vulkan device and nothing else, so TEI in compose runs
# on the CPU (checked 2026-10-08). It runs natively on the host, like LMStudio, Unsloth and
# Ollama — and unlike them, nothing else starts it. This script does.
#
# HOW IT IS CALLED: each gateway's compose.yml declares a service `tei` with
# `provider: {type: ../tei/tei.sh}`. Compose — Docker Compose v5.3.1 behind `podman
# compose` — runs it ON THE HOST, from the folder you stand in (measured 2026-10-08):
#
#   ../tei/tei.sh compose metadata
#   ../tei/tei.sh compose --project-name=ai-gateway up   --engine=all --models=embed,rerank tei
#   ../tei/tei.sh compose --project-name=ai-gateway down --engine=all --models=embed,rerank tei
#
# THE PATH IS RELATIVE TO WHERE YOU STAND, not to compose.yml: `-f litellm/compose.yml`
# from the repo root fails with `stat ../tei/tei.sh: no such file`. Run compose from inside
# the gateway folder, as everything here already does.
#
# THIS IS THE ONE FILE THE TWO GATEWAYS SHARE (the user's choice, 2026-10-08): the start
# flags live here once. What differs is data in each compose.yml — LiteLLM asks for
# `embed,rerank`, Envoy for `embed` alone, because it cannot route a rerank to TEI.
#
#   up    a config that names no TEI alias starts nothing and releases what this gateway held,
#         so GATEWAY_ENGINE=lms never pays for TEI. Otherwise each model is started unless its
#         port already answers, and this gateway is recorded as one of its users.
#   down  this gateway is forgotten, and each model left with no user is stopped — but only
#         a model this script started. One started by hand is left alone.
#
# NOT CALLED by `compose restart`, `compose start`, or a container coming back on its
# restart policy after a reboot (measured 2026-10-08). The gateway is back and TEI is not;
# `podman compose up -d` again starts it, and repeating it is harmless.
#
# A FAILURE HERE MAKES `up` EXIT 1 BUT DOES NOT STOP THE GATEWAY: no service depends on
# `tei`, so the container starts anyway (measured). Loud, and nothing else breaks.
#
# STDOUT BELONGS TO COMPOSE: one JSON object per line, {"type":"info|error","message":…}.
# An unknown type fails the command, so everything else goes to a log file.

set -u

STATE=/tmp/ai-gateway-tei   # pid files and users; macOS empties /tmp at boot, as a reboot ends TEI
WAIT_S=30                   # a cached model answers in seconds; a first start downloads it —
                            # 2.3 GB for the reranker took 651 s — and `up` does not wait for that

# One model per TEI process, so one port per model.
#   embed   2048 inputs per call: OpenAI's own limit, and LangChain sends 1000 by default
#   rerank  128 documents per call. TEI's default is 32 and it answers 422 above it
model_id() {
  case "$1" in
    embed) echo nomic-ai/nomic-embed-text-v1.5 ;;
    rerank) echo BAAI/bge-reranker-v2-m3 ;;
  esac
}
model_port() {
  case "$1" in
    embed) echo 27000 ;;
    rerank) echo 27001 ;;
  esac
}
model_batch() {
  case "$1" in
    embed) echo 2048 ;;
    rerank) echo 128 ;;
  esac
}

say() { printf '{"type":"%s","message":"%s"}\n' "$1" "$2"; }

answers() { curl -fsS -m 2 "http://127.0.0.1:$(model_port "$1")/health" > /dev/null 2>&1; }

# True only for a pid this script recorded that is still TEI, so a reused pid is never killed.
started_here() {
  [ -f "$STATE/$1.pid" ] && ps -p "$(cat "$STATE/$1.pid")" -o comm= 2> /dev/null | grep -q text-embeddings
}

start() {
  model=$1
  log=/tmp/ai-gateway-tei-$model.log
  if answers "$model" || started_here "$model"; then
    say info "$model: already running on $(model_port "$model")"
    return 0
  fi
  if ! bin=$(command -v text-embeddings-router); then
    say error "TEI is not installed: brew install text-embeddings-inference"
    return 1
  fi
  nohup "$bin" --model-id "$(model_id "$model")" --hostname 127.0.0.1 --port "$(model_port "$model")" \
    --max-client-batch-size "$(model_batch "$model")" > "$log" 2>&1 < /dev/null &
  echo $! > "$STATE/$model.pid"
  waited=0
  while [ "$waited" -lt "$WAIT_S" ]; do
    if answers "$model"; then
      say info "$model: ready on $(model_port "$model")"
      return 0
    fi
    if ! started_here "$model"; then
      rm -f "$STATE/$model.pid"
      say error "$model: TEI exited while starting, see $log"
      return 1
    fi
    sleep 1
    waited=$((waited + 1))
  done
  say info "$model: still loading after ${WAIT_S} s (a first start downloads the model), see $log"
}

stop() {
  model=$1
  users=$(ls "$STATE/$model.users" 2> /dev/null | tr '\n' ' ')
  if [ -n "$users" ]; then
    say info "$model: kept, still used by $users"
    return 0
  fi
  if ! started_here "$model"; then
    rm -f "$STATE/$model.pid"
    if answers "$model"; then
      say info "$model: not started by a gateway, left alone"
    else
      say info "$model: not running"
    fi
    return 0
  fi
  pid=$(cat "$STATE/$model.pid")
  kill "$pid"
  waited=0
  while kill -0 "$pid" 2> /dev/null && [ "$waited" -lt 10 ]; do
    sleep 1
    waited=$((waited + 1))
  done
  rm -f "$STATE/$model.pid"
  say info "$model: stopped, no gateway uses it"
}

action='' project='' engine='' models=''
for arg in "$@"; do
  case "$arg" in
    up | down) action=$arg ;;
    --project-name=*) project=${arg#*=} ;;
    --engine=*) engine=${arg#*=} ;;
    --models=*) models=$(echo "${arg#*=}" | tr ',' ' ') ;;
  esac
done

# `compose metadata` and anything else Compose may add: nothing to declare, nothing to do.
[ -n "$action" ] || exit 0

for model in $models; do
  if [ -z "$(model_port "$model")" ]; then
    say error "unknown TEI model in compose.yml: $model (known: embed, rerank)"
    exit 1
  fi
done

release() {
  for model in $models; do
    rm -f "$STATE/$model.users/$project"
    stop "$model"
  done
}

mkdir -p "$STATE"
status=0
if [ "$action" = down ]; then
  release
  exit 0
fi
# The engine word names config/<word>.yaml in the folder you stand in. A TEI alias or an
# `include: tei.yaml` there is what says this gateway serves TEI at all — in the YAML, not in
# a comment: unsloth.yaml's comments point callers at `tei-nomic-embed`, and matching those
# kept TEI up for a gateway on `unsloth` (measured 2026-10-08). A gateway brought up again on
# a config without one — `all` to `lms` — gives TEI up exactly as `down` would.
if ! sed 's/#.*//' "config/$engine.yaml" 2> /dev/null | grep -qE '(^|[^a-z])tei[-.]'; then
  say info "config/$engine.yaml serves no TEI alias, nothing started"
  release
  exit 0
fi
for model in $models; do
  mkdir -p "$STATE/$model.users"
  touch "$STATE/$model.users/$project"
  start "$model" || status=1
done
exit "$status"
