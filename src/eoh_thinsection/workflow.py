from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

import pandas as pd
from PIL import Image, ImageDraw

from .io import ImageRecord, likely_mode_from_name, scan_images
from .pairing import build_pairs, registration_qc
from .qc import compute_metrics
from .scale_bar import ScaleBarDetection, detect_red_scale_bar, save_scale_bar_qc
from .segmentation import DarkRegionStat, segment_dark_regions, summarize_features
from .static_tables import (
    analysis_feasibility_rows,
    human_vs_computer_rows,
    impossible_or_not_recommended_rows,
    phenomenon_followup_rows,
)


@dataclass
class WorkflowSummary:
    processed_images: int
    generated_files: list[Path]
    top_findings: list[str]
    top_limitations: list[str]
    top_followups: list[str]


def run_workflow(
    input_dir: Path,
    output_dir: Path,
    overwrite: bool = False,
    max_registration_pairs: int = 20,
) -> WorkflowSummary:
    input_dir = input_dir.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    for subdir in ["thumbnails", "scale_bar_qc", "annotated_overview"]:
        path = output_dir / subdir
        if overwrite and path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

    records = scan_images(input_dir)
    image_by_relative_path = {record.relative_path: record.path for record in records}

    qc_rows: list[dict[str, object]] = []
    scale_rows: list[dict[str, object]] = []
    feature_rows: list[dict[str, object]] = []
    dark_rows: list[dict[str, object]] = []
    thumbnail_paths: list[Path] = []
    overview_items: list[tuple[str, Path]] = []

    for record in records:
        image = Image.open(record.path).convert("RGB")
        metrics = compute_metrics(image)
        detection = detect_red_scale_bar(image, record.filename)
        likely_mode = likely_mode_from_name(record.filename)

        thumb_path = output_dir / "thumbnails" / f"{record.image_id}_{record.path.stem}.jpg"
        save_thumbnail(image, thumb_path)
        thumbnail_paths.append(thumb_path)
        overview_items.append((f"{record.image_id} | {record.relative_path}", thumb_path))

        scale_qc_path = (
            output_dir
            / "scale_bar_qc"
            / f"{record.image_id}_{record.path.stem}_scale_bar_qc.jpg"
        )
        save_scale_bar_qc(
            image=image,
            detection=detection,
            out_path=scale_qc_path,
            title=f"{record.image_id} | {record.relative_path}",
        )

        labels, dark_stats = segment_dark_regions(image)
        feature_summary = summarize_features(image, dark_stats)

        qc_rows.append(_qc_row(record, likely_mode, metrics, detection))
        scale_rows.append(_scale_row(record, detection))
        feature_rows.append(
            {
                "image_id": record.image_id,
                "filename": record.filename,
                "relative_path": record.relative_path,
                "likely_mode": likely_mode,
                "dark_fraction": round(feature_summary.dark_fraction, 6),
                "dark_region_count": feature_summary.dark_region_count,
                "dark_region_area_px": feature_summary.dark_region_area_px,
                "median_dark_equivalent_diameter_px": _round_or_blank(
                    feature_summary.median_dark_equivalent_diameter_px, 3
                ),
                "linear_edge_fraction": round(feature_summary.linear_edge_fraction, 6),
                "candidate_fracture_or_vein_note": feature_summary.candidate_fracture_or_vein_note,
                "interpretation_warning": _feature_warning(likely_mode),
            }
        )
        dark_rows.extend(_dark_rows(record, dark_stats))

    pair_rows = build_pairs(records)
    registration_rows = registration_qc(
        pair_rows,
        image_by_relative_path=image_by_relative_path,
        max_pairs=max_registration_pairs,
    )

    overview_paths = save_overview_pages(overview_items, output_dir / "annotated_overview")

    generated_files = _write_tables(
        output_dir=output_dir,
        qc_rows=qc_rows,
        scale_rows=scale_rows,
        pair_rows=pair_rows,
        registration_rows=registration_rows,
        feature_rows=feature_rows,
        dark_rows=dark_rows,
    )
    generated_files.extend(thumbnail_paths)
    generated_files.extend(overview_paths)
    generated_files.extend(sorted((output_dir / "scale_bar_qc").glob("*.jpg")))

    report_path = output_dir / "thinsection_image_assessment_report.md"
    report_path.write_text(
        build_report(
            records=records,
            qc_rows=qc_rows,
            scale_rows=scale_rows,
            pair_rows=pair_rows,
            registration_rows=registration_rows,
            feature_rows=feature_rows,
            generated_files=generated_files,
        ),
        encoding="utf-8",
    )
    generated_files.insert(0, report_path)

    top_findings = [
        f"Processed {len(records)} image files from {input_dir}.",
        f"Detected visible red scale bars in {sum(1 for r in scale_rows if r['has_scale_bar'] == 'Yes')} images.",
        f"Built {len(pair_rows)} filename-derived PPL/XPL candidate pairs.",
        "Generated candidate dark-domain and linear-feature statistics for human review.",
        "Generated QC crops, thumbnails, overview pages, and conservative follow-up tables.",
    ]
    top_limitations = [
        "Scale labels are inferred from visible labels/filename magnification rules and should be verified before publication-scale measurements.",
        "Use reflected-light or BSE/EDS analysis to classify opaque and dark domains.",
        "PPL/XPL registration produces candidate alignments for QC.",
        "Mineral species, clay types, sulfate species, and feldspar composition require follow-up analysis.",
        "Combine textures, isotope analyses and chronology to investigate fluid-source switching and timing.",
    ]
    top_followups = [
        "Manual petrographic review of candidate domains and scale-bar calibrations.",
        "Reflected-light microscopy and SEM-BSE/EDS for opaque and replacement domains.",
        "EPMA for manually confirmed feldspar or alunite/sulfate candidates.",
        "Raman/XRD for clay-like, sulfate-like, alunite/natroalunite, and silica/feldspar candidates.",
        "SEM-CL, fluid inclusion work, SIMS delta34S, and Sr/Ra-series analyses only after textural generations are confirmed.",
    ]
    return WorkflowSummary(
        processed_images=len(records),
        generated_files=generated_files,
        top_findings=top_findings,
        top_limitations=top_limitations,
        top_followups=top_followups,
    )


