#!/usr/bin/env bash
set -u

ROOT="${1:-/home/wamocon/lokal-ai-stack}"

section() {
  printf '\n## %s\n' "$1"
}

section "Host"
hostname
date

section "Stack root"
if [ -d "$ROOT" ]; then
  echo "$ROOT"
else
  echo "missing: $ROOT"
fi

section "Top-level directories"
find "$ROOT" -maxdepth 2 -type d 2>/dev/null | sort | sed "s#^$ROOT#.#" | head -160

section "Docs and compose files"
find "$ROOT" -maxdepth 5 -type f \( \
  -iname '*readme*' -o \
  -iname '*.md' -o \
  -iname 'docker-compose*.yml' -o \
  -iname 'docker-compose*.yaml' -o \
  -iname 'compose*.yml' -o \
  -iname 'compose*.yaml' -o \
  -iname '*.env.example' \
\) 2>/dev/null | sort | sed "s#^$ROOT#.#" | head -260

section "Docker compose projects"
if command -v docker >/dev/null 2>&1; then
  docker ps --format '{{.Names}}	{{.Label "com.docker.compose.project"}}	{{.Label "com.docker.compose.project.working_dir"}}' \
    | sort \
    | awk 'BEGIN { FS="\t" } { printf "%s\tproject=%s\tworkdir=%s\n", $1, $2, $3 }' \
    | head -180
else
  echo "docker not found"
fi

section "Ollama service"
if command -v systemctl >/dev/null 2>&1; then
  systemctl show ollama -p ActiveState -p SubState -p FragmentPath -p DropInPaths -p Environment 2>/dev/null || true
fi

section "Ollama models"
if command -v ollama >/dev/null 2>&1; then
  ollama ps || true
  ollama list || true
else
  echo "ollama CLI not found"
fi

section "Key listeners"
if command -v ss >/dev/null 2>&1; then
  ss -ltnp 2>/dev/null | grep -E ':(11434|8188|8117|5678|4000|4007|4019|4020|3030|5000|9000|9001)\b' || true
else
  echo "ss not found"
fi
