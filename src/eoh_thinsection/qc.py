from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image
from skimage.color import rgb2gray
from skimage.filters import laplace, threshold_otsu


@dataclass
class ImageMetrics:
    width_px: int
    height_px: int
    color_channels: int
    focus_proxy: float
    illumination_cv: float
    color_balance_delta: float
    dark_fraction: float
    focus_quality: str
    illumination_quality: str
    color_balance_quality: str
    segmentation_suitability: str
    publication_suitability: str


def compute_metrics(image: Image.Image) -> ImageMetrics:
    arr = np.asarray(image.convert("RGB")).astype(np.float32) / 255.0
    height, width = arr.shape[:2]
    gray = rgb2gray(arr)
    focus_proxy = float(np.var(laplace(gray)) * 10000)
    mean_gray = float(np.mean(gray))
    illumination_cv = float(np.std(gray) / max(mean_gray, 1e-6))
    channel_means = np.mean(arr.reshape(-1, 3), axis=0)
    color_balance_delta = float(np.max(channel_means) - np.min(channel_means))

    try:
        otsu = threshold_otsu(gray)
    except ValueError:
        otsu = 0.5
    dark_threshold = min(0.28, otsu * 0.75)
    dark_fraction = float(np.mean(gray < dark_threshold))

    focus_quality = _bucket(focus_proxy, high=7.0, medium=3.0)
    illumination_quality = _reverse_bucket(illumination_cv, high=0.10, medium=0.20)
    color_balance_quality = _reverse_bucket(color_balance_delta, high=0.06, medium=0.14)
    segmentation_suitability = _combine_for_segmentation(
        focus_quality, illumination_quality, dark_fraction
    )
    publication_suitability = _combine_for_publication(
        focus_quality, illumination_quality, color_balance_quality
    )
    return ImageMetrics(
        width_px=width,
        height_px=height,
        color_channels=3,
        focus_proxy=focus_proxy,
        illumination_cv=illumination_cv,
        color_balance_delta=color_balance_delta,
        dark_fraction=dark_fraction,
        focus_quality=focus_quality,
        illumination_quality=illumination_quality,
        color_balance_quality=color_balance_quality,
        segmentation_suitability=segmentation_suitability,
        publication_suitability=publication_suitability,
    )


def _bucket(value: float, high: float, medium: float) -> str:
    if value >= high:
        return "High"
    if value >= medium:
        return "Medium"
    return "Low"


def _reverse_bucket(value: float, high: float, medium: float) -> str:
    if value <= high:
        return "High"
    if value <= medium:
        return "Medium"
    return "Low"


def _combine_for_segmentation(
    focus_quality: str, illumination_quality: str, dark_fraction: float
) -> str:
    if focus_quality == "Low" or illumination_quality == "Low":
        return "Medium"
    if 0.001 <= dark_fraction <= 0.65:
        return "High"
    return "Medium"


def _combine_for_publication(
    focus_quality: str, illumination_quality: str, color_balance_quality: str
) -> str:
    if "Low" in {focus_quality, illumination_quality, color_balance_quality}:
        return "Low"
    if "Medium" in {focus_quality, illumination_quality, color_balance_quality}:
        return "Medium"
    return "High"
