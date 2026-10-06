#!/usr/bin/env python3
"""Simple desktop GUI for Smart Name Stamp.

Pick a single image or a whole folder, pick an output folder, press the button.
The heavy lifting lives in smart_name_stamp.py; this file is only the window.
"""

from __future__ import annotations

from dataclasses import replace
import json
import queue
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from smart_name_stamp import (
    DEFAULT_FONT_PATH,
    SUPPORTED_EXTENSIONS,
    Settings,
    iter_images,
    make_contact_sheet,
    output_path_for,
    stamp_one,
    caption_text_for, fit_text_layout, choose_placement, draw_caption,
)

APP_TITLE = "图片命名压字工具"
IMAGE_PATTERNS = [
    ("图片文件", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff"),
    ("所有文件", "*.*"),
]


def open_in_file_manager(path: Path) -> None:
    """Reveal a folder in Finder / Explorer / file manager, best effort."""
    import subprocess
    import sys

    try:
        if sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        elif sys.platform.startswith("win"):
            import os

            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception:
        pass


class StampApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.input_path: Path | None = None
        self.output_path: Path | None = None
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.worker: threading.Thread | None = None

        root.title(APP_TITLE)
        root.minsize(760, 780)

        self.pretty_var = tk.BooleanVar(value=True)
        self.recursive_var = tk.BooleanVar(value=True)
        self.backing_var = tk.StringVar(value="auto")

        self.position_var = tk.StringVar(value="自动避让（边缘）")
        self.color_var = tk.StringVar(value="自动")
        self.size_var = tk.DoubleVar(value=5.2)
        self.margin_var = tk.DoubleVar(value=3.5)
        self.width_var = tk.DoubleVar(value=42)
        self.opacity_var = tk.DoubleVar(value=32)
        self.lines_var = tk.IntVar(value=2)
        self.extension_var = tk.BooleanVar(value=False)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.overrides = {}
        self.font_path = DEFAULT_FONT_PATH
        self._build_ui()
        self.root.after(120, self._drain_events)

    # ---------- UI construction ----------
    def _build_ui(self) -> None:
        pad = {"padx": 14, "pady": 6}
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)

        title = ttk.Label(main, text=APP_TITLE, font=("Helvetica", 18, "bold"))
        title.grid(row=0, column=0, sticky="w")
        subtitle = ttk.Label(
            main,
            text="把每张图片的文件名，自动压到画面干净、尽量避开人脸和复杂区域；可以预览并手动指定位置。",
            foreground="#555555",
        )
        subtitle.grid(row=1, column=0, sticky="w", pady=(2, 12))

        # Step 1: input
        in_frame = ttk.LabelFrame(main, text="① 选择要处理的图片", padding=12)
        in_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        in_frame.columnconfigure(0, weight=1)
        self.input_label = ttk.Label(
            in_frame, text="还没有选择", foreground="#888888", anchor="w"
        )
        self.input_label.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Button(in_frame, text="选择单张图片", command=self._pick_image).grid(
            row=1, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Button(in_frame, text="选择整个文件夹", command=self._pick_folder).grid(
            row=1, column=1, sticky="ew", padx=(6, 0)
        )
        in_frame.columnconfigure(0, weight=1)
        in_frame.columnconfigure(1, weight=1)
        self.recursive_check = ttk.Checkbutton(
            in_frame,
            text="包含子文件夹里的图片",
            variable=self.recursive_var,
        )
        self.recursive_check.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        # Step 2: output
        out_frame = ttk.LabelFrame(
            main, text="② 选择输出文件夹（不能和原图在同一个文件夹）", padding=12
        )
        out_frame.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        out_frame.columnconfigure(0, weight=1)
        self.output_label = ttk.Label(
            out_frame, text="还没有选择", foreground="#888888", anchor="w"
        )
        self.output_label.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(
            out_frame, text="选择输出文件夹", command=self._pick_output
        ).grid(row=1, column=0, sticky="w")

        # Step 3: options
        opt_frame = ttk.LabelFrame(main, text="③ 选项", padding=12)
        opt_frame.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        ttk.Checkbutton(
            opt_frame,
            text="美化文件名（把下划线、多余空格整理成空格）",
            variable=self.pretty_var,
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(opt_frame, text="文字底：").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Radiobutton(
            opt_frame,
            text="背景复杂时自动加一层淡底（更清楚，推荐）",
            value="auto",
            variable=self.backing_var,
        ).grid(row=2, column=0, sticky="w")
        ttk.Radiobutton(
            opt_frame,
            text="只用描边 + 阴影，不加底（遮挡更轻）",
            value="never",
            variable=self.backing_var,
        ).grid(row=3, column=0, sticky="w")

        advanced = ttk.Frame(opt_frame)
        advanced.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        positions = ["自动避让（边缘）", "自动避让（全图）", "左上", "右上", "左下", "右下", "顶部居中", "底部居中"]
        for row, (label, var, values) in enumerate([
            ("位置", self.position_var, positions),
            ("文字颜色", self.color_var, ["自动", "白色", "黑色"]),
            ("文字底", self.backing_var, ["auto", "never", "always"]),
        ]):
            ttk.Label(advanced, text=label).grid(row=row, column=0, sticky="w")
            ttk.Combobox(advanced, textvariable=var, values=values, state="readonly", width=22).grid(row=row, column=1, sticky="w")
        for row, (label, var, low, high) in enumerate([
            ("字号占短边 (%)", self.size_var, 1, 12),
            ("边距占短边 (%)", self.margin_var, 0, 15),
            ("文字最大宽度 (%)", self.width_var, 15, 85),
            ("底色不透明度 (%)", self.opacity_var, 0, 100),
            ("最多行数", self.lines_var, 1, 5),
        ]):
            ttk.Label(advanced, text=label).grid(row=row, column=2, sticky="w", padx=(24, 8))
            ttk.Spinbox(advanced, textvariable=var, from_=low, to=high, increment=1, width=8).grid(row=row, column=3, sticky="w")
        ttk.Checkbutton(advanced, text="保留扩展名", variable=self.extension_var).grid(row=5, column=0, sticky="w")
        ttk.Checkbutton(advanced, text="覆盖输出目录的同名文件", variable=self.overwrite_var).grid(row=5, column=1, sticky="w")
        ttk.Button(advanced, text="选择字体…", command=self._pick_font).grid(row=6, column=0, sticky="w")
        ttk.Button(advanced, text="逐张预览与微调…", command=self._preview).grid(row=6, column=1, sticky="w")

        # Run + progress
        self.run_button = ttk.Button(
            main, text="开始处理", command=self._start
        )
        self.run_button.grid(row=5, column=0, sticky="ew", pady=(4, 8), ipady=4)

        self.progress = ttk.Progressbar(main, mode="determinate")
        self.progress.grid(row=6, column=0, sticky="ew")
        self.status_label = ttk.Label(main, text="等待开始…", foreground="#555555")
        self.status_label.grid(row=7, column=0, sticky="w", pady=(4, 6))

        log_frame = ttk.Frame(main)
        log_frame.grid(row=8, column=0, sticky="nsew")
        main.rowconfigure(8, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(log_frame, height=8, wrap="none", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

        self.open_button = ttk.Button(
            main, text="打开输出文件夹", command=self._open_output, state="disabled"
        )
        self.open_button.grid(row=9, column=0, sticky="e", pady=(8, 0))

    # ---------- input handlers ----------
    def _pick_image(self) -> None:
        path = filedialog.askopenfilename(
            title="选择一张图片", filetypes=IMAGE_PATTERNS
        )
        if not path:
            return
        self.input_path = Path(path)
        self.input_label.configure(
            text=f"图片：{self.input_path}", foreground="#222222"
        )
        self.recursive_check.state(["disabled"])

    def _pick_folder(self) -> None:
        path = filedialog.askdirectory(title="选择一个图片文件夹")
        if not path:
            return
        self.input_path = Path(path)
        self.input_label.configure(
            text=f"文件夹：{self.input_path}", foreground="#222222"
        )
        self.recursive_check.state(["!disabled"])

    def _pick_output(self) -> None:
        path = filedialog.askdirectory(title="选择输出文件夹")
        if not path:
            return
        self.output_path = Path(path)
        self.output_label.configure(
            text=f"输出到：{self.output_path}", foreground="#222222"
        )

    def _pick_font(self) -> None:
        path = filedialog.askopenfilename(title="选择字体", filetypes=[("字体", "*.ttf *.otf *.ttc")])
        if path:
            self.font_path = Path(path)

    def _settings(self) -> Settings:
        values = [self.size_var.get(), self.margin_var.get(), self.width_var.get(), self.opacity_var.get()]
        bounds = [(1, 12), (0, 15), (15, 85), (0, 100)]
        if any(not lo <= v <= hi for v, (lo, hi) in zip(values, bounds)) or not 1 <= self.lines_var.get() <= 5:
            raise ValueError("选项超出范围，请按输入框范围填写。")
        positions = dict(zip(["自动避让（边缘）", "自动避让（全图）", "左上", "右上", "左下", "右下", "顶部居中", "底部居中"],
                            ["edge", "anywhere", "top-left", "top-right", "bottom-left", "bottom-right", "top-center", "bottom-center"]))
        return Settings(backing=self.backing_var.get(), placement_mode=positions[self.position_var.get()],
                        text_color={"自动": "auto", "白色": "white", "黑色": "black"}[self.color_var.get()],
                        font_size_ratio=values[0]/100, margin_ratio=values[1]/100,
                        max_width_ratio=values[2]/100, backing_opacity=values[3]/100,
                        max_lines=self.lines_var.get(), min_font_size=8, max_font_size=512)

    def _preview(self) -> None:
        from PIL import Image, ImageOps, ImageTk
        try:
            if self.input_path is None:
                raise ValueError("请先选择图片或文件夹。")
            images = iter_images(self.input_path, self.recursive_var.get())
            if self.output_path:
                images = [p for p in images if not p.resolve().is_relative_to(self.output_path.resolve())]
            if not images:
                raise ValueError("没有找到图片。")
            base = (self._settings(), self.font_path, self.pretty_var.get(), self.extension_var.get())
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        window = tk.Toplevel(self.root)
        window.title("逐张微调 · 拖动文字调整位置")
        window.geometry("1100x760")
        panel = ttk.Frame(window, padding=12)
        panel.pack(side="left", fill="y")
        listing = tk.Listbox(panel, width=28, exportselection=False)
        listing.pack(fill="both", expand=True)
        for source in images:
            listing.insert("end", source.name)
        right = ttk.Frame(window, padding=12)
        right.pack(side="right", fill="both", expand=True)
        caption = tk.StringVar()
        ttk.Label(right, text="当前图片文字（可修改）").pack(anchor="w")
        ttk.Entry(right, textvariable=caption).pack(fill="x", pady=6)
        canvas = tk.Canvas(right, background="#23262d", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        info = ttk.Label(right, text="")
        info.pack(anchor="w", pady=8)
        state = {}

        def render():
            try:
                settings, font, pretty, extension = state["options"]
                text = caption.get().strip()
                if not text:
                    raise ValueError("文字不能为空。")
                image = state["image"]
                layout = fit_text_layout(text, image.size, font, settings)
                placement, _, status = choose_placement(image, layout, settings)
                rendered = draw_caption(image, layout, placement, font)
                window.update_idletasks()
                rendered.thumbnail((max(200, canvas.winfo_width()), max(200, canvas.winfo_height())))
                photo = ImageTk.PhotoImage(rendered)
                canvas.delete("all")
                canvas.create_image(0, 0, anchor="nw", image=photo)
                canvas.photo = photo
                state.update(layout=layout, placement=placement, scale=rendered.width/image.width)
                info.configure(text=f"{state['source'].name} · {layout.font_size}px · 拖动文字后点击保存")
            except Exception as exc:
                info.configure(text=str(exc))

        def save():
            if not caption.get().strip():
                return
            self.overrides[str(state["source"].resolve())] = (*state["options"], caption.get().strip())
            info.configure(text="已保存本张设置，批量导出时自动应用。")

        def select(event=None):
            selected = listing.curselection()
            if not selected:
                return
            source = images[selected[0]]
            options = self.overrides.get(str(source.resolve()))
            state["options"] = options[:4] if options else base
            state["source"] = source
            with Image.open(source) as opened:
                state["image"] = ImageOps.exif_transpose(opened).convert("RGB")
            caption.set(options[4] if options else caption_text_for(source, base[3], base[2]))
            render()

        def start_drag(event):
            box = state.get("placement")
            if box is None:
                return
            scale = state["scale"]
            x, y = event.x/scale, event.y/scale
            if box.box[0] <= x <= box.box[2] and box.box[1] <= y <= box.box[3]:
                state["drag"] = (x-box.box[0], y-box.box[1])

        def end_drag(event):
            offset = state.pop("drag", None)
            if offset is None:
                return
            image, layout, scale = state["image"], state["layout"], state["scale"]
            px = (event.x/scale-offset[0])/max(1, image.width-layout.width)
            py = (event.y/scale-offset[1])/max(1, image.height-layout.height)
            settings, font, pretty, extension = state["options"]
            state["options"] = (replace(settings, manual_position=(max(0,min(1,px)), max(0,min(1,py)))), font, pretty, extension)
            render()

        def use_current():
            try:
                state["options"] = (self._settings(), self.font_path, self.pretty_var.get(), self.extension_var.get())
                render()
            except Exception as exc:
                info.configure(text=str(exc))

        def reset():
            self.overrides.pop(str(state["source"].resolve()), None)
            state["options"] = base
            caption.set(caption_text_for(state["source"], base[3], base[2]))
            render()

        buttons = ttk.Frame(right)
        buttons.pack(fill="x")
        for text, command in [("刷新文字预览", render), ("使用主窗口样式", use_current), ("保存本张设置", save), ("恢复批量默认", reset)]:
            ttk.Button(buttons, text=text, command=command).pack(side="left", padx=3)
        listing.bind("<<ListboxSelect>>", select)
        canvas.bind("<ButtonPress-1>", start_drag)
        canvas.bind("<ButtonRelease-1>", end_drag)
        listing.selection_set(0)
        window.after(50, select)

    def _open_output(self) -> None:
        if self.output_path:
            open_in_file_manager(self.output_path)

    # ---------- logging ----------
    def _append_log(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---------- run ----------
    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if self.input_path is None:
            messagebox.showwarning(APP_TITLE, "请先选择一张图片或一个文件夹。")
            return
        if self.output_path is None:
            messagebox.showwarning(APP_TITLE, "请先选择输出文件夹。")
            return
        if not self.input_path.exists():
            messagebox.showerror(APP_TITLE, f"找不到输入：{self.input_path}")
            return

        input_path = self.input_path.resolve()
        output_path = self.output_path.resolve()
        input_dir = input_path if input_path.is_dir() else input_path.parent
        if input_dir == output_path:
            messagebox.showerror(
                APP_TITLE,
                "输出文件夹不能和原图所在文件夹相同，否则会覆盖原图。\n请另选一个输出文件夹。",
            )
            return

        recursive = self.recursive_var.get() and input_path.is_dir()
        try:
            settings = self._settings()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        pretty = self.pretty_var.get()

        self.run_button.state(["disabled"])
        self.open_button.state(["disabled"])
        self.progress.configure(value=0, maximum=100)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.status_label.configure(text="正在准备…")

        self.worker = threading.Thread(
            target=self._run_batch,
            args=(input_path, output_path, recursive, settings, pretty, self.font_path, self.extension_var.get(), self.overwrite_var.get(), dict(self.overrides)),
            daemon=True,
        )
        self.worker.start()

    def _run_batch(
        self,
        input_path: Path,
        output_path: Path,
        recursive: bool,
        settings: Settings,
        pretty: bool,
        font_path: Path,
        include_extension: bool,
        overwrite: bool,
        overrides: dict | None = None,
    ) -> None:
        try:
            images = [p for p in iter_images(input_path, recursive) if not p.resolve().is_relative_to(output_path)]
            if not images:
                self.events.put(("error", "这个位置没有找到支持的图片。"))
                return
            self.events.put(("total", len(images)))
            ok = 0
            errors = 0
            skipped = 0
            written: list[Path] = []
            results = []
            for index, source in enumerate(images, start=1):
                destination = output_path_for(source, input_path, output_path)
                try:
                    custom = (overrides or {}).get(str(source.resolve()))
                    image_settings, image_font, image_pretty, image_extension = custom[:4] if custom else (settings, font_path, pretty, include_extension)
                    result = stamp_one(
                        source=source,
                        destination=destination,
                        source_root=input_path,
                        font_path=image_font,
                        settings=image_settings,
                        include_extension=image_extension,
                        pretty_name=image_pretty,
                        overwrite=overwrite,
                        dry_run=False,
                        caption_override=custom[4] if custom else None,
                    )
                    results.append(result)
                    status = result.get("status")
                    if status == "ok":
                        ok += 1
                        written.append(destination)
                    if status == "skipped":
                        skipped += 1
                    self.events.put(("progress", index, source.name, str(status)))
                except Exception as exc:  # noqa: BLE001 - report per-image
                    errors += 1
                    results.append({"source": str(source), "status": "error", "error": str(exc)})
                    self.events.put(("progress", index, source.name, f"失败: {exc}"))

            if len(written) > 1:
                try:
                    make_contact_sheet(written, output_path, font_path)
                except Exception:
                    pass

            output_path.mkdir(parents=True, exist_ok=True)
            (output_path / "caption_report.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
            self.events.put(("done", ok, errors, len(images), skipped))
        except Exception as exc:  # noqa: BLE001 - top-level guard
            self.events.put(("error", f"{exc}\n{traceback.format_exc()}"))

    # ---------- event pump ----------
    def _drain_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "total":
                    total = event[1]
                    self.progress.configure(maximum=total, value=0)
                    self.status_label.configure(text=f"共 {total} 张，开始处理…")
                elif kind == "progress":
                    index, name, status = event[1], event[2], event[3]
                    self.progress.configure(value=index)
                    self.status_label.configure(
                        text=f"正在处理 {index}/{int(self.progress['maximum'])}"
                    )
                    self._append_log(f"[{index}] {name} — {status}")
                elif kind == "done":
                    ok, errors, total = event[1], event[2], event[3]
                    self.progress.configure(value=int(self.progress["maximum"]))
                    summary = f"完成：成功 {ok} 张，跳过 {event[4]} 张"
                    if errors:
                        summary += f"，失败 {errors} 张"
                    self.status_label.configure(text=summary)
                    self._append_log("—— " + summary + " ——")
                    self.run_button.state(["!disabled"])
                    self.open_button.state(["!disabled"])
                    if self.output_path:
                        open_in_file_manager(self.output_path)
                elif kind == "error":
                    self.status_label.configure(text="出错了")
                    self._append_log(str(event[1]))
                    self.run_button.state(["!disabled"])
                    messagebox.showerror(APP_TITLE, str(event[1]))
        except queue.Empty:
            pass
        self.root.after(120, self._drain_events)


def _selftest() -> int:
    """Headless end-to-end check used to verify a packaged build.

    Run with:  SmartNameStamp --selftest <input> <output>
    Confirms the bundled font and OpenCV cascades resolve when frozen.
    """
    import sys

    args = [a for a in sys.argv[1:] if a != "--selftest"]
    in_path = Path(args[0]) if len(args) > 0 else Path.cwd()
    out_path = Path(args[1]) if len(args) > 1 else (Path.cwd() / "selftest-out")
    out_path.mkdir(parents=True, exist_ok=True)
    print(f"[selftest] font: {DEFAULT_FONT_PATH} exists={DEFAULT_FONT_PATH.exists()}")
    images = iter_images(in_path.resolve(), recursive=True)
    print(f"[selftest] found {len(images)} image(s)")
    settings = Settings(backing="auto", face_avoidance="auto")
    ok = 0
    for src in images:
        dst = output_path_for(src, in_path.resolve(), out_path.resolve())
        result = stamp_one(
            source=src,
            destination=dst,
            source_root=in_path.resolve(),
            font_path=DEFAULT_FONT_PATH,
            settings=settings,
            include_extension=False,
            pretty_name=True,
            overwrite=True,
            dry_run=False,
        )
        print(f"[selftest] {src.name}: {result.get('status')} face={result.get('face_detection')}")
        ok += 1 if result.get("status") == "ok" else 0
    print(f"[selftest] done, ok={ok}/{len(images)}")
    return 0 if ok == len(images) and images else 1


def _startup_check() -> int:
    """Print startup diagnostics before opening the GUI."""
    import platform
    import sys

    print("[startup] executable:", sys.executable)
    print("[startup] argv:", sys.argv)
    print("[startup] cwd:", Path.cwd())
    print("[startup] platform:", platform.platform(), platform.machine())
    print("[startup] frozen:", getattr(sys, "frozen", False))
    print("[startup] font:", DEFAULT_FONT_PATH, "exists=", DEFAULT_FONT_PATH.exists())
    print("[startup] supported:", ", ".join(sorted(SUPPORTED_EXTENSIONS)))

    try:
        from PIL import Image

        print("[startup] Pillow:", getattr(Image, "__version__", "unknown"))
    except Exception:
        print("[startup] Pillow import failed:")
        print(traceback.format_exc())
        return 1

    try:
        import cv2

        print("[startup] OpenCV:", getattr(cv2, "__version__", "unknown"))
        print("[startup] OpenCV data:", getattr(cv2, "data", None))
    except Exception:
        print("[startup] OpenCV import failed:")
        print(traceback.format_exc())
        return 1

    try:
        probe = tk.Tk()
        probe.withdraw()
        print("[startup] Tk patchlevel:", probe.tk.call("info", "patchlevel"))
        print("[startup] Tk windowing:", probe.tk.call("tk", "windowingsystem"))
        probe.destroy()
    except Exception:
        print("[startup] Tk init failed:")
        print(traceback.format_exc())
        return 1

    print("[startup] OK")
    return 0


def main() -> None:
    import sys

    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    if "--startup-check" in sys.argv:
        raise SystemExit(_startup_check())

    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "aqua" in style.theme_names():
            style.theme_use("aqua")
    except Exception:
        pass
    StampApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
