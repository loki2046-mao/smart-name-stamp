#!/usr/bin/env python3
"""Batch-stamp image file names onto visually quiet parts of each image."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps


SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
}

def resource_base() -> Path:
    """Directory that holds bundled assets, whether run as a script or frozen."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


SCRIPT_DIR = resource_base()
DEFAULT_FONT_PATH = SCRIPT_DIR / "assets" / "fonts" / "NotoSansCJKsc-Regular.otf"


@dataclass(frozen=True)
class Settings:
    max_analysis_side: int = 1600
    margin_ratio: float = 0.035
    max_width_ratio: float = 0.42
    min_font_size: int = 18
    max_font_size: int = 96
    font_size_ratio: float = 0.052
    max_lines: int = 2
    backing: str = "auto"
    placement_mode: str = "edge"
    face_avoidance: str = "auto"
    manual_position: tuple[float, float] | None = None
    text_color: str = "auto"
    backing_opacity: float = 0.32


@dataclass(frozen=True)
class TextLayout:
    text: str
    lines: tuple[str, ...]
    font_size: int
    width: int
    height: int
    line_height: int
    line_spacing: int
    padding_x: int
    padding_y: int
    stroke_width: int


@dataclass(frozen=True)
class CandidateScore:
    box: tuple[int, int, int, int]
    score: float
    metrics: dict[str, float]


@dataclass(frozen=True)
class Placement:
    box: tuple[int, int, int, int]
    text_color: tuple[int, int, int, int]
    stroke_color: tuple[int, int, int, int]
    backing_color: tuple[int, int, int, int] | None
    score: float
    metrics: dict[str, float]


class ImageStampError(RuntimeError):
    """Raised when one image cannot be stamped cleanly."""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Put each image's file name onto a quiet, readable area of the image."
        )
    )
    parser.add_argument("input", type=Path, help="Input image file or directory.")
    parser.add_argument("output", type=Path, help="Output file or directory.")
    parser.add_argument(
        "--font",
        type=Path,
        default=DEFAULT_FONT_PATH,
        help="OpenType/TrueType font path. Defaults to bundled Noto Sans CJK SC.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Walk subdirectories when input is a directory.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files in the output path.",
    )
    parser.add_argument(
        "--include-extension",
        action="store_true",
        help="Use the full file name, including extension, as the stamped text.",
    )
    parser.add_argument(
        "--pretty-name",
        action="store_true",
        help="Replace underscores and repeated spaces in the stamped text.",
    )
    parser.add_argument(
        "--placement",
        choices=("edge", "anywhere"),
        default="edge",
        help="Prefer edges/corners or search the full image.",
    )
    parser.add_argument(
        "--backing",
        choices=("auto", "always", "never"),
        default="auto",
        help="Use a subtle translucent backing when needed for legibility.",
    )
    parser.add_argument(
        "--face-avoidance",
        choices=("auto", "off", "require"),
        default="auto",
        help=(
            "Use OpenCV Haar face detection when available. "
            "'require' fails if OpenCV is not installed."
        ),
    )
    parser.add_argument(
        "--font-size-ratio",
        type=float,
        default=0.052,
        help="Font size as a ratio of the shorter image side.",
    )
    parser.add_argument(
        "--max-width-ratio",
        type=float,
        default=0.42,
        help="Maximum caption block width as a ratio of image width.",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=2,
        help="Maximum caption lines before ellipsizing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze and write only the JSON report, without image files.",
    )
    parser.add_argument(
        "--contact-sheet",
        action="store_true",
        help="Write a thumbnail contact sheet named _contact_sheet.jpg.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Report JSON path. Defaults to <output>/caption_report.json.",
    )
    return parser.parse_args(argv)


