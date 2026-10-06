#!/bin/bash
# ============================================================
#  Build the macOS app for 图片命名压字 (Smart Name Stamp).
#  Run on a Mac:  bash build_mac.sh
#  Requires Python 3.13 with tkinter (brew install python@3.13 python-tk@3.13).
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

PY313="/opt/homebrew/opt/python@3.13/bin/python3.13"
if [[ ! -x "$PY313" ]]; then
  PY313="$(command -v python3.13 || command -v python3)"
fi

echo "=== [1/3] Build environment (.venv-build) ==="
if [[ ! -x ".venv-build/bin/python" ]]; then
  "$PY313" -m venv .venv-build
fi
.venv-build/bin/python -m pip install --upgrade pip --quiet
.venv-build/bin/pip install -r requirements-build.txt

echo "=== [2/3] PyInstaller build ==="
rm -rf build dist
.venv-build/bin/pyinstaller --noconfirm SmartNameStamp.spec

echo "=== [3/3] Zipping for distribution ==="
cd dist
# Strip the macOS quarantine attribute so it is clean before zipping.
xattr -cr "SmartNameStamp.app" 2>/dev/null || true
ditto -c -k --sequesterRsrc --keepParent "SmartNameStamp.app" "图片命名压字-Mac.zip"
cd ..

echo
echo "Done."
echo "App:  dist/SmartNameStamp.app"
echo "Send: dist/图片命名压字-Mac.zip"