def _qc_row(
    record: ImageRecord,
    likely_mode: str,
    metrics,
    detection: ScaleBarDetection,
) -> dict[str, object]:
    return {
        "image_id": record.image_id,
        "filename": record.filename,
        "relative_path": record.relative_path,
        "width_px": metrics.width_px,
        "height_px": metrics.height_px,
        "color_channels": metrics.color_channels,
        "likely_mode": likely_mode,
        "has_scale_bar": "Yes" if detection.has_scale_bar else "No",
        "scale_bar_text": detection.scale_bar_text,
        "estimated_um_per_px": _round_or_blank(detection.estimated_um_per_px, 6),
        "focus_quality": metrics.focus_quality,
        "illumination_quality": metrics.illumination_quality,
        "color_balance_quality": metrics.color_balance_quality,
        "suitable_for_segmentation": metrics.segmentation_suitability,
        "suitable_for_pairing": "High" if likely_mode in {"PPL", "XPL"} else "Medium",
        "suitable_for_publication": metrics.publication_suitability,
        "notes": (
            f"focus_proxy={metrics.focus_proxy:.3f}; "
            f"illumination_cv={metrics.illumination_cv:.3f}; "
            f"dark_fraction={metrics.dark_fraction:.4f}; "
            f"scale_bar_confidence={detection.confidence}; {detection.notes}"
        ),
    }


def _scale_row(record: ImageRecord, detection: ScaleBarDetection) -> dict[str, object]:
    bbox = detection.bbox_xyxy or ("", "", "", "")
    return {
        "image_id": record.image_id,
        "filename": record.filename,
        "relative_path": record.relative_path,
        "has_scale_bar": "Yes" if detection.has_scale_bar else "No",
        "scale_bar_text": detection.scale_bar_text,
        "label_um": _round_or_blank(detection.label_um, 6),
        "bar_length_px": _round_or_blank(detection.bar_length_px, 3),
        "estimated_um_per_px": _round_or_blank(detection.estimated_um_per_px, 6),
        "confidence": detection.confidence,
        "bbox_x1": bbox[0],
        "bbox_y1": bbox[1],
        "bbox_x2": bbox[2],
        "bbox_y2": bbox[3],
        "method": detection.method,
        "notes": detection.notes,
    }


