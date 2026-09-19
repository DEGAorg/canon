#!/usr/bin/env bash
set -euo pipefail

uv tool install "${PWD}" --force --reinstall
if ! command -v canon >/dev/null 2>&1; then
  echo "Add $(uv tool dir --bin) to PATH, then run canon ."
  exit 1
fi
canon --version
command -v canon-ctl >/dev/null
printf 'Canon installed. Follow INSTALL.md for wallet and configuration setup.\n'
