#!/bin/zsh
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_PATH="$PROJECT_DIR/smart_name_stamp.py"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"

if [[ -x "$VENV_PYTHON" ]]; then
  PYTHON_BIN="$VENV_PYTHON"
else
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [[ -z "${PYTHON_BIN:-}" || ! -x "$PYTHON_BIN" ]]; then
  echo "无法启动：没有找到可用的 Python。"
  echo "请先安装 Python，或在项目目录里创建 .venv。"
  read -r "?按回车退出..."
  exit 1
fi

if [[ ! -f "$SCRIPT_PATH" ]]; then
  echo "无法启动：找不到 smart_name_stamp.py。"
  echo "请确认启动器还在项目目录里。"
  read -r "?按回车退出..."
  exit 1
fi

normalize_path() {
  local raw="$1"
  "$PYTHON_BIN" - "$raw" <<'PY'
import os
import shlex
import sys

raw = sys.argv[1].strip()
if not raw:
    print("")
    raise SystemExit

try:
    parts = shlex.split(raw)
    path = parts[0] if parts else ""
except ValueError:
    path = raw.strip("\"'")

path = os.path.expanduser(path)
if path and not os.path.isabs(path):
    path = os.path.join(os.path.expanduser("~"), path)
print(path)
PY
}

finder_selection_path() {
  osascript <<'APPLESCRIPT' 2>/dev/null
try
  tell application "Finder"
    set selectedItems to selection
    if (count of selectedItems) is 0 then
      return ""
    end if
    return POSIX path of ((item 1 of selectedItems) as alias)
  end tell
on error
  return ""
end try
APPLESCRIPT
}

is_supported_input() {
  local path="$1"
  if [[ -d "$path" ]]; then
    return 0
  fi
  case "${path:l}" in
    *.jpg|*.jpeg|*.png|*.webp|*.bmp|*.tif|*.tiff) return 0 ;;
  esac
  return 1
}

prompt_input_path() {
  local raw path finder_path
  while true; do
    echo "请选择要处理的图片或照片文件夹：" >&2
    echo "  1. 最推荐：把图片/文件夹从 Finder 直接拖到这个窗口，然后按回车" >&2
    echo "  2. 也可以粘贴完整路径，例如：~/Pictures/待标注图片" >&2
    echo "  3. 如果你已经在 Finder 里选中了目标，直接按回车读取 Finder 当前选中项" >&2
    echo >&2
    IFS= read -r "?输入路径或拖入文件夹后按回车： " raw

    if [[ -z "$raw" ]]; then
      finder_path="$(finder_selection_path)"
      if [[ -z "$finder_path" ]]; then
        echo >&2
        echo "没有读到 Finder 当前选中项。请拖入文件夹，或粘贴路径。" >&2
        echo >&2
        continue
      fi
      path="$finder_path"
    else
      path="$(normalize_path "$raw")"
    fi

    if [[ "$path" == "$0" || "$path" == "$PROJECT_DIR/Smart Name Stamp.command" ]]; then
      echo >&2
      echo "读到的是启动器自己，不是要处理的图片或文件夹。请重新选择。" >&2
      echo >&2
      continue
    fi

    if [[ ! -e "$path" ]]; then
      echo >&2
      echo "找不到这个路径：$path" >&2
      echo >&2
      continue
    fi

    if ! is_supported_input "$path"; then
      echo >&2
      echo "这个输入不是支持的图片，也不是文件夹：$path" >&2
      echo "支持 jpg/jpeg/png/webp/bmp/tif/tiff，或包含这些图片的文件夹。" >&2
      echo >&2
      continue
    fi

    print -r -- "$path"
    return 0
  done
}

