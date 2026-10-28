# Build and run EOH 0.4.1 from source

EOH's desktop entry point targets Windows x64 and Python 3.12. The public repository contains no sample images or review records. Scientific results require independently calibrated images and human review.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-eoh.txt
python -B comment1_colocation/code/portable_entry.py
```

For optional NVIDIA GPU acceleration in a source environment, install a compatible CUDA 12 toolkit and `cupy-cuda12x==13.6.0`; without it, the application falls back to the CPU. In source mode, select an output folder on the same drive as the repository. Existing cases remain compatible when their original output folder is selected.

For a Windows bundle, install `requirements-build-windows.txt` and run `python comment1_colocation/code/build_portable.py`. The builder generates a new versioned directory in `releases/`; it does not overwrite a previous build. Its GPU bundle searches both Conda `Library/bin` and the NVIDIA pip package DLL directories. Building requires a Windows environment and the CUDA redistributable components; see their license notices.

The published 0.4.1 executable was built and tested in a Conda Python 3.12.3 environment with CuPy 13.6.0, CUDA NVRTC 12.9.86, PyMuPDF 1.26.4 and MuPDF 1.26.7. Runtime validation reported SciPy 1.16.2, although the original installed-package metadata also listed SciPy 1.13.1; this discrepancy is recorded rather than presented as a fully locked environment. A rebuild from pip packages can differ in binary packaging and is not asserted to be byte-identical.

Some `verify_*` scripts are development checks for the original local research cases and expect private image data and task-specific temporary paths; those inputs are intentionally not published. The release's non-data GUI self-check is `EOH.exe --check <output.json>` with `BSE_COMPUTE_BACKEND=cpu`. The project and upstream source references are in [SOURCE.md](SOURCE.md).
