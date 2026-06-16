from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


@dataclass(frozen=True)
class ImageRecord:
    image_id: str
    path: Path
    filename: str
    relative_path: str


def scan_images(input_dir: Path) -> list[ImageRecord]:
    input_dir = input_dir.resolve()
    paths = sorted(
        p
        for p in input_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )
    records: list[ImageRecord] = []
    for idx, path in enumerate(paths, start=1):
        records.append(
            ImageRecord(
                image_id=f"IMG{idx:03d}",
                path=path,
                filename=path.name,
                relative_path=path.relative_to(input_dir).as_posix(),
            )
        )
    return records


def likely_mode_from_name(filename: str) -> str:
    lowered = filename.lower()
    if any(token in lowered for token in ["_ppl", "-ppl", " ppl", "plane"]):
        return "PPL"
    if any(token in lowered for token in ["_xpl", "-xpl", " xpl", "cross"]):
        return "XPL"
    if any(token in lowered for token in ["reflect", "reflected", "_rl", "-rl"]):
        return "reflected_or_folder_context"
    return "unknown"


def pairing_key(filename: str) -> str:
    lowered = filename.lower()
    stem = Path(filename).stem.lower()
    for token in ["_ppl", "-ppl", " ppl"]:
        stem = stem.replace(token, "_mode")
    for token in ["_xpl", "-xpl", " xpl"]:
        stem = stem.replace(token, "_mode")
    for token in ["_rl", "-rl", "_reflected", "-reflected"]:
        stem = stem.replace(token, "_mode")
    return stem
