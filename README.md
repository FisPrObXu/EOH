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

## 主要功能与流程

EOH 支持裁切、标尺定标、亮／暗候选识别、手工增删或重画轮廓，以及用孔洞点和裂隙线设置排除区。程序可统计安全窗口内完整颗粒的二维等效圆粒径，并将实测近邻距离与均匀布局、随机模拟进行比较。结果包含独立科研图件、数据表、模拟数组、审核记录及单图／批量汇总报告。

先导入并定标图片，在审核页修改并点击 **Save all changes**，回到主窗口确认人工审核后生成报告。后续修改轮廓需要重新生成报告。建议备份完整案例文件夹，其中包含原图副本、审核版次、参数、结果和日志。

亮度分类不能单独证明矿物物相；金和黄铜矿名称来自用户提供的类别对应关系，需要独立证据。均匀铺开是直观对照，随机曲线及其参考上界表示模型结果，不能视为实测误差带或独立样品重复。

## 源码与许可

源码位于 [`comment1_colocation/code`](comment1_colocation/code)，构建方法见 [BUILDING.md](BUILDING.md)。项目采用 [GNU AGPL-3.0-only](LICENSE)；第三方组件各自的许可及对应源码位置见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 [SOURCE.md](SOURCE.md)。

早期薄片分析代码仍位于 [`src/eoh_thinsection`](src/eoh_thinsection)；根目录的 `pyproject.toml` 和 `requirements.txt` 属于该旧代码，并非 0.4.1 桌面工具的安装配置。仓库和发布包不包含原始研究图片及案例数据。
