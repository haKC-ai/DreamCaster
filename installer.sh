#!/usr/bin/env bash
set -euo pipefail
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel
pip install -r requirements.txt
cp -n .env.example .env || true
echo "Setup complete. Edit .env and run: source .venv/bin/activate && python -m app.main"