def _dark_rows(record: ImageRecord, dark_stats: list[DarkRegionStat]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for stat in dark_stats:
        x1, y1, x2, y2 = stat.bbox_xyxy
        cx, cy = stat.centroid_xy
        rows.append(
            {
                "image_id": record.image_id,
                "filename": record.filename,
                "relative_path": record.relative_path,
                "domain_id": f"{record.image_id}_DARK_{stat.label:05d}",
                "area_px": stat.area_px,
                "equivalent_diameter_px": round(stat.equivalent_diameter_px, 3),
                "eccentricity": round(stat.eccentricity, 4),
                "solidity": round(stat.solidity, 4),
                "centroid_x": round(cx, 2),
                "centroid_y": round(cy, 2),
                "bbox_x1": x1,
                "bbox_y1": y1,
                "bbox_x2": x2,
                "bbox_y2": y2,
                "safe_interpretation": "opaque/dark candidate; possible opaque mineral, pore, resin, crack, inclusion, or shadow",
                "requires_review": "Yes",
            }
        )
    return rows


def _write_tables(
    output_dir: Path,
    qc_rows: list[dict[str, object]],
    scale_rows: list[dict[str, object]],
    pair_rows: list[dict[str, object]],
    registration_rows: list[dict[str, object]],
    feature_rows: list[dict[str, object]],
    dark_rows: list[dict[str, object]],
) -> list[Path]:
    tables = {
        "image_qc.csv": qc_rows,
        "scale_bar_measurements.csv": scale_rows,
        "image_pairs.csv": pair_rows,
        "registration_qc.csv": registration_rows,
        "feature_summary.csv": feature_rows,
        "dark_domain_stats.csv": dark_rows,
        "analysis_feasibility.csv": analysis_feasibility_rows(),
        "impossible_or_not_recommended.csv": impossible_or_not_recommended_rows(),
        "phenomenon_followup.csv": phenomenon_followup_rows(),
        "human_vs_computer.csv": human_vs_computer_rows(),
    }
    paths: list[Path] = []
    for filename, rows in tables.items():
        path = output_dir / filename
        pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8")
        paths.append(path)
    return paths


def _feature_warning(likely_mode: str) -> str:
    if likely_mode == "XPL":
        return (
            "XPL dark_fraction describes image darkness; use paired "
            "PPL, reflected-light or BSE views for class review."
        )
    return (
        "Candidate image features only; dark domains may include opaque minerals, pores, "
        "resin, cracks, inclusions, or shadows. Mineral identity and paragenesis require expert review."
    )


def save_thumbnail(image: Image.Image, out_path: Path, max_size: tuple[int, int] = (420, 280)) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    thumb = image.copy()
    thumb.thumbnail(max_size)
    canvas = Image.new("RGB", max_size, "white")
    x = (max_size[0] - thumb.width) // 2
    y = (max_size[1] - thumb.height) // 2
    canvas.paste(thumb, (x, y))
    canvas.save(out_path, quality=90)


def save_overview_pages(items: list[tuple[str, Path]], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    per_page = 12
    cols = 3
    tile_w, tile_h = 460, 360
    for page_index, start in enumerate(range(0, len(items), per_page), start=1):
        page_items = items[start : start + per_page]
        rows = (len(page_items) + cols - 1) // cols
        canvas = Image.new("RGB", (cols * tile_w, rows * tile_h), "white")
        draw = ImageDraw.Draw(canvas)
        for idx, (label, path) in enumerate(page_items):
            img = Image.open(path).convert("RGB")
            x = (idx % cols) * tile_w
            y = (idx // cols) * tile_h
            canvas.paste(img, (x + 20, y + 20))
            draw.text((x + 20, y + 310), label[:68], fill=(0, 0, 0))
        out_path = output_dir / f"annotated_overview_page_{page_index:02d}.jpg"
        canvas.save(out_path, quality=92)
        paths.append(out_path)
    return paths


def build_report(
    records: list[ImageRecord],
    qc_rows: list[dict[str, object]],
    scale_rows: list[dict[str, object]],
    pair_rows: list[dict[str, object]],
    registration_rows: list[dict[str, object]],
    feature_rows: list[dict[str, object]],
    generated_files: list[Path],
) -> str:
    mode_counts = pd.Series([row["likely_mode"] for row in qc_rows]).value_counts().to_dict()
    scale_count = sum(1 for row in scale_rows if row["has_scale_bar"] == "Yes")
    high_pair_count = sum(1 for row in pair_rows if row["confidence"] == "High")
    registration_good = sum(
        1 for row in registration_rows if row.get("registration_status") == "good_candidate"
    )
    mean_dark = (
        sum(float(row["dark_fraction"]) for row in feature_rows) / len(feature_rows)
        if feature_rows
        else 0.0
    )
    generated_short = "\n".join(
        f"- `{path.relative_to(generated_files[0].parent).as_posix()}`"
        if path.is_relative_to(generated_files[0].parent)
        else f"- `{path}`"
        for path in generated_files[:30]
    )
    if len(generated_files) > 30:
        generated_short += f"\n- ... {len(generated_files) - 30} additional generated files"

    return f"""# Thin Section Image Assessment Report

## Executive Summary

This EOH (Eye of Heaven) workflow scanned the current thin-section image directory and generated conservative image-analysis support outputs. The images can support metadata organization, PPL/XPL filename pairing, visible red scale-bar detection, QC review, thumbnail and basemap generation, dark-domain candidate statistics, and preliminary target selection for manual petrography and follow-up laboratory work.

The workflow reports image-derived candidates for clast-matrix-vein-vug-pseudomorph mapping and microtextural review. Mineral identification, chemistry, isotope values and fluid-source interpretation use petrographic and laboratory observations.

Most recommended next step: manually review the scale-bar QC crops and candidate domains, then choose a small set of representative fields for reflected-light microscopy, SEM-BSE/EDS, EPMA, Raman/XRD, SEM-CL, SIMS sulfur isotope work, Sr isotope work, and fluid-inclusion analysis as appropriate.

## Dataset Inventory

- Images processed: {len(records)}
- Estimated modes: {mode_counts}
- Images with visible red scale-bar evidence: {scale_count}
- Filename-derived high-confidence PPL/XPL pairs: {high_pair_count}
- Registration QC good candidates: {registration_good}
- Mean dark-domain candidate area fraction: {mean_dark:.4f}

Scale-bar detection now uses a lower-right red-overlay detector constrained by color, geometry, position, and high aspect ratio. It also infers expected scale labels from the observed magnification tokens in filenames where available. Use the measured scale-bar label and endpoints for navigation and quantitative calibration.

Dark-domain statistics describe image darkness in PPL, reflected-light and XPL views; paired-image review supports material classification.

## Image Analysis Workflow

Automated work: image inventory, mode inference from filenames, PPL/XPL candidate pairing, red scale-bar candidate detection, thumbnails, QC crops, overview sheets, dark-domain candidate masks, region statistics, and conservative report tables.

Semi-automated work: PPL/XPL registration QC, clast-matrix-vein-vug-pseudomorph candidate mapping, candidate fracture/vein edge-density review, numbered microdomain maps, and basemaps for EPMA, SEM-EDS, Raman, SIMS, SEM-CL, or fluid-inclusion target selection.

Manual review required: mineral identity, textural paragenesis, replacement versus relict interpretation, valid points for feldspar composition, sulfide/sulfate crosscutting relationships, and final analytical prioritization.

## Complementary Petrographic Analyses

- Review candidate plagioclase-shaped domains with rotation-stage optical observation and BSE/EDS or EPMA.
- Classify segmented opaque grains using reflected-light microscopy and SEM-EDS.
- Use mineralogical and spectral measurements to distinguish clay, sulfate, quartz and feldspar species.
- Combine preliminary textural paragenesis with mineral chemistry and isotope analyses to investigate fluid-source switching.
- Use dating and independent temporal constraints on mineral generations to study switching timescales.

## Observed Candidate Phenomena

Automated outputs record candidate dark domains, candidate linear features, possible clast/matrix contrasts, candidate feldspar-shaped or tabular domains, and visible scale-bar overlays. These are navigation aids. They should be reviewed in paired PPL/XPL views before being used as analytical targets.

## Recommended Follow-Up Analyses

- SEM-BSE and SEM-EDS for dark domains, replacement textures, sulfate-like, silica-like, and clay-like candidates.
- Reflected-light petrography before assigning dark transmitted-light grains to pyrite, oxides, or other opaque phases.
- EPMA/WDS only on manually confirmed relict feldspar, alunite-group, sulfate, or other suitable phases.
- Raman/XRD for clay-like aggregates, alunite/natroalunite candidates, sulfate-like phases, and fine-grained silica/feldspar candidates.
- SEM-CL and fluid inclusion work for manually confirmed quartz/silica veins with growth-zone relationships.
- SIMS delta34S, Sr isotope, and Ra-series analyses only after textural generations and phase identities are confirmed.

## Human-Computer Workflow

Computer-led tasks: metadata organization, pair tables, scale-bar candidate detection, thumbnails, QC crops, candidate masks, region statistics, and basemap production.

Human-led tasks: final mineral interpretation, E0-E5 or equivalent paragenetic sequence construction, valid EPMA/SIMS/LA-ICP-MS point selection, fluid-inclusion origin classification, and fluid-source switching interpretation.

Human-in-the-loop mode is best: the computer proposes candidate domains and measurements; the petrographer reviews and edits polygons/classes; confirmed targets then guide laboratory analysis.

## Candidate Descriptions

Candidate descriptions include:

- "candidate plagioclase-shaped domain"
- "feldspar pseudomorph candidate"
- "opaque grains / possible sulfide, oxide, pore, or resin"
- "clay-like aggregate"
- "probable sulfate-like phase pending BSE/EDS or Raman/XRD"
- "silicified matrix or quartz-rich candidate domain"
- "preliminary textural generation pending chemical and chronological confirmation"

## Open-Source Methods Referenced

- scikit-image thresholding, morphology, ORB/RANSAC, and regionprops documentation: https://scikit-image.org/docs/stable/
- OpenCV feature matching and homography concepts for optional future registration backends: https://docs.opencv.org/
- Petrographic PPL/XPL segmentation examples: https://github.com/jbardelli/Petrographic-Image-Segmentation
- Deep mineralogical segmentation example: https://github.com/ltracegeo/deep-mineralogical-segmentation

## Generated Files

{generated_short}
"""


def _round_or_blank(value: float | None, digits: int) -> float | str:
    if value is None:
        return ""
    return round(float(value), digits)