prompt_output_path() {
  local raw path default_path answer
  default_path="$HOME/Desktop/Smart Name Stamp Output $(/bin/date +%Y%m%d-%H%M%S)"

  while true; do
    echo "请选择输出文件夹：" >&2
    echo "  1. 可以把输出文件夹从 Finder 拖到这个窗口" >&2
    echo "  2. 可以粘贴路径" >&2
    echo "  3. 直接按回车使用默认输出：$default_path" >&2
    echo >&2
    IFS= read -r "?输出路径： " raw

    if [[ -z "$raw" ]]; then
      path="$default_path"
    else
      path="$(normalize_path "$raw")"
    fi

    if [[ -e "$path" && ! -d "$path" ]]; then
      echo >&2
      echo "输出路径已经存在，但不是文件夹：$path" >&2
      echo >&2
      continue
    fi

    if [[ ! -d "$path" ]]; then
      IFS= read -r "?输出文件夹不存在，是否创建？[Y/n] " answer
      case "${answer:l}" in
        ""|y|yes|是)
          mkdir -p "$path" || {
            echo >&2
            echo "创建失败：$path" >&2
            echo >&2
            continue
          }
          ;;
        *)
          echo >&2
          continue
          ;;
      esac
    fi

    print -r -- "$path"
    return 0
  done
}

prompt_style_mode() {
  local raw
  echo "请选择文字样式：" >&2
  echo "  1. 轻遮挡优先：不加半透明底，只用描边和阴影" >&2
  echo "  2. 清楚优先：复杂背景下自动加淡底" >&2
  echo >&2
  IFS= read -r "?输入 1 或 2，直接回车默认 1： " raw
  case "$raw" in
    2) echo "auto" ;;
    *) echo "never" ;;
  esac
}

clear
echo "Smart Name Stamp"
echo "图片文件名压字工具"
echo
echo "这版不使用 macOS 文件选择面板，避免出现文件夹点不动、边栏点不动的问题。"
echo

INPUT_PATH="$(prompt_input_path)"
echo
OUTPUT_PATH="$(prompt_output_path)"
echo

if [[ -d "$INPUT_PATH" ]]; then
  INPUT_GUARD="$INPUT_PATH"
else
  INPUT_GUARD="$(dirname "$INPUT_PATH")"
fi

INPUT_GUARD_REAL="$(cd "$INPUT_GUARD" && pwd)"
OUTPUT_REAL="$(cd "$OUTPUT_PATH" && pwd)"

if [[ "$INPUT_GUARD_REAL" == "$OUTPUT_REAL" ]]; then
  echo "输出文件夹不能和原图所在文件夹相同。"
  echo "请重新运行，并选择一个单独的输出文件夹，避免覆盖原图。"
  read -r "?按回车退出..."
  exit 1
fi

BACKING_MODE="$(prompt_style_mode)"
echo

if "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import cv2
PY
then
  FACE_MODE="require"
else
  FACE_MODE="auto"
fi

LOG_FILE="$OUTPUT_REAL/smart_name_stamp_run.log"
ARGS=(
  "$SCRIPT_PATH"
  "$INPUT_PATH"
  "$OUTPUT_PATH"
  "--pretty-name"
  "--overwrite"
  "--face-avoidance" "$FACE_MODE"
  "--backing" "$BACKING_MODE"
  "--contact-sheet"
)

if [[ -d "$INPUT_PATH" ]]; then
  ARGS+=("--recursive")
fi

echo "输入：$INPUT_PATH"
echo "输出：$OUTPUT_PATH"
echo "人脸避让：$FACE_MODE"
echo "文字底：$BACKING_MODE"
echo
echo "开始处理..."
echo

"$PYTHON_BIN" "${ARGS[@]}" 2>&1 | tee "$LOG_FILE"
STATUS=${pipestatus[1]}

echo
if [[ "$STATUS" -eq 0 ]]; then
  echo "处理完成。"
  echo "日志：$LOG_FILE"
  echo "总览图：$OUTPUT_REAL/_contact_sheet.jpg"
  echo
  IFS= read -r "?是否打开输出文件夹？[Y/n] " OPEN_ANSWER
  case "${OPEN_ANSWER:l}" in
    ""|y|yes|是) open "$OUTPUT_REAL" ;;
  esac
else
  echo "处理失败，请查看日志：$LOG_FILE"
  read -r "?按回车退出..."
  exit "$STATUS"
fi

echo
echo "可以关闭这个窗口了。"