def iter_images(input_path: Path, recursive: bool) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            return [input_path]
        raise ImageStampError(f"Unsupported image extension: {input_path.suffix}")

    if not input_path.is_dir():
        raise ImageStampError(f"Input does not exist: {input_path}")

    pattern = "**/*" if recursive else "*"
    return sorted(
        p
        for p in input_path.glob(pattern)
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def output_path_for(input_path: Path, source_root: Path, output_root: Path) -> Path:
    if source_root.is_file():
        if output_root.suffix:
            return output_root
        return output_root / source_root.name
    rel = input_path.relative_to(source_root)
    return output_root / rel


def caption_text_for(path: Path, include_extension: bool, pretty_name: bool) -> str:
    text = path.name if include_extension else path.stem
    if pretty_name:
        text = re.sub(r"[_\s]+", " ", text).strip()
    return text


def load_font(font_path: Path, size: int) -> ImageFont.FreeTypeFont:
    if not font_path.exists():
        raise ImageStampError(
            f"Font not found: {font_path}. Pass --font with an open-source font."
        )
    try:
        return ImageFont.truetype(str(font_path), size=size)
    except OSError as exc:
        raise ImageStampError(f"Could not load font: {font_path}") from exc


def text_advance(font: ImageFont.FreeTypeFont, text: str) -> int:
    if not text:
        return 0
    left, _top, right, _bottom = font.getbbox(text)
    return max(0, right - left)


def split_units(text: str) -> list[str]:
    if re.search(r"\s", text) and not re.search(r"[\u3400-\u9fff]", text):
        return re.findall(r"\S+\s*", text)
    return list(text)


def ellipsize(line: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    ellipsis = "..."
    if text_advance(font, ellipsis) > max_width:
        return ""
    while line and text_advance(font, line + ellipsis) > max_width:
        line = line[:-1]
    return (line.rstrip() + ellipsis).strip()


def wrap_text(
    text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int
) -> tuple[str, ...]:
    units = split_units(text)
    lines: list[str] = []
    current = ""

    for unit in units:
        proposed = current + unit
        if current and text_advance(font, proposed) > max_width:
            lines.append(current.rstrip())
            current = unit.lstrip()
        else:
            current = proposed

        while current and text_advance(font, current) > max_width:
            piece = ""
            for char in current:
                if piece and text_advance(font, piece + char) > max_width:
                    lines.append(piece.rstrip())
                    current = current[len(piece) :].lstrip()
                    break
                piece += char
            else:
                break

        if len(lines) >= max_lines:
            break

    if len(lines) < max_lines and current.strip():
        lines.append(current.rstrip())

    if len(lines) > max_lines:
        lines = lines[:max_lines]

    consumed = "".join(lines).replace(" ", "")
    original = text.replace(" ", "")
    if len(lines) == max_lines and len(consumed) < len(original):
        lines[-1] = ellipsize(lines[-1], font, max_width)

    return tuple(line for line in lines if line)


def fit_text_layout(
    text: str,
    image_size: tuple[int, int],
    font_path: Path,
    settings: Settings,
) -> TextLayout:
    width, height = image_size
    target = int(min(width, height) * settings.font_size_ratio)
    start_size = max(settings.min_font_size, min(settings.max_font_size, target))
    max_text_width = int(width * settings.max_width_ratio)

    for size in range(start_size, settings.min_font_size - 1, -2):
        font = load_font(font_path, size)
        padding_x = max(10, round(size * 0.42))
        padding_y = max(7, round(size * 0.28))
        stroke_width = max(1, min(5, round(size * 0.055)))
        usable_width = max(20, max_text_width - 2 * padding_x)
        lines = wrap_text(text, font, usable_width, settings.max_lines)
        if not lines:
            continue

        line_boxes = [font.getbbox(line, stroke_width=stroke_width) for line in lines]
        line_width = max(right - left for left, _top, right, _bottom in line_boxes)
        line_height = max(bottom - top for _left, top, _right, bottom in line_boxes)
        line_spacing = max(2, round(size * 0.18))
        text_height = line_height * len(lines) + line_spacing * (len(lines) - 1)
        block_width = line_width + 2 * padding_x
        block_height = text_height + 2 * padding_y

        if block_width <= width * 0.9 and block_height <= height * 0.3:
            return TextLayout(
                text=text,
                lines=lines,
                font_size=size,
                width=math.ceil(block_width),
                height=math.ceil(block_height),
                line_height=math.ceil(line_height),
                line_spacing=line_spacing,
                padding_x=padding_x,
                padding_y=padding_y,
                stroke_width=stroke_width,
            )

    raise ImageStampError(f"Could not fit caption text: {text!r}")


def resized_for_analysis(
    image: Image.Image, max_side: int
) -> tuple[Image.Image, float]:
    width, height = image.size
    scale = min(1.0, max_side / max(width, height))
    if scale == 1.0:
        return image.convert("RGB"), 1.0
    resized = image.resize(
        (max(1, round(width * scale)), max(1, round(height * scale))),
        Image.Resampling.LANCZOS,
    )
    return resized.convert("RGB"), scale


def build_analysis_arrays(image: Image.Image) -> dict[str, np.ndarray]:
    arr = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b

    gx = np.zeros_like(luma)
    gy = np.zeros_like(luma)
    gx[:, 1:] = np.abs(luma[:, 1:] - luma[:, :-1])
    gy[1:, :] = np.abs(luma[1:, :] - luma[:-1, :])
    grad = np.sqrt(gx * gx + gy * gy)
    grad_norm = grad / max(float(np.percentile(grad, 95)), 0.025)
    grad_norm = np.clip(grad_norm, 0.0, 1.0)

    max_rgb = arr.max(axis=2)
    min_rgb = arr.min(axis=2)
    saturation = np.zeros_like(max_rgb)
    np.divide(max_rgb - min_rgb, max_rgb, out=saturation, where=max_rgb != 0)
    local_contrast = np.abs(luma - float(np.mean(luma)))
    saliency = np.clip(0.58 * grad_norm + 0.28 * saturation + 0.14 * local_contrast, 0, 1)

    return {
        "luma": luma,
        "grad": grad_norm,
        "saturation": saturation,
        "saliency": saliency,
    }


def detect_faces(
    analysis_image: Image.Image,
    analysis_scale: float,
    original_size: tuple[int, int],
    face_avoidance: str,
) -> tuple[list[tuple[int, int, int, int]], str]:
    if face_avoidance == "off":
        return [], "off"

    try:
        import cv2  # type: ignore[import-not-found]
    except Exception as exc:
        if face_avoidance == "require":
            raise ImageStampError(
                "OpenCV is required for --face-avoidance require. "
                "Install requirements-full.txt or use --face-avoidance auto."
            ) from exc
        return [], "unavailable"

    cascade_specs = [
        ("front", Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"),
        ("profile", Path(cv2.data.haarcascades) / "haarcascade_profileface.xml"),
    ]
    cascades = [
        (name, cv2.CascadeClassifier(str(path)))
        for name, path in cascade_specs
    ]
    if all(cascade.empty() for _name, cascade in cascades):
        if face_avoidance == "require":
            raise ImageStampError("Could not load OpenCV face cascades.")
        return [], "unavailable"

    rgb = np.asarray(analysis_image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    min_side = min(gray.shape[:2])
    min_size = max(24, round(min_side * 0.045))
    raw_faces: list[tuple[int, int, int, int]] = []
    for name, cascade in cascades:
        if cascade.empty():
            continue
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.08,
            minNeighbors=5 if name == "front" else 4,
            minSize=(min_size, min_size),
        )
        raw_faces.extend((int(x), int(y), int(w), int(h)) for x, y, w, h in faces)

        if name == "profile":
            flipped = cv2.flip(gray, 1)
            flipped_faces = cascade.detectMultiScale(
                flipped,
                scaleFactor=1.08,
                minNeighbors=4,
                minSize=(min_size, min_size),
            )
            img_w = gray.shape[1]
            for x, y, w, h in flipped_faces:
                raw_faces.append((int(img_w - x - w), int(y), int(w), int(h)))

    width, height = original_size
    boxes: list[tuple[int, int, int, int]] = []
    for x, y, w, h in raw_faces:
        x0 = x / analysis_scale
        y0 = y / analysis_scale
        x1 = (x + w) / analysis_scale
        y1 = (y + h) / analysis_scale
        pad_x = (x1 - x0) * 0.48
        pad_top = (y1 - y0) * 0.58
        pad_bottom = (y1 - y0) * 0.58
        expanded = (
            max(0, round(x0 - pad_x)),
            max(0, round(y0 - pad_top)),
            min(width, round(x1 + pad_x)),
            min(height, round(y1 + pad_bottom)),
        )
        if all(overlap_ratio(expanded, existing) < 0.55 for existing in boxes):
            boxes.append(expanded)
    return boxes, "opencv"


def generate_candidate_boxes(
    image_size: tuple[int, int],
    layout: TextLayout,
    settings: Settings,
) -> list[tuple[int, int, int, int]]:
    width, height = image_size
    margin = max(8, round(min(width, height) * settings.margin_ratio))
    box_w, box_h = layout.width, layout.height
    if box_w + 2 * margin > width or box_h + 2 * margin > height:
        margin = max(2, min(margin, width // 40, height // 40))

    def clamp_x(value: float) -> int:
        return max(margin, min(round(value), width - box_w - margin))

    def clamp_y(value: float) -> int:
        return max(margin, min(round(value), height - box_h - margin))

    xs = [
        margin,
        width * 0.25 - box_w / 2,
        width * 0.5 - box_w / 2,
        width * 0.75 - box_w / 2,
        width - box_w - margin,
    ]
    ys = [
        margin,
        height * 0.22 - box_h / 2,
        height * 0.5 - box_h / 2,
        height * 0.78 - box_h / 2,
        height - box_h - margin,
    ]

    if settings.manual_position is not None:
        px, py = settings.manual_position
        x0 = max(0, min(width - box_w, round(px * max(0, width - box_w))))
        y0 = max(0, min(height - box_h, round(py * max(0, height - box_h))))
        return [(x0, y0, x0 + box_w, y0 + box_h)]

    anchors = {"top-left": (xs[0], ys[0]), "top-right": (xs[-1], ys[0]),
               "bottom-left": (xs[0], ys[-1]), "bottom-right": (xs[-1], ys[-1]),
               "top-center": (xs[2], ys[0]), "bottom-center": (xs[2], ys[-1])}
    if settings.placement_mode in anchors:
        x, y = anchors[settings.placement_mode]
        x0, y0 = clamp_x(x), clamp_y(y)
        return [(x0, y0, x0 + box_w, y0 + box_h)]

    boxes: set[tuple[int, int, int, int]] = set()
    if settings.placement_mode == "edge":
        for x in xs:
            for y in (ys[0], ys[1], ys[-2], ys[-1]):
                x0, y0 = clamp_x(x), clamp_y(y)
                boxes.add((x0, y0, x0 + box_w, y0 + box_h))
    else:
        for x in xs:
            for y in ys:
                x0, y0 = clamp_x(x), clamp_y(y)
                boxes.add((x0, y0, x0 + box_w, y0 + box_h))

    return sorted(boxes)


def overlap_ratio(
    box: tuple[int, int, int, int], obstacle: tuple[int, int, int, int]
) -> float:
    x0 = max(box[0], obstacle[0])
    y0 = max(box[1], obstacle[1])
    x1 = min(box[2], obstacle[2])
    y1 = min(box[3], obstacle[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    intersection = (x1 - x0) * (y1 - y0)
    area = max(1, (box[2] - box[0]) * (box[3] - box[1]))
    return intersection / area


def score_candidate(
    box: tuple[int, int, int, int],
    arrays: dict[str, np.ndarray],
    analysis_scale: float,
    original_size: tuple[int, int],
    face_boxes: Sequence[tuple[int, int, int, int]],
) -> CandidateScore:
    scaled = tuple(round(v * analysis_scale) for v in box)
    x0, y0, x1, y1 = scaled
    luma = arrays["luma"][y0:y1, x0:x1]
    grad = arrays["grad"][y0:y1, x0:x1]
    saturation = arrays["saturation"][y0:y1, x0:x1]
    saliency = arrays["saliency"][y0:y1, x0:x1]
    if luma.size == 0:
        return CandidateScore(box=box, score=float("inf"), metrics={})

    luma_mean = float(np.mean(luma))
    luma_std = float(np.std(luma))
    grad_mean = float(np.mean(grad))
    sat_std = float(np.std(saturation))
    saliency_mean = float(np.mean(saliency))
    busy_fraction = float(np.mean(saliency > np.percentile(arrays["saliency"], 82)))

    width, height = original_size
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    center_dx = abs(cx / width - 0.5) * 2
    center_dy = abs(cy / height - 0.5) * 2
    center_penalty = max(0.0, 1.0 - math.sqrt(center_dx * center_dx + center_dy * center_dy))

    face_overlap = max((overlap_ratio(box, face) for face in face_boxes), default=0.0)
    watermark_guard = (
        round(width * 0.79),
        round(height * 0.72),
        width,
        height,
    )
    watermark_overlap = overlap_ratio(box, watermark_guard)
    edge_gap = min(box[0], box[1], width - box[2], height - box[3]) / max(1, min(width, height))
    floating_penalty = max(0.0, edge_gap - 0.13)

    score = (
        37.0 * saliency_mean
        + 28.0 * grad_mean
        + 22.0 * luma_std
        + 10.0 * sat_std
        + 18.0 * busy_fraction
        + 15.0 * center_penalty
        + 24.0 * floating_penalty
        + 2000.0 * face_overlap
        + 700.0 * watermark_overlap
    )

    metrics = {
        "luma_mean": luma_mean,
        "luma_std": luma_std,
        "edge_density": grad_mean,
        "saturation_std": sat_std,
        "saliency": saliency_mean,
        "busy_fraction": busy_fraction,
        "center_penalty": center_penalty,
        "floating_penalty": floating_penalty,
        "face_overlap": face_overlap,
        "watermark_overlap": watermark_overlap,
    }
    return CandidateScore(box=box, score=score, metrics=metrics)


def choose_text_colors(
    metrics: dict[str, float], backing: str
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int], tuple[int, int, int, int] | None]:
    luma = metrics.get("luma_mean", 0.5)
    noise = (
        metrics.get("edge_density", 0.0)
        + metrics.get("luma_std", 0.0)
        + metrics.get("busy_fraction", 0.0)
    )

    if luma >= 0.56:
        text_color = (18, 18, 18, 246)
        stroke_color = (255, 255, 255, 210)
        backing_color = (255, 255, 255, 78)
    else:
        text_color = (250, 250, 246, 248)
        stroke_color = (0, 0, 0, 205)
        backing_color = (0, 0, 0, 86)

    if backing == "never":
        return text_color, stroke_color, None
    if backing == "always" or noise > 0.35:
        return text_color, stroke_color, backing_color
    return text_color, stroke_color, None


def choose_placement(
    image: Image.Image,
    layout: TextLayout,
    settings: Settings,
) -> tuple[Placement, list[tuple[int, int, int, int]], str]:
    analysis_image, analysis_scale = resized_for_analysis(
        image, settings.max_analysis_side
    )
    arrays = build_analysis_arrays(analysis_image)
    face_boxes, face_status = detect_faces(
        analysis_image,
        analysis_scale,
        image.size,
        settings.face_avoidance,
    )
    candidates = generate_candidate_boxes(image.size, layout, settings)
    if not candidates:
        raise ImageStampError("No possible caption placement candidate.")

    scores = [
        score_candidate(candidate, arrays, analysis_scale, image.size, face_boxes)
        for candidate in candidates
    ]
    best = min(scores, key=lambda item: item.score)
    text_color, stroke_color, backing_color = choose_text_colors(
        best.metrics, settings.backing
    )
    if settings.text_color == "white":
        text_color, stroke_color = (250, 250, 250, 255), (0, 0, 0, 205)
        if backing_color is not None:
            backing_color = (0, 0, 0, backing_color[3])
    elif settings.text_color == "black":
        text_color, stroke_color = (18, 18, 18, 255), (255, 255, 255, 210)
        if backing_color is not None:
            backing_color = (255, 255, 255, backing_color[3])
    if backing_color is not None:
        backing_color = (*backing_color[:3], round(255 * settings.backing_opacity))
    return (
        Placement(
            box=best.box,
            text_color=text_color,
            stroke_color=stroke_color,
            backing_color=backing_color,
            score=best.score,
            metrics=best.metrics,
        ),
        face_boxes,
        face_status,
    )


def draw_caption(
    image: Image.Image,
    layout: TextLayout,
    placement: Placement,
    font_path: Path,
) -> Image.Image:
    base = image.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = load_font(font_path, layout.font_size)
    x0, y0, x1, y1 = placement.box
    radius = max(4, round(layout.font_size * 0.22))

    if placement.backing_color is not None:
        draw.rounded_rectangle(
            (x0, y0, x1, y1),
            radius=radius,
            fill=placement.backing_color,
        )

    text_x = x0 + layout.padding_x
    text_y = y0 + layout.padding_y
    for idx, line in enumerate(layout.lines):
        left, top, _right, _bottom = font.getbbox(
            line, stroke_width=layout.stroke_width
        )
        line_y = (
            text_y
            + idx * (layout.line_height + layout.line_spacing)
            - top
        )
        shadow_offset = max(1, round(layout.font_size * 0.035))
        shadow_color = (
            0,
            0,
            0,
            82,
        ) if placement.text_color[0] > 128 else (255, 255, 255, 70)
        draw.text(
            (text_x - left + shadow_offset, line_y + shadow_offset),
            line,
            font=font,
            fill=shadow_color,
            stroke_width=layout.stroke_width,
            stroke_fill=shadow_color,
        )
        draw.text(
            (text_x - left, line_y),
            line,
            font=font,
            fill=placement.text_color,
            stroke_width=layout.stroke_width,
            stroke_fill=placement.stroke_color,
        )

    return Image.alpha_composite(base, overlay)


def save_image(image: Image.Image, source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    suffix = destination.suffix.lower()
    params: dict[str, object] = {}
    if suffix in {".jpg", ".jpeg"}:
        image = image.convert("RGB")
        params.update({"quality": 95, "subsampling": 1, "optimize": True})
    elif suffix == ".webp":
        params.update({"quality": 95, "method": 6})
    else:
        image = image.convert("RGBA") if image.mode == "RGBA" else image
    image.save(destination, **params)


def make_contact_sheet(
    image_paths: Sequence[Path],
    output_dir: Path,
    font_path: Path,
) -> Path | None:
    paths = [
        path
        for path in image_paths
        if path.exists()
        and not path.name.startswith("_")
        and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    if not paths:
        return None

    thumb_w, thumb_h = 320, 240
    cols = 4
    pad = 16
    label_h = 34
    rows = math.ceil(len(paths) / cols)
    sheet = Image.new(
        "RGB",
        (
            cols * thumb_w + (cols + 1) * pad,
            rows * (thumb_h + label_h) + (rows + 1) * pad,
        ),
        (245, 245, 242),
    )
    draw = ImageDraw.Draw(sheet)
    try:
        label_font = ImageFont.truetype(str(font_path), 16)
    except OSError:
        label_font = ImageFont.load_default()

    for index, path in enumerate(paths):
        row, col = divmod(index, cols)
        x = pad + col * (thumb_w + pad)
        y = pad + row * (thumb_h + label_h + pad)
        try:
            with Image.open(path) as opened:
                thumb = ImageOps.exif_transpose(opened).convert("RGB")
                thumb.thumbnail((thumb_w, thumb_h), Image.Resampling.LANCZOS)
                tx = x + (thumb_w - thumb.width) // 2
                ty = y + (thumb_h - thumb.height) // 2
                sheet.paste(thumb, (tx, ty))
        except OSError:
            continue

        label = path.stem
        if len(label) > 18:
            label = label[:17] + "..."
        draw.text((x, y + thumb_h + 8), label, fill=(40, 40, 40), font=label_font)

    output_dir.mkdir(parents=True, exist_ok=True)
    sheet_path = output_dir / "_contact_sheet.jpg"
    sheet.save(sheet_path, quality=92)
    return sheet_path


def stamp_one(
    source: Path,
    destination: Path,
    source_root: Path,
    font_path: Path,
    settings: Settings,
    include_extension: bool,
    pretty_name: bool,
    overwrite: bool,
    dry_run: bool,
    caption_override: str | None = None,
) -> dict[str, object]:
    if destination.exists() and not overwrite and not dry_run:
        return {
            "source": str(source),
            "destination": str(destination),
            "status": "skipped",
            "reason": "output_exists",
        }

    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")

    text = caption_override if caption_override is not None else caption_text_for(source, include_extension, pretty_name)
    layout = fit_text_layout(text, image.size, font_path, settings)
    placement, face_boxes, face_status = choose_placement(image, layout, settings)

    if not dry_run:
        stamped = draw_caption(image, layout, placement, font_path)
        save_image(stamped, source, destination)

    return {
        "source": str(source),
        "destination": str(destination),
        "status": "ok",
        "text": text,
        "image_size": {"width": image.size[0], "height": image.size[1]},
        "font": str(font_path),
        "font_size": layout.font_size,
        "lines": list(layout.lines),
        "box": {
            "x0": placement.box[0],
            "y0": placement.box[1],
            "x1": placement.box[2],
            "y1": placement.box[3],
        },
        "text_color_rgba": placement.text_color,
        "stroke_color_rgba": placement.stroke_color,
        "backing_color_rgba": placement.backing_color,
        "score": round(placement.score, 4),
        "metrics": {key: round(value, 5) for key, value in placement.metrics.items()},
        "face_detection": face_status,
        "face_boxes": [
            {"x0": x0, "y0": y0, "x1": x1, "y1": y1}
            for x0, y0, x1, y1 in face_boxes
        ],
        "relative_source": str(source.relative_to(source_root))
        if source_root.is_dir()
        else source.name,
    }


def report_path_for(output: Path, explicit_report: Path | None) -> Path:
    if explicit_report:
        return explicit_report
    if output.suffix:
        return output.with_name(output.stem + "_caption_report.json")
    return output / "caption_report.json"


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    settings = Settings(
        font_size_ratio=args.font_size_ratio,
        max_width_ratio=args.max_width_ratio,
        max_lines=max(1, args.max_lines),
        backing=args.backing,
        placement_mode=args.placement,
        face_avoidance=args.face_avoidance,
    )

    try:
        input_path = args.input.resolve()
        output_path = args.output.resolve()
        font_path = args.font.resolve()
        images = iter_images(input_path, args.recursive)
        if not images:
            raise ImageStampError(f"No supported images found in {input_path}")

        results: list[dict[str, object]] = []
        for index, source in enumerate(images, start=1):
            destination = output_path_for(source, input_path, output_path)
            try:
                result = stamp_one(
                    source=source,
                    destination=destination,
                    source_root=input_path,
                    font_path=font_path,
                    settings=settings,
                    include_extension=args.include_extension,
                    pretty_name=args.pretty_name,
                    overwrite=args.overwrite,
                    dry_run=args.dry_run,
                )
            except Exception as exc:
                result = {
                    "source": str(source),
                    "destination": str(destination),
                    "status": "error",
                    "reason": str(exc),
                }
            results.append(result)
            print(
                f"[{index}/{len(images)}] {result['status']}: {source.name}",
                file=sys.stderr,
            )

        report = {
            "input": str(input_path),
            "output": str(output_path),
            "dry_run": args.dry_run,
            "count": len(results),
            "ok": sum(1 for item in results if item["status"] == "ok"),
            "skipped": sum(1 for item in results if item["status"] == "skipped"),
            "errors": sum(1 for item in results if item["status"] == "error"),
            "results": results,
        }
        report_path = report_path_for(output_path, args.report).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Report: {report_path}", file=sys.stderr)
        if args.contact_sheet and not args.dry_run:
            written_paths = [
                Path(str(item["destination"]))
                for item in results
                if item["status"] == "ok"
            ]
            sheet_dir = output_path if not output_path.suffix else output_path.parent
            sheet_path = make_contact_sheet(written_paths, sheet_dir, font_path)
            if sheet_path:
                print(f"Contact sheet: {sheet_path.resolve()}", file=sys.stderr)
        return 1 if report["errors"] else 0
    except ImageStampError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
