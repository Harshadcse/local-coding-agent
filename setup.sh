#!/usr/bin/env bash
# One-time setup: Python venv + deps, Ollama models, VS Code extension build.
# Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

step "Python virtual environment"
PY=$(command -v python3.12 || command -v python3.13 || command -v python3.14 || command -v python3)
"$PY" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
[ -d venv ] || "$PY" -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt
echo "ok: $(./venv/bin/python --version)"

step "Ollama models"
if command -v ollama >/dev/null; then
  if ! ollama list >/dev/null 2>&1; then
    echo "Ollama is installed but not running. Start the Ollama app (or 'ollama serve'), then re-run ./setup.sh"
    exit 1
  fi
  ollama pull nomic-embed-text      # embeddings (~270 MB)
  ollama pull qwen2.5-coder:7b      # chat/code model (~4.7 GB)
else
  echo "Ollama not found. Install it from https://ollama.com/download, then re-run ./setup.sh"
  exit 1
fi

step "VS Code extension"
if command -v npm >/dev/null; then
  (cd vscode-extension && npm install --silent && npm run -s compile \
     && npx --yes @vscode/vsce package --allow-missing-repository --skip-license >/dev/null)
  echo "ok: $(ls vscode-extension/*.vsix)"
else
  echo "npm not found: skip building. Download the .vsix from the GitHub Releases page instead."
fi

step "Demo app (optional, needs Flutter)"
if command -v flutter >/dev/null; then
  (cd examples/demo_app && flutter pub get >/dev/null) && echo "ok: demo_app dependencies"
else
  echo "Flutter not on PATH: the demo app still works for Ask/Review; the analyzer check needs Flutter."
  echo "If Flutter is installed elsewhere: export AGENT_TOOL_PATHS=/path/to/flutter/bin"
fi

cat <<'MSG'

Done. Next:
  1. VS Code: Extensions -> ... -> Install from VSIX -> vscode-extension/local-coding-agent-*.vsix
  2. Open examples/demo_app in VS Code, open the Local Agent chat (robot icon), click Start
  3. Follow docs/DEMO.md
MSG
