#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "${script_dir}"

uv tool install "${PWD}" --force --reinstall
tool_root="$(uv tool dir)"
"${tool_root}/canon-app/bin/python" -m toad.cardano_install
if ! command -v canon >/dev/null 2>&1; then
  echo "Add $(uv tool dir --bin) to PATH, then run canon ."
  exit 1
fi
canon --version
command -v canon-ctl >/dev/null
printf 'Canon installed. Follow INSTALL.md for wallet and configuration setup.\n'
