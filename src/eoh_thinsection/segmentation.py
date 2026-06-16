from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image
from skimage import feature, measure, morphology
from skimage.color import rgb2gray
from skimage.filters import threshold_otsu


@dataclass
class DarkRegionStat:
    label: int
    area_px: int
    equivalent_diameter_px: float
    eccentricity: float
    solidity: float
    bbox_xyxy: tuple[int, int, int, int]
    centroid_xy: tuple[float, float]


@dataclass
class FeatureSummary:
    dark_fraction: float
    dark_region_count: int
    dark_region_area_px: int
    median_dark_equivalent_diameter_px: float | None
    linear_edge_fraction: float
    candidate_fracture_or_vein_note: str


def segment_dark_regions(
    image: Image.Image, max_size: int = 1800, max_regions: int = 600
) -> tuple[np.ndarray, list[DarkRegionStat]]:
    arr, scale_back = _rgb_array_for_analysis(image, max_size=max_size)
    gray = rgb2gray(arr)
    try:
        otsu = threshold_otsu(gray)
    except ValueError:
        otsu = 0.5
    threshold = min(0.28, otsu * 0.75)
    mask = gray < threshold

    # Exclude the lower-right scale-bar overlay region from dark-particle stats.
    height, width = gray.shape
    mask[int(height * 0.88) :, int(width * 0.50) :] = False
    mask = morphology.remove_small_objects(mask, min_size=20)
    mask = morphology.binary_opening(mask, morphology.disk(1))

    labels = measure.label(mask)
    stats: list[DarkRegionStat] = []
    props = sorted(measure.regionprops(labels), key=lambda prop: prop.area, reverse=True)
    for prop in props[:max_regions]:
        minr, minc, maxr, maxc = prop.bbox
        if prop.area < 20:
            continue
        area_px = int(round(float(prop.area) * scale_back * scale_back))
        equivalent_diameter_px = float(prop.equivalent_diameter) * scale_back
        x1 = int(round(minc * scale_back))
        y1 = int(round(minr * scale_back))
        x2 = int(round(maxc * scale_back))
        y2 = int(round(maxr * scale_back))
        cx = float(prop.centroid[1]) * scale_back
        cy = float(prop.centroid[0]) * scale_back
        stats.append(
            DarkRegionStat(
                label=int(prop.label),
                area_px=area_px,
                equivalent_diameter_px=equivalent_diameter_px,
                eccentricity=float(prop.eccentricity),
                solidity=float(prop.solidity),
                bbox_xyxy=(x1, y1, x2, y2),
                centroid_xy=(cx, cy),
            )
        )
    return labels, stats


def summarize_features(image: Image.Image, dark_stats: list[DarkRegionStat]) -> FeatureSummary:
    arr, _ = _rgb_array_for_analysis(image, max_size=1800)
    gray = rgb2gray(arr)
    height, width = gray.shape
    original_width, original_height = image.size
    area = original_width * original_height
    try:
        otsu = threshold_otsu(gray)
    except ValueError:
        otsu = 0.5
    threshold = min(0.28, otsu * 0.75)
    dark_mask = gray < threshold
    dark_mask[int(height * 0.88) :, int(width * 0.50) :] = False
    dark_fraction = float(np.mean(dark_mask))
    dark_area = int(round(dark_fraction * area))
    diameters = [s.equivalent_diameter_px for s in dark_stats]

    edges = feature.canny(gray, sigma=2.0)
    edges[int(height * 0.88) :, int(width * 0.50) :] = False
    edge_fraction = float(np.mean(edges))
    if edge_fraction > 0.08:
        note = "High edge density; may support fracture/vein candidate review, but includes grain boundaries and texture."
    elif edge_fraction > 0.03:
        note = "Moderate edge density; candidate linear features should be manually reviewed."
    else:
        note = "Low edge density by current automated pass."

    return FeatureSummary(
        dark_fraction=float(dark_fraction),
        dark_region_count=len(dark_stats),
        dark_region_area_px=int(dark_area),
        median_dark_equivalent_diameter_px=(
            float(np.median(diameters)) if diameters else None
        ),
        linear_edge_fraction=edge_fraction,
        candidate_fracture_or_vein_note=note,
    )


def _rgb_array_for_analysis(
    image: Image.Image, max_size: int
) -> tuple[np.ndarray, float]:
    image = image.convert("RGB")
    width, height = image.size
    largest = max(width, height)
    if largest <= max_size:
        return np.asarray(image).astype(np.float32) / 255.0, 1.0
    scale = max_size / largest
    resized = image.resize((int(width * scale), int(height * scale)))
    scale_back = 1.0 / scale
    return np.asarray(resized).astype(np.float32) / 255.0, scale_back
