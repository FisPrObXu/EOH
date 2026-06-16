# EOH Thin-Section Assistant

EOH is short for **Eye of Heaven**. This private research codebase is being developed to reproduce and extend a conservative thin-section image-analysis workflow for Brothers Volcano / IODP Expedition 376 samples.

The project does **not** claim final mineral identification from images alone. It is designed to organize image metadata, detect scale bars, pair PPL/XPL fields, generate QC outputs, segment candidate domains, and prepare human-reviewed basemaps for follow-up petrography and laboratory analysis.

## What It Does

- Recursively scans `.jpg`, `.jpeg`, `.png`, `.tif`, and `.tiff` images.
- Infers likely PPL/XPL/reflected/unknown mode from filenames.
- Detects red lower-right scale bars using color, geometry, and position constraints.
- Estimates `um_per_px` when both bar length and scale label can be inferred.
- Builds PPL/XPL pairing tables from filename stems.
- Computes conservative QC metrics: focus proxy, illumination variation, color balance, dark-domain fraction.
- Creates thumbnails, scale-bar QC crops, and annotated overview sheets.
- Generates candidate dark-domain statistics for opaque grains / pores / resin / shadows.
- Produces feature summaries for candidate fractures/linear features and region statistics.
- Writes conservative CSV tables and a Markdown report.

## Install

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

If editable install is not desired:

```powershell
python -m pip install -r requirements.txt
```

OpenCV is optional. The current workflow uses `scikit-image` for the core implementation and will keep running if `cv2` is missing.

## Run

Example using the current local data layout:

```powershell
python -m eoh_thinsection --input .\JBXu_TS --output .\thinsection_assessment_outputs --overwrite
```

Equivalent after editable install:

```powershell
eoh-thinsection --input .\JBXu_TS --output .\thinsection_assessment_outputs --overwrite
```

The default run writes:

- `thinsection_image_assessment_report.md`
- `image_qc.csv`
- `scale_bar_measurements.csv`
- `image_pairs.csv`
- `registration_qc.csv`
- `dark_domain_stats.csv`
- `feature_summary.csv`
- `analysis_feasibility.csv`
- `impossible_or_not_recommended.csv`
- `phenomenon_followup.csv`
- `human_vs_computer.csv`
- `thumbnails/`
- `scale_bar_qc/`
- `annotated_overview/`

## GitHub Privacy

This repository is intended to be private because it may contain unpublished research images and interpretations. The `.gitignore` excludes raw image folders and generated output folders by default. Commit the code first; add data only after deciding whether Git LFS or a separate private data repository is more appropriate.

## Git Workflow After Running

Check local changes:

```powershell
git status -sb
```

Stage code and documentation:

```powershell
git add .gitignore README.md docs pyproject.toml requirements.txt src
```

Commit:

```powershell
git commit -m "Build EOH thin-section analysis workflow"
```

If the private GitHub repository already exists:

```powershell
git remote add origin https://github.com/FisPrObXu/EOH.git
git branch -M main
git push -u origin main
```

If GitHub CLI is installed and authenticated, create a private repository and push in one step:

```powershell
gh repo create FisPrObXu/EOH --private --source . --remote origin --push --description "EOH (Eye of Heaven): codebase for reproducing and assisting thin-section analysis"
```

If GitHub CLI is not installed, create a private repository named `EOH` in the GitHub web interface, then run the `git remote add` and `git push` commands above.

## Conservative Interpretation Policy

Use image-derived labels as candidates only:

- "candidate plagioclase-shaped domain"
- "feldspar pseudomorph candidate"
- "opaque grains / possible sulfide, oxide, pore, or resin"
- "clay-like aggregate"
- "sulfate-like phase candidate"
- "silicified or quartz-rich candidate domain"

Do not use this tool alone to determine final mineral species, feldspar An-Ab-Or composition, isotope values, fluid-inclusion origin, or fluid-source switching time scales.
