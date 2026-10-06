#!/bin/zsh
set -u

LOG="$HOME/Desktop/SmartNameStamp-intel-startup.log"
APP_NAME="SmartNameStamp.app"

{
  echo "=== SmartNameStamp Intel startup repair ==="
  date
  echo "User: $(id)"
  echo "macOS: $(sw_vers -productVersion 2>/dev/null || true)"
  echo "Machine: $(uname -m)"
  echo
} > "$LOG"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

find_app() {
  local candidates=(
    "$SCRIPT_DIR/$APP_NAME"
    "/Applications/$APP_NAME"
    "$HOME/Applications/$APP_NAME"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -d "$candidate" ]]; then
      print -r -- "$candidate"
      return 0
    fi
  done
  return 1
}

APP_PATH="$(find_app || true)"
if [[ -z "${APP_PATH:-}" ]]; then
  echo "没有找到 SmartNameStamp.app。" | tee -a "$LOG"
  echo "请把这个修复启动器和 SmartNameStamp.app 放在同一个文件夹，或先把 App 拖到 Applications。" | tee -a "$LOG"
  echo
  read -r "?按回车退出..."
  exit 1
fi

BIN_PATH="$APP_PATH/Contents/MacOS/SmartNameStamp"

echo "App: $APP_PATH" | tee -a "$LOG"
echo "Binary: $BIN_PATH" | tee -a "$LOG"
echo | tee -a "$LOG"

echo "[1/5] 修复权限..." | tee -a "$LOG"
chmod -R u+rwX,go+rX "$APP_PATH" >> "$LOG" 2>&1 || true
chmod +x "$BIN_PATH" >> "$LOG" 2>&1 || true

echo "[2/5] 移除 quarantine / 扩展属性..." | tee -a "$LOG"
xattr -dr com.apple.quarantine "$APP_PATH" >> "$LOG" 2>&1 || true
xattr -cr "$APP_PATH" >> "$LOG" 2>&1 || true

echo "[3/5] 本机重新签名..." | tee -a "$LOG"
codesign --force --deep --sign - "$APP_PATH" >> "$LOG" 2>&1 || true

echo "[4/5] 检查架构和签名..." | tee -a "$LOG"
file "$BIN_PATH" >> "$LOG" 2>&1 || true
lipo -archs "$BIN_PATH" >> "$LOG" 2>&1 || true
codesign --verify --deep --strict --verbose=1 "$APP_PATH" >> "$LOG" 2>&1 || true
spctl --assess --type execute --verbose=4 "$APP_PATH" >> "$LOG" 2>&1 || true

echo "[5/5] 尝试启动..." | tee -a "$LOG"
open "$APP_PATH" >> "$LOG" 2>&1
OPEN_STATUS=$?

if [[ "$OPEN_STATUS" -ne 0 ]]; then
  echo "Finder 启动失败，改为直接运行可执行文件。错误码：$OPEN_STATUS" | tee -a "$LOG"
  "$BIN_PATH" >> "$LOG" 2>&1
  RUN_STATUS=$?
  echo "直接运行退出码：$RUN_STATUS" | tee -a "$LOG"
else
  echo "已发起启动。如果 App 仍没有窗口，请查看这个日志：$LOG" | tee -a "$LOG"
fi

echo
echo "日志已写到：$LOG"
echo "如果还是打不开，把这个日志发回来，我就能看到真实错误。"
read -r "?按回车退出..."
