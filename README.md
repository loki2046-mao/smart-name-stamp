# Smart Name Stamp

把一批图片的文件名自动压到图片上。脚本会先分析每张图，尽量把文字放到背景更干净、视觉重要性更低的位置，并根据局部明暗自动选择深色或浅色文字。

默认字体是仓库内置的 `assets/fonts/NotoSansCJKsc-Regular.otf`，来自 Noto CJK / 思源黑体系，许可证是 SIL Open Font License 1.1，适合中英文文件名。

## 开源与下载

源码采用 MIT 许可证，可自行使用、修改和分发；内置 Noto CJK 字体沿用 SIL OFL 1.1。

- 源码：https://github.com/loki2046-mao/smart-name-stamp
- 安装包：https://github.com/loki2046-mao/smart-name-stamp/releases/latest
- 当前提供 macOS Apple Silicon（M 系列）安装包，Intel / Windows 请按说明从源码运行或自行打包；这些平台尚未完成本次版本安装验收。
- 有帮助欢迎 Star，也欢迎提 Issue 或 Pull Request。

这是本地图片处理工具，运行时不调用 AI 模型，也不上传图片。自动选位不保证避开所有主体，导出前请预览；单图设置当前仅在本次会话中保存。

## 从源码运行

```bash
git clone https://github.com/loki2046-mao/smart-name-stamp.git
cd smart-name-stamp
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-full.txt
python smart_name_stamp_gui.py
```

需要 Python 3.10+ 和 tkinter。macOS 若 Python 不含 tkinter，可安装匹配版本的 python-tk；Linux 常需系统包 python3-tk。命令行核心不依赖 tkinter。

## 快速使用

```bash
python3 smart_name_stamp.py ./images ./output --recursive --pretty-name
```

## 双击运行的图形界面 App（推荐）

普通用户直接用打包好的桌面 App，不用碰命令行：

- 图形界面代码：`smart_name_stamp_gui.py`（基于 tkinter，调用本仓库的核心引擎）。
- 打包配置：`SmartNameStamp.spec`（Mac / Windows 通用）。
- 打包脚本：`build_mac.sh`（Mac）、`build_windows.bat`（Windows）。
- 终端用户说明：`使用说明.txt`（含 Mac 首次打开、Windows 首次打开步骤）。

打包出 Mac 版：

```bash
bash build_mac.sh
# 产物：dist/SmartNameStamp.app 和 dist/图片命名压字-Mac.zip
```

打包出 Intel 芯片 Mac 版：

```bash
bash build_mac_intel.sh
# 产物：dist-intel/图片命名压字-Mac-Intel.pkg 和 dist-intel/图片命名压字-Mac-Intel.zip
```

注意：Apple Silicon 上普通 `build_mac.sh` 打出来的是 `arm64`，不要发给 Intel Mac。Intel Mac 优先发 `.pkg`，双击安装后会放到 `/Applications/SmartNameStamp.app`。

打包出 Windows 版（必须在 Windows 电脑上执行，Mac 无法交叉编译）：

```text
双击运行 build_windows.bat
# 产物：dist\SmartNameStamp\（整个文件夹打 zip 发给别人）
```

App 双击打开后：① 选单张图片或整个文件夹 → ② 选输出文件夹 → ③ 选项（美化文件名、文字底）→ 点“开始处理”，完成后自动打开输出文件夹。开源思源黑体、人脸避让、深浅字自适应、描边/阴影都已内置打包，对方解压即用，无需安装 Python。

> 注：仓库里还保留了旧的终端启动器 `Smart Name Stamp.command`，作为不打包时的命令行备用入口；普通分发请用上面的 App。

## 命令行用法

常用参数：

```bash
python3 smart_name_stamp.py ./images ./output \
  --recursive \
  --pretty-name \
  --placement edge \
  --backing auto \
  --overwrite
```

输出目录里会生成处理后的图片和 `caption_report.json`，报告包含每张图片的文字位置、颜色、评分、人脸检测状态和错误原因。

## 依赖

本机当前已经有 `Pillow` 和 `numpy` 时可以直接运行。干净环境可安装：

```bash
python3 -m pip install -r requirements.txt
```

如果希望显式做人脸避让，安装完整依赖：

```bash
python3 -m pip install -r requirements-full.txt
```

然后运行：

```bash
python3 smart_name_stamp.py ./images ./output --face-avoidance require
```

没有 OpenCV 时，默认 `--face-avoidance auto` 会降级为“显著性/边缘/纹理避让”：它会避开更像主体或信息密集的区域，但不会声称已经做了真正的人脸检测。这个状态会写进报告。

## 判断逻辑

- 文字内容：默认使用文件名去掉扩展名后的部分，比如 `春日海边.png` 会写入 `春日海边`。
- 位置：在边缘、角落和视觉上自然的位置中打分，优先选择低纹理、低边缘、低显著性的区域。
- 颜色：分析文字落点区域的亮度。浅底用深字，深底用浅字，并加轻微描边/阴影。
- 背景：默认只在局部过于复杂时加一层很淡的半透明底，避免文字糊在画面里。
- 人脸：安装 OpenCV 后使用开源 Haar cascade 检测并扩大避让框；没有 OpenCV 时自动降级。

## 单张图片

```bash
python3 smart_name_stamp.py ./input/photo.jpg ./output/photo.jpg
```

## 不改变文件名文字

默认保留原始 stem。比如 `my_image_01.png` 会写 `my_image_01`。如果想把下划线变空格：

```bash
python3 smart_name_stamp.py ./images ./output --pretty-name
```

如果想连扩展名一起写上去：

```bash
python3 smart_name_stamp.py ./images ./output --include-extension
```

## 先只分析不出图

```bash
python3 smart_name_stamp.py ./images ./output --dry-run
```

这会只生成 `caption_report.json`，方便先看每张图会被放到哪里。

## 生成总览图

```bash
python3 smart_name_stamp.py ./images ./output --recursive --contact-sheet
```

总览图会保存为：

```text
./output/_contact_sheet.jpg
```

## 精细控制版

桌面界面支持自动选位或六种固定位置、相对字号、边距、文字最大宽度、最多行数、自动/黑/白文字、底色模式与透明度、字体选择、扩展名开关。点击「预览第一张」检查效果后再批量导出。固定位置遵循指定位置，可能遮挡主体；自动避让只是图像分析与人脸检测，不保证识别所有主体。

默认跳过已有输出；输出位于输入目录内部时，不会重新处理输出目录。每批保存 caption_report.json。支持逐张预览、拖动文字位置和单图独立设置，操作见下节。

### 逐张微调

点击「逐张预览与微调」打开图片列表，选择任意图片修改文字，按住文字并在目标位置松开以调整位置，点击「保存本张设置」。主窗口更改字号、字体等选项后，可以点击「使用主窗口样式」应用到本张，再保存。未保存的调整不参与导出；逐张设置仅在本次打开的工具会话中保留。重新生成已有输出需勾选覆盖同名文件。

## 作者与相关作品

由[赛博小熊猫 Loki](https://hiloki.ai/about)制作与维护。用 AI 做产品、做内容，把真实制作中的修改、取舍和方法留下来。

[个人网站](https://hiloki.ai/) · [作品与制作记录](https://hiloki.ai/works) · [公众号文章](https://hiloki.ai/articles/) · [GitHub](https://github.com/loki2046-mao)
