#!/bin/bash
# ============================================================
#  Build the Intel macOS app/package for 图片命名压字.
#
#  Run on this Apple Silicon Mac:
#      bash build_mac_intel.sh
#
#  Output:
#      dist-intel/SmartNameStamp.app
#      dist-intel/图片命名压字-Mac-Intel.zip
#      dist-intel/图片命名压字-Mac-Intel-带修复启动器.zip
#      dist-intel/图片命名压字-Mac-Intel.pkg
#      dist-intel/图片命名压字-Mac-Intel.dmg
#
#  Notes:
#  - This intentionally uses python*-intel64 from python.org.
#  - Do not package .venv or .venv-build from Apple Silicon; those are arm64.
# ============================================================
set -euo pipefail
export COPYFILE_DISABLE=1
cd "$(dirname "$0")"

APP_BUNDLE_ID="com.lokimao.smartnamestamp"
APP_NAME="SmartNameStamp"
DISPLAY_NAME="图片命名压字"
VERSION="1.0.0"
ARCH_X86=(/usr/bin/arch -x86_64)
REPAIR_LAUNCHER="SmartNameStamp Intel 修复启动.command"

find_intel_python() {
  local candidates=(
    "/Library/Frameworks/Python.framework/Versions/Current/bin/python3.12-intel64"
    "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12-intel64"
    "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11-intel64"
    "/Library/Frameworks/Python.framework/Versions/Current/bin/python3-intel64"
    "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3-intel64"
    "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3-intel64"
  )
  for py in "${candidates[@]}"; do
    if [[ -x "$py" ]]; then
      echo "$py"
      return 0
    fi
  done
  return 1
}

PY_INTEL="$(find_intel_python || true)"
if [[ -z "${PY_INTEL:-}" ]]; then
  echo "ERROR: 找不到 python.org 的 Intel Python。"
  echo "请安装 macOS 版 Python 3.12 universal2，或在 Intel Mac 上运行 build_mac.sh。"
  exit 1
fi

echo "=== [0/6] Intel Python ==="
echo "$PY_INTEL"
file "$PY_INTEL"
"${ARCH_X86[@]}" "$PY_INTEL" - <<'PY'
import platform
import sys

machine = platform.machine()
print("Python:", sys.version.split()[0], machine)
if machine != "x86_64":
    raise SystemExit("ERROR: 当前 Python 不是 x86_64。")
PY

echo "=== [1/6] Build environment (.venv-build-intel) ==="
if [[ ! -x ".venv-build-intel/bin/python" ]]; then
  "${ARCH_X86[@]}" "$PY_INTEL" -m venv .venv-build-intel
fi
"${ARCH_X86[@]}" .venv-build-intel/bin/python - <<'PY'
import platform

if platform.machine() != "x86_64":
    raise SystemExit("ERROR: .venv-build-intel 不是 x86_64。请删除后重试。")
PY
"${ARCH_X86[@]}" .venv-build-intel/bin/python -m pip install --upgrade pip --quiet
"${ARCH_X86[@]}" .venv-build-intel/bin/python -m pip install -r requirements-build.txt

echo "=== [2/6] PyInstaller Intel build ==="
rm -rf build-intel dist-intel
"${ARCH_X86[@]}" .venv-build-intel/bin/python -m PyInstaller \
  --noconfirm \
  --workpath build-intel \
  --distpath dist-intel \
  SmartNameStamp.spec

APP_PATH="dist-intel/${APP_NAME}.app"
BIN_PATH="${APP_PATH}/Contents/MacOS/${APP_NAME}"
if [[ ! -x "$BIN_PATH" ]]; then
  echo "ERROR: 没有生成 App 可执行文件：$BIN_PATH"
  exit 1
fi

echo "=== [3/6] Architecture check ==="
file "$BIN_PATH"
if ! file "$BIN_PATH" | grep -q "x86_64"; then
  echo "ERROR: 生成结果不是 x86_64，不能给 Intel Mac 使用。"
  exit 1
fi
xattr -cr "$APP_PATH" 2>/dev/null || true

echo "=== [4/6] Zip package ==="
chmod +x "$REPAIR_LAUNCHER" packaging/mac-intel/postinstall
cd dist-intel
ditto -c -k --norsrc --noextattr --noqtn --noacl --keepParent "${APP_NAME}.app" "${DISPLAY_NAME}-Mac-Intel.zip"
cd ..

COMBO_ROOT="build-intel/combo-root"
rm -rf "$COMBO_ROOT"
mkdir -p "$COMBO_ROOT"
ditto --norsrc --noextattr --noqtn --noacl "$APP_PATH" "$COMBO_ROOT/${APP_NAME}.app"
ditto --norsrc --noextattr --noqtn --noacl "$REPAIR_LAUNCHER" "$COMBO_ROOT/$REPAIR_LAUNCHER"
cd "$COMBO_ROOT"
ditto -c -k --norsrc --noextattr --noqtn --noacl . "../../dist-intel/${DISPLAY_NAME}-Mac-Intel-带修复启动器.zip"
cd ../..

echo "=== [5/6] Installer pkg ==="
PKG_ROOT="build-intel/pkgroot"
rm -rf "$PKG_ROOT"
mkdir -p "$PKG_ROOT/Applications"
ditto --norsrc --noextattr --noqtn --noacl "$APP_PATH" "$PKG_ROOT/Applications/${APP_NAME}.app"
xattr -cr "$PKG_ROOT" 2>/dev/null || true
pkgbuild \
  --root "$PKG_ROOT" \
  --scripts "packaging/mac-intel" \
  --install-location "/" \
  --identifier "$APP_BUNDLE_ID" \
  --version "$VERSION" \
  "dist-intel/${DISPLAY_NAME}-Mac-Intel.pkg"

echo "=== [6/6] Installer dmg ==="
DMG_ROOT="build-intel/dmgroot"
rm -rf "$DMG_ROOT"
mkdir -p "$DMG_ROOT"
ditto --norsrc --noextattr --noqtn --noacl "$APP_PATH" "$DMG_ROOT/${APP_NAME}.app"
ditto --norsrc --noextattr --noqtn --noacl "$REPAIR_LAUNCHER" "$DMG_ROOT/$REPAIR_LAUNCHER"
ln -s /Applications "$DMG_ROOT/Applications"
hdiutil create \
  -volname "${DISPLAY_NAME} Intel" \
  -srcfolder "$DMG_ROOT" \
  -ov \
  -format UDZO \
  "dist-intel/${DISPLAY_NAME}-Mac-Intel.dmg"

echo
echo "Done."
echo "App:  $APP_PATH"
echo "Zip:  dist-intel/${DISPLAY_NAME}-Mac-Intel.zip"
echo "Zip+: dist-intel/${DISPLAY_NAME}-Mac-Intel-带修复启动器.zip"
echo "Pkg:  dist-intel/${DISPLAY_NAME}-Mac-Intel.pkg"
echo "Dmg:  dist-intel/${DISPLAY_NAME}-Mac-Intel.dmg"
