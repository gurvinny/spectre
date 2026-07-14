#!/usr/bin/env bash
# SPECTRE — first-run bootstrap
# Author: gurvinny
#
# Idempotent: safe to run repeatedly. Creates .env from the template,
# generates the secret, and prompts for the host IP. Never clobbers an
# existing .env.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

say()  { printf '\033[36m[spectre]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[spectre]\033[0m %s\n' "$*"; }
die()  { printf '\033[31m[spectre]\033[0m %s\n' "$*" >&2; exit 1; }

# ── Dependency checks ─────────────────────────────────────────────────
command -v docker  >/dev/null 2>&1 || die "docker not found."
docker compose version >/dev/null 2>&1 || die "docker compose (v2) not found."
command -v openssl >/dev/null 2>&1 || die "openssl not found (needed to generate the secret)."

# ── .env ──────────────────────────────────────────────────────────────
if [[ -f .env ]]; then
  say ".env already exists — leaving it untouched."
else
  say "Creating .env from .env.example ..."
  cp .env.example .env

  secret="$(openssl rand -hex 32)"
  # Portable in-place sed (GNU + BSD).
  sed -i.bak "s|^SPECTRE_SECRET=.*|SPECTRE_SECRET=${secret}|" .env && rm -f .env.bak
  say "Generated SPECTRE_SECRET."

  default_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  default_ip="${default_ip:-10.0.0.10}"
  read -rp "$(printf '\033[36m[spectre]\033[0m Host LAN IP for the web UI [%s]: ' "$default_ip")" host_ip
  host_ip="${host_ip:-$default_ip}"
  sed -i.bak \
    -e "s|^HOST_IP=.*|HOST_IP=${host_ip}|" \
    -e "s|^NEXT_PUBLIC_API_BASE=.*|NEXT_PUBLIC_API_BASE=http://${host_ip}:8100|" \
    .env && rm -f .env.bak
  say "Set HOST_IP=${host_ip}."
fi

# ── Serial device sanity check ────────────────────────────────────────
for dev in /dev/ttyUSB0 /dev/ttyUSB1; do
  if [[ -e "$dev" ]]; then
    say "Found serial device $dev."
  else
    warn "Serial device $dev not present — plug in the board or edit SERIAL_PORTS / SPECTRE_SOURCE=sim."
  fi
done

say "Bootstrap complete. Next:"
say "  docker compose up -d --build"
say "  then open the web UI and finish the setup wizard."
