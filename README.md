# EOH — Eyes of heaven

**EOH 0.4.1** is a Windows desktop tool for reviewing BSE microscopy images, measuring grain sizes, and comparing observed spatial distances with simulated layouts. Its interface and new reports are in English; a [Chinese user manual](EOH_%E4%B8%AD%E6%96%87%E8%AF%B4%E6%98%8E%E6%89%8B%E5%86%8C.html) is included.

## Download and run

1. Download `EOH_0.4.1_win64.zip` from the [v0.4.1 release](https://github.com/FisPrObXu/EOH/releases/tag/v0.4.1).
2. Extract the entire archive to a short, writable path such as `C:\EOH`.
3. Open `EOH/EOH.exe`. Keep the adjacent `_internal` folder. Python and Conda do not need to be installed.

The target platform is 64-bit Windows. An NVIDIA GPU with a compatible driver can accelerate selected layout calculations; EOH falls back to the CPU when a GPU is unavailable. The executable is an unsigned test release. See the [Chinese manual](EOH_%E4%B8%AD%E6%96%87%E8%AF%B4%E6%98%8E%E6%89%8B%E5%86%8C.html) for installation, screenshots-independent operating steps, and troubleshooting.

## What EOH does

- Imports single-frame 8-bit images, with explicit crop and physical pixel-size calibration.
- Detects candidate bright particles and dark regions for human review. Add, redraw, delete, keep, or exclude outlines in the local review page.
- Excludes buffered hole points and crack lines; defines protected analysis windows for distance and grain-size measurements.
- Measures native-pixel areas and two-dimensional equivalent-circle diameters for complete grains in the grain-size window.
- Compares observed nearest-dark-region distances with an illustrative uniform layout and random controls. The default center-position analysis uses 4,999 Monte Carlo layouts; an optional equal-area design retains the specified area and non-overlap constraints.
- Exports editable PDF/SVG figures, 600 dpi PNG/TIFF figures, numerical tables, simulation arrays, settings, review records, and individual or selected-case summary reports.
- Lets users choose plotting settings and process cases in a batch. Supported GPU operations reuse the compute context within a batch.

## Typical workflow

1. Choose input and output folders, import an image, crop non-image labels, and set the physical scale.
2. Open **Review**, check the bright and dark candidates, add exclusions, and click **Save all changes**.
3. Confirm human review in the desktop window and generate the report. Re-generate after further edits.
4. Adjust **Plot settings** and, if desired, select cases for a batch summary.

Back up the complete case folder: it contains the original image copy, saved review revisions, parameters, results, and logs. Existing user images and case data are not included in this repository or its release archive.

## Interpretation

Brightness-based candidates do not independently identify chemical phases. The names gold and chalcopyrite follow the user-supplied class mapping and require independent mineralogical evidence. A uniform-layout example is an illustrative comparison, not the random-model expectation. Simulation curves and their Monte Carlo reference limits are model results, not measurement-error bands or independent sample replicates. Interpret test results within the stated window, segmentation, and null-model assumptions.

## Source and licensing

The application source is in [`comment1_colocation/code`](comment1_colocation/code), with its default configuration in [`comment1_colocation/config.json`](comment1_colocation/config.json). See [BUILDING.md](BUILDING.md) for the Windows development environment and packaging, and [SOURCE.md](SOURCE.md) for corresponding upstream source versions. EOH project code is distributed under [GNU AGPL-3.0-only](LICENSE). Third-party components retain their own terms; attribution and notices are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [`licenses/`](licenses/).

Earlier thin-section research code remains in [`src/eoh_thinsection`](src/eoh_thinsection); the root `pyproject.toml` and `requirements.txt` describe that legacy code, rather than this 0.4.1 desktop application. Original images and generated research outputs are excluded by `.gitignore`.

---

# 中文说明

**EOH 0.4.1** 是用于 BSE 显微图像的桌面工具，支持人工审核轮廓、粒径统计以及实测距离与模拟布局的对比。软件界面和新生成的报告为英文，并附有[中文操作手册](EOH_%E4%B8%AD%E6%96%87%E8%AF%B4%E6%98%8E%E6%89%8B%E5%86%8C.html)。

## 下载与启动

1. 从 [v0.4.1 发布页](https://github.com/FisPrObXu/EOH/releases/tag/v0.4.1)下载 `EOH_0.4.1_win64.zip`。
2. 将整个压缩包解压到较短、可写的路径，例如 `C:\EOH`。
3. 打开 `EOH/EOH.exe`，并保留旁边的 `_internal` 文件夹。无需安装 Python 或 Conda。

目标平台为 64 位 Windows。具有兼容驱动的 NVIDIA GPU 可加速部分布局计算；没有可用 GPU 时自动使用 CPU。当前可执行文件为未签名测试版。操作步骤和故障排查见[中文手册](EOH_%E4%B8%AD%E6%96%87%E8%AF%B4%E6%98%8E%E6%89%8B%E5%86%8C.html)。

## 主要功能

- 导入单帧 8 位图片，明确设置裁切范围和物理像素尺寸。
- 识别待人工审核的亮颗粒和暗区域；可在本机审核页新增、重画、删除、保留或排除轮廓。
- 使用带缓冲半径的孔洞点和裂隙线设置排除区，分别建立距离分析和粒径分析的安全窗口。
- 测量粒径安全窗口内完整颗粒的原生像素面积及二维等效圆直径。
- 将实测的最近暗区距离与直观的均匀布局和随机对照比较。默认中心位置分析使用 4,999 次蒙特卡洛布局；可选的等面积设计遵循设定的面积和不重叠约束。
- 输出可编辑的 PDF／SVG 图件、600 dpi PNG／TIFF 图件、数值表、模拟数组、设置、审核记录，以及单图或所选案例的汇总报告。
- 支持调整出图设置和批量处理；批量任务中的受支持 GPU 操作共用计算上下文。

## 典型流程

1. 选择输入和输出文件夹，导入图片，裁掉非图像文字并设置物理标尺。
2. 打开 **Review**，检查亮／暗候选及排除区，点击 **Save all changes**。
3. 回到桌面窗口确认已人工审核，再生成报告；后续修改后需重新生成。
4. 根据需要调整 **Plot settings**，或勾选案例生成批量汇总。

建议备份完整案例文件夹，其中包含原图副本、审核版次、参数、结果和日志。公开仓库与发布包不包含用户的原始图片或案例数据。

## 结果解释

亮度分类不能单独证明矿物物相；金和黄铜矿名称来自用户提供的类别对应关系，需要独立矿物学证据。均匀铺开是直观对照，不是随机模型的期望值。随机曲线及其蒙特卡洛参考上界表示模型结果，不能视为实测误差带或独立样品重复。结论需要结合所采用的窗口、分割结果和零假设模型解释。

## 源码与许可

源码位于 [`comment1_colocation/code`](comment1_colocation/code)，构建方法见 [BUILDING.md](BUILDING.md)。项目采用 [GNU AGPL-3.0-only](LICENSE)；第三方组件各自的许可及对应源码位置见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 [SOURCE.md](SOURCE.md)。

早期薄片分析代码仍位于 [`src/eoh_thinsection`](src/eoh_thinsection)；根目录的 `pyproject.toml` 和 `requirements.txt` 属于该旧代码，并非 0.4.1 桌面工具的安装配置。仓库和发布包不包含原始研究图片及案例数据。
