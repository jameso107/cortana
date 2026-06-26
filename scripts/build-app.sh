#!/usr/bin/env bash
# Build Cortana.app — run from repo root
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "→ Building React UI…"
cd "$ROOT/ui"
npm run build

echo "→ Installing Electron deps…"
cd "$ROOT/electron"
npm install

echo "→ Packaging .app / .dmg…"
npm run build

echo ""
echo "✓ Done. Find your app in electron/dist/"
ls -lh "$ROOT/electron/dist/" 2>/dev/null || true
