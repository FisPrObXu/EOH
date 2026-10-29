# Corresponding source and reproducibility

EOH 0.4.1 application sources, configuration, review-page assets, and build scripts are available in this repository. The Windows archive includes the corresponding application source snapshot and license notices.

The executable includes or uses these separately maintained components:

- [PyMuPDF 1.26.4 source](https://github.com/pymupdf/PyMuPDF/tree/1.26.4), under GNU AGPL-3.0 or a commercial license. EOH is distributed using the AGPL option. The [official source distribution](https://pypi.org/project/PyMuPDF/1.26.4/#files) is also provided as `pymupdf-1.26.4.tar.gz` alongside the executable on the [v0.4.1 release page](https://github.com/FisPrObXu/EOH/releases/tag/v0.4.1).
- [MuPDF 1.26.7 source](https://github.com/ArtifexSoftware/mupdf/tree/1.26.7), the MuPDF version reported by the build environment, under AGPL/commercial terms.
- [CuPy 13.6.0 source](https://github.com/cupy/cupy/tree/v13.6.0), under the MIT license.
- [PyInstaller 6.17.0 source](https://github.com/pyinstaller/pyinstaller/tree/v6.17.0), under GPL-2.0-or-later with its bootloader exception.
- Native CUDA NVRTC is a redistributable NVIDIA binary component, distributed subject to NVIDIA's applicable license rather than under AGPL; the accompanying notices and version metadata are in `licenses/`.

Recorded Python and native component versions, distribution URLs where available, and third-party license texts are in [`licenses/`](licenses/). Build steps are in [BUILDING.md](BUILDING.md). The published binary is built from the included project sources.
