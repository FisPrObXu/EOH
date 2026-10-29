# Build and run EOH 0.4.1 from source

EOH's desktop entry point targets Windows x64 and Python 3.12. The repository includes an illustrated sample and the application source.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-eoh.txt
python -B comment1_colocation/code/portable_entry.py
```

For NVIDIA GPU acceleration in a source environment, install a compatible CUDA 12 toolkit and `cupy-cuda12x==13.6.0`. The compute selector also offers a CPU mode. In source mode, select an output folder on the same drive as the repository. Existing cases remain compatible when their original output folder is selected.

For a Windows bundle, install `requirements-build-windows.txt` and run `python comment1_colocation/code/build_portable.py`. The builder generates a versioned directory in `releases/`. Its GPU bundle searches both Conda `Library/bin` and the NVIDIA pip package DLL directories. Building requires a Windows environment and the CUDA redistributable components; see their license notices.

The published 0.4.1 executable was built and tested in a Conda Python 3.12.3 environment with CuPy 13.6.0, CUDA NVRTC 12.9.86, PyMuPDF 1.26.4 and MuPDF 1.26.7. The recorded runtime and package metadata are available in the distribution’s component manifests.

The `verify_*` scripts exercise individual development and analysis workflows. The release's non-data GUI self-check is `EOH.exe --check <output.json>` with `BSE_COMPUTE_BACKEND=cpu`. The project and upstream source references are in [SOURCE.md](SOURCE.md).
