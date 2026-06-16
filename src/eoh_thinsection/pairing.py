from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from skimage import color, feature, measure, transform

from .io import ImageRecord, pairing_key


def build_pairs(records: list[ImageRecord]) -> list[dict[str, str]]:
    grouped: dict[str, dict[str, ImageRecord]] = {}
    for record in records:
        parent = str(Path(record.relative_path).parent).replace("\\", "/")
        key = f"{parent}/{pairing_key(record.filename)}"
        group = grouped.setdefault(key, {})
        lowered = record.filename.lower()
        if "_ppl" in lowered or "-ppl" in lowered:
            group["ppl"] = record
        elif "_xpl" in lowered or "-xpl" in lowered:
            group["xpl"] = record
        elif "reflect" in lowered or "_rl" in lowered:
            group["reflected"] = record

    rows: list[dict[str, str]] = []
    pair_idx = 1
    for key, group in sorted(grouped.items()):
        if "ppl" not in group and "xpl" not in group:
            continue
        ppl = group.get("ppl")
        xpl = group.get("xpl")
        reflected = group.get("reflected")
        confidence = "High" if ppl and xpl else "Low"
        reason = "Filename stem matches after replacing PPL/XPL token."
        if not (ppl and xpl):
            reason = "Incomplete mode group; pair requires manual review."
        rows.append(
            {
                "pair_id": f"PAIR{pair_idx:03d}",
                "pair_key": key,
                "ppl_image": ppl.relative_path if ppl else "",
                "xpl_image": xpl.relative_path if xpl else "",
                "reflected_image": reflected.relative_path if reflected else "",
                "ppl_filename": ppl.filename if ppl else "",
                "xpl_filename": xpl.filename if xpl else "",
                "reflected_filename": reflected.filename if reflected else "",
                "confidence": confidence,
                "reason": reason,
                "registration_possible": "Likely" if ppl and xpl else "Unknown",
                "notes": "Verify field of view before quantitative paired-image interpretation.",
            }
        )
        pair_idx += 1
    return rows


def registration_qc(
    pair_rows: list[dict[str, str]],
    image_by_relative_path: dict[str, Path],
    max_pairs: int = 20,
) -> list[dict[str, str | int | float]]:
    rows: list[dict[str, str | int | float]] = []
    for row in pair_rows[:max_pairs]:
        ppl_rel = row.get("ppl_image", "")
        xpl_rel = row.get("xpl_image", "")
        if not ppl_rel or not xpl_rel:
            continue
        try:
            fixed = _load_gray_small(image_by_relative_path[ppl_rel])
            moving = _load_gray_small(image_by_relative_path[xpl_rel])
            result = _estimate_similarity(fixed, moving)
            rows.append(
                {
                    "pair_id": row["pair_id"],
                    "ppl_image": ppl_rel,
                    "xpl_image": xpl_rel,
                    **result,
                }
            )
        except Exception as exc:  # keep workflow robust for huge or unusual files
            rows.append(
                {
                    "pair_id": row["pair_id"],
                    "ppl_image": ppl_rel,
                    "xpl_image": xpl_rel,
                    "registration_status": "failed",
                    "keypoints_fixed": 0,
                    "keypoints_moving": 0,
                    "matches": 0,
                    "inliers": 0,
                    "inlier_fraction": 0.0,
                    "notes": f"{type(exc).__name__}: {exc}",
                }
            )
    return rows


def _load_gray_small(path: Path, max_size: int = 1200) -> np.ndarray:
    image = Image.open(path).convert("RGB")
    width, height = image.size
    scale = min(max_size / max(width, height), 1.0)
    if scale < 1.0:
        image = image.resize((int(width * scale), int(height * scale)))
    arr = np.asarray(image).astype(np.float32) / 255.0
    return color.rgb2gray(arr)


def _estimate_similarity(
    fixed: np.ndarray, moving: np.ndarray
) -> dict[str, str | int | float]:
    extractor_fixed = feature.ORB(n_keypoints=500, fast_threshold=0.08)
    extractor_moving = feature.ORB(n_keypoints=500, fast_threshold=0.08)
    extractor_fixed.detect_and_extract(fixed)
    extractor_moving.detect_and_extract(moving)
    keypoints_fixed = extractor_fixed.keypoints
    keypoints_moving = extractor_moving.keypoints
    descriptors_fixed = extractor_fixed.descriptors
    descriptors_moving = extractor_moving.descriptors

    matches = feature.match_descriptors(
        descriptors_fixed, descriptors_moving, cross_check=True
    )
    if len(matches) < 8:
        return {
            "registration_status": "insufficient_matches",
            "keypoints_fixed": int(len(keypoints_fixed)),
            "keypoints_moving": int(len(keypoints_moving)),
            "matches": int(len(matches)),
            "inliers": 0,
            "inlier_fraction": 0.0,
            "notes": "Too few ORB matches for robust registration.",
        }

    src = keypoints_moving[matches[:, 1]][:, ::-1]
    dst = keypoints_fixed[matches[:, 0]][:, ::-1]
    _, inliers = measure.ransac(
        (src, dst),
        transform.SimilarityTransform,
        min_samples=4,
        residual_threshold=3,
        max_trials=100,
    )
    inlier_count = int(np.sum(inliers)) if inliers is not None else 0
    fraction = inlier_count / max(len(matches), 1)
    status = "good_candidate" if inlier_count >= 12 and fraction >= 0.20 else "manual_review"
    return {
        "registration_status": status,
        "keypoints_fixed": int(len(keypoints_fixed)),
        "keypoints_moving": int(len(keypoints_moving)),
        "matches": int(len(matches)),
        "inliers": inlier_count,
        "inlier_fraction": round(float(fraction), 4),
        "notes": "Registration QC is a candidate only; inspect overlay before measurement.",
    }
