from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import numpy as np
from PIL import Image, ImageDraw
from skimage.measure import label, regionprops
from skimage.morphology import binary_closing, remove_small_objects, rectangle


@dataclass
class ScaleBarDetection:
    has_scale_bar: bool
    scale_bar_text: str
    label_um: float | None
    bar_length_px: float | None
    estimated_um_per_px: float | None
    confidence: str
    bbox_xyxy: tuple[int, int, int, int] | None
    method: str
    notes: str


SCALE_LABEL_BY_MAGNIFICATION_UM = {
    "2x": 250.0,
    "5x": 100.0,
    "10x": 200.0,
    "20x": 20.0,
}


def infer_scale_label_um(filename: str) -> tuple[float | None, str]:
    lowered = filename.lower()
    match = re.search(r"(?<!\d)(2x|5x|10x|20x)(?:\d+)?", lowered)
    if match and match.group(1) in SCALE_LABEL_BY_MAGNIFICATION_UM:
        value = SCALE_LABEL_BY_MAGNIFICATION_UM[match.group(1)]
        return value, f"{value:g} um inferred from filename magnification {match.group(1)}"
    return None, "scale label not inferred; manual reading required"


def detect_red_scale_bar(image: Image.Image, filename: str) -> ScaleBarDetection:
    arr = np.asarray(image.convert("RGB"))
    height, width = arr.shape[:2]

    y0 = int(height * 0.72)
    x0 = int(width * 0.50)
    roi = arr[y0:height, x0:width].astype(np.int16)

    red = roi[:, :, 0]
    green = roi[:, :, 1]
    blue = roi[:, :, 2]
    mask = (
        (red > 120)
        & (red > green + 40)
        & (red > blue + 40)
        & (green < 140)
        & (blue < 140)
    )
    mask = binary_closing(mask, rectangle(3, 17))
    mask = remove_small_objects(mask, min_size=20)

    candidates: list[tuple[float, tuple[int, int, int, int], float, float]] = []
    for prop in regionprops(label(mask)):
        minr, minc, maxr, maxc = prop.bbox
        comp_w = maxc - minc
        comp_h = maxr - minr
        aspect = comp_w / max(comp_h, 1)
        gy0, gx0, gy1, gx1 = minr + y0, minc + x0, maxr + y0, maxc + x0

        if (
            comp_w >= 25
            and comp_h <= 60
            and aspect >= 3.5
            and gy1 > height * 0.95
            and gx0 > width * 0.55
        ):
            # Prefer a low, long, horizontal component. This rejects most red
            # XPL interference colors and the scale-bar label text.
            score = comp_w * aspect + (gy1 / height) * 100
            candidates.append((score, (gx0, gy0, gx1, gy1), comp_w, aspect))

    label_um, label_note = infer_scale_label_um(filename)
    if not candidates:
        return ScaleBarDetection(
            has_scale_bar=False,
            scale_bar_text=label_note,
            label_um=label_um,
            bar_length_px=None,
            estimated_um_per_px=None,
            confidence="Low",
            bbox_xyxy=None,
            method="red-overlay geometry detector",
            notes="No red horizontal scale-bar line passed geometry filters.",
        )

    candidates.sort(reverse=True, key=lambda item: item[0])
    _, bbox, bar_length_px, aspect = candidates[0]
    estimated = label_um / bar_length_px if label_um and bar_length_px else None
    confidence = "High" if label_um and aspect >= 4.0 else "Medium"
    text = label_note if label_um else "visible red scale bar; label requires manual reading"
    notes = (
        f"Detected red lower-right horizontal bar; aspect={aspect:.2f}; "
        f"bbox_xyxy={bbox}. Verify label manually before publication-scale measurements."
    )
    return ScaleBarDetection(
        has_scale_bar=True,
        scale_bar_text=text,
        label_um=label_um,
        bar_length_px=float(bar_length_px),
        estimated_um_per_px=estimated,
        confidence=confidence,
        bbox_xyxy=bbox,
        method="red-overlay geometry detector plus filename label inference",
        notes=notes,
    )


def save_scale_bar_qc(
    image: Image.Image,
    detection: ScaleBarDetection,
    out_path: Path,
    title: str,
) -> None:
    image = image.convert("RGB")
    width, height = image.size
    crop_box = (int(width * 0.45), int(height * 0.68), width, height)
    crop = image.crop(crop_box)
    draw = ImageDraw.Draw(crop)
    if detection.bbox_xyxy:
        x1, y1, x2, y2 = detection.bbox_xyxy
        draw.rectangle(
            (x1 - crop_box[0], y1 - crop_box[1], x2 - crop_box[0], y2 - crop_box[1]),
            outline=(0, 255, 255),
            width=5,
        )
    label_text = detection.scale_bar_text
    if detection.estimated_um_per_px is not None:
        label_text += f"; {detection.estimated_um_per_px:.4f} um/px"
    canvas_h = crop.height + 110
    canvas = Image.new("RGB", (crop.width, canvas_h), "white")
    canvas.paste(crop, (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((14, crop.height + 18), title, fill=(0, 0, 0))
    draw.text((14, crop.height + 48), label_text[:180], fill=(0, 0, 0))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, quality=92)
