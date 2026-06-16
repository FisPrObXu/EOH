# 本地运行与 Git 操作说明

## 项目说明

EOH 是 **Eye of Heaven** 的代称。本项目是为了复制并辅助光片/薄片图像分析而开发的本地 Python 工作流。它可以帮助完成图像清单、比例尺检测、PPL/XPL 配对、质量控制、候选暗域统计、候选裂隙/纹理特征统计、后续实验建议和保守报告生成。

本项目不会仅凭图像确认矿物名称。输出中的矿物、结构和阶段解释都应理解为候选结果，需要人工岩相学复核和后续实验验证。

## 第一次安装

在 PowerShell 中进入仓库目录：

```powershell
cd E:\Github\FisPrObXu\EOH
```

创建并启用虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

如果不想 editable install，也可以：

```powershell
python -m pip install -r requirements.txt
```

## 独立运行

默认数据目录为 `JBXu_TS`，输出目录为 `thinsection_assessment_outputs`：

```powershell
python -m eoh_thinsection --input .\JBXu_TS --output .\thinsection_assessment_outputs --overwrite
```

安装后也可以运行：

```powershell
eoh-thinsection --input .\JBXu_TS --output .\thinsection_assessment_outputs --overwrite
```

## 主要输出

- `thinsection_image_assessment_report.md`：总报告
- `image_qc.csv`：每张图像的质量控制、模式推断、比例尺摘要
- `scale_bar_measurements.csv`：红色比例尺检测结果、像素长度和候选 `um/px`
- `image_pairs.csv`：PPL/XPL 配对表
- `registration_qc.csv`：PPL/XPL 配准候选质量
- `feature_summary.csv`：图像级暗域和边缘特征摘要
- `dark_domain_stats.csv`：候选暗域连通域统计
- `analysis_feasibility.csv`：任务可行性评估
- `impossible_or_not_recommended.csv`：不能仅凭图像下结论的事项
- `phenomenon_followup.csv`：候选现象触发的后续分析建议
- `human_vs_computer.csv`：人机分工建议
- `thumbnails/`：缩略图
- `scale_bar_qc/`：比例尺检测 QC 图
- `annotated_overview/`：总览图

## 如何理解比例尺结果

当前算法检测右下角红色标尺线，并根据文件名倍率推断候选标尺文字：

- `2x`：候选 `250 um`
- `5x`：候选 `100 um`
- `10x`：候选 `200 um`
- `20x`：候选 `20 um`

这些结果适合导航和初步统计。用于发表级定量测量前，应人工检查 `scale_bar_qc/` 中青色框是否准确框住红色横线，并确认图中文字。

## 运行后如何 Git

查看状态：

```powershell
git status -sb
```

只提交代码和说明文档：

```powershell
git add .gitignore README.md docs pyproject.toml requirements.txt src
git commit -m "Build EOH thin-section analysis workflow"
```

当前 `.gitignore` 默认不提交原始图像 `JBXu_TS/` 和生成输出 `thinsection_assessment_outputs/`，这样可以避免把大量未发表数据直接上传。

## 上传到私人 GitHub 仓库

如果已经在 GitHub 网页创建了私有仓库 `FisPrObXu/EOH`：

```powershell
git remote add origin https://github.com/FisPrObXu/EOH.git
git branch -M main
git push -u origin main
```

如果安装并登录了 GitHub CLI，可以一行创建 private repo 并推送：

```powershell
gh repo create FisPrObXu/EOH --private --source . --remote origin --push --description "EOH (Eye of Heaven): codebase for reproducing and assisting thin-section analysis"
```

如果 `gh` 不存在，先安装 GitHub CLI，然后运行：

```powershell
gh auth login
```

再执行上面的 `gh repo create` 命令。

## 日常更新流程

每次修改代码后：

```powershell
git status -sb
git add .gitignore README.md docs pyproject.toml requirements.txt src
git commit -m "Describe the change"
git push
```

如果你决定把少量示例输出也提交，需要手动指定文件路径，例如：

```powershell
git add -f thinsection_assessment_outputs\thinsection_image_assessment_report.md
```

不要默认 `git add -A`，除非你确认原始图像和输出都应该进入仓库。
