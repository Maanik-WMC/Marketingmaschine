#!/usr/bin/env bash
set -u

section() {
  printf '\n## %s\n' "$1"
}

section "Host"
hostname
date
uname -a

section "RAM and swap"
free -h

section "Memory details"
awk '/MemTotal|MemAvailable|SwapTotal|SwapFree|SwapCached|Cached|Buffers|SReclaimable|Shmem/ { print }' /proc/meminfo

section "GPU query"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits || nvidia-smi
else
  echo "nvidia-smi not found"
fi

section "Top processes by resident memory"
ps -eo pid,ppid,comm,rss,%mem --sort=-rss | head -40

section "Ollama and llama processes"
ps -eo pid,ppid,comm,rss,%mem --sort=-rss | grep -E 'ollama|llama-server' | grep -v grep || true

section "Ollama loaded models"
if command -v ollama >/dev/null 2>&1; then
  ollama ps || true
else
  echo "ollama CLI not found"
fi

section "Docker stats"
if command -v docker >/dev/null 2>&1; then
  docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}' | head -100
else
  echo "docker not found"
fi

section "Docker memory summary"
if command -v docker >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
  docker stats --no-stream --format '{{.Name}}	{{.MemUsage}}' | python3 -c '
import re
import sys

def mib(raw: str) -> float:
    left = raw.split("/", 1)[0].strip()
    match = re.match(r"([0-9.]+)\s*([KMGT]?i?B)", left)
    if not match:
        return 0.0
    value = float(match.group(1))
    unit = match.group(2)
    factors = {
        "B": 1 / (1024 * 1024),
        "KiB": 1 / 1024,
        "MiB": 1,
        "GiB": 1024,
        "TiB": 1024 * 1024,
        "KB": 1 / 1024,
        "MB": 1,
        "GB": 1024,
        "TB": 1024 * 1024,
    }
    return value * factors.get(unit, 0.0)

rows = []
for line in sys.stdin:
    line = line.rstrip("\n")
    if "\t" not in line:
        continue
    name, usage = line.split("\t", 1)
    rows.append((name, mib(usage)))

total = sum(value for _, value in rows)
print(f"docker_container_count={len(rows)}")
print(f"docker_total_mib={total:.1f}")
print(f"docker_total_gib={total / 1024:.2f}")
for name, value in sorted(rows, key=lambda item: item[1], reverse=True)[:20]:
    print(f"{value / 1024:.2f} GiB\t{name}")
'
fi

section "Process memory summary"
if command -v python3 >/dev/null 2>&1; then
  ps -eo rss,comm --no-headers | python3 -c '
import sys
from collections import defaultdict

groups = defaultdict(int)
total = 0
for line in sys.stdin:
    parts = line.strip().split(None, 1)
    if len(parts) != 2:
        continue
    rss = int(parts[0])
    comm = parts[1]
    total += rss
    lower = comm.lower()
    if lower in {"llama-server", "ollama"}:
        key = "ollama_and_loaded_models"
    elif lower in {"docker", "dockerd", "containerd"}:
        key = "docker_engine"
    elif lower in {"node", "mainthread", "codex", "kimi code", "code"}:
        key = "vscode_codex_node_apps"
    elif "firefox" in lower or "web content" in lower or "isolated web" in lower:
        key = "browser"
    elif lower in {"python", "python3", "python3.12", "uvicorn"}:
        key = "python_apps"
    elif lower in {"java"}:
        key = "java_apps"
    elif "gnome" in lower or lower in {"xorg", "mutter-x11-fram"}:
        key = "desktop"
    else:
        key = "other_processes"
    groups[key] += rss

print(f"process_rss_total_gib={total / 1024 / 1024:.2f}")
for key, rss in sorted(groups.items(), key=lambda item: item[1], reverse=True):
    print(f"{rss / 1024 / 1024:.2f} GiB\t{key}")
'
fi

section "Marketing agent container"
if command -v docker >/dev/null 2>&1; then
  docker stats --no-stream --format '{{.Name}}	{{.MemUsage}}	{{.MemPerc}}	{{.CPUPerc}}' wmc-marketing-agent 2>/dev/null || true
  docker inspect --format '{{.Name}} memory_limit={{.HostConfig.Memory}} nano_cpus={{.HostConfig.NanoCpus}} restart={{.HostConfig.RestartPolicy.Name}}' wmc-marketing-agent 2>/dev/null || true
fi

section "Docker container count"
if command -v docker >/dev/null 2>&1; then
  docker ps --format '{{.Names}}' | wc -l
fi

section "High-speed links"
for iface in enp1s0f0np0 enp1s0f1np1 enP2p1s0f0np0 enP2p1s0f1np1; do
  if [ -e "/sys/class/net/$iface" ]; then
    echo "-- $iface --"
    ip -br addr show dev "$iface" || true
    printf 'speed_mbps='
    cat "/sys/class/net/$iface/speed" 2>/dev/null || echo unknown
    printf 'carrier='
    cat "/sys/class/net/$iface/carrier" 2>/dev/null || echo unknown
    printf 'operstate='
    cat "/sys/class/net/$iface/operstate" 2>/dev/null || echo unknown
  fi
done

section "Disk"
df -h / /home 2>/dev/null || df -h
