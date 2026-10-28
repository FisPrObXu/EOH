"""Document and archive an already validated portable build, without private cases."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile

from self_service_engine import ROOT, load, dump, within


GUIDE = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>EOH — Eyes of heaven · 0.4.1 中文说明手册</title>
<style>body{max-width:920px;margin:40px auto;padding:0 24px;font:17px/1.8 "Microsoft YaHei",sans-serif;color:#243342;background:#f8fafc}h1,h2{line-height:1.35;color:#18374a}h1{font-size:32px}h2{margin-top:36px;font-size:23px}article{background:white;padding:30px;border:1px solid #dce4eb;border-radius:12px}code{background:#edf2f6;padding:2px 6px;border-radius:4px}.note{border-left:4px solid #16958f;padding:12px 18px;background:#edf8f7}li{margin:8px 0}a{color:#076e9a}</style>
<article><h1>EOH — Eyes of heaven · 0.4.1</h1><p>Windows x64 便携测试版 · BSE 颗粒审核、距离零假设检验与粒径统计</p>
<div class="note">接收者不需要安装 Python、Conda 或 CUDA Toolkit。请解压整个压缩包，双击 <code>EOH/EOH.exe</code>。请保留同目录的 <code>_internal</code>。</div>
<h2>第一次运行</h2><ol>
<li>将整个包解压到有写入权限的较短路径，例如 <code>E:\\EOH</code>；不要直接在压缩包中运行。</li>
<li>进入 <code>EOH</code> 文件夹，双击 <code>EOH.exe</code>。首次启动可能稍慢。</li>
<li>软件会在 EXE 旁建立 <code>工作数据</code>，存放设置、日志和运行缓存。包内没有作者的原始图片、人工审核记录或历史报告。</li>
<li>Windows 10/11、64 位系统为目标环境；其他电脑仍需首次试运行。本测试版未签名，不会把 Python 缺失作为启动前提。</li></ol>
<h2>完成一张新图片</h2><ol>
<li>在主窗口选择输出案例文件夹，再选择输入图片。便携版可选择其他盘符的输出文件夹。</li>
<li>裁掉文字／比例尺栏，核对像素尺寸或沿已知比例尺定标，选择统计范围、保护距离和分析参数后创建案例。</li>
<li>打开该案例的审核网页，核对亮白颗粒与深灰对象；可增删轮廓，或用点／线及其半径排除孔洞、裂隙。灰度候选仍须人工确认物相。</li>
<li>完成当前轮廓后点击网页的“保存全部更新”，确认页面提示已保存；随后回到应用生成报告。</li>
<li>在“出图设置”调整尺寸、图例、曲线、柱宽等后重新出图。勾选案例后可执行批量分析或汇总。</li></ol>
<p>案例目录内保存原图副本、审核记录、分析表格、模拟数据、参数和报告。备份时复制整个案例目录。详细操作可从应用内的操作说明打开。</p>
<h2>GPU 与批量计算</h2>
<p>计算设备可选“自动”“CPU”或优先使用 GPU。支持 NVIDIA CUDA 的电脑会加速均匀布局和等面积随机布局；缺少兼容设备或 CUDA 初始化失败时回退 CPU。GPU 驱动仍需由操作系统提供，包中不包含显卡驱动。</p>
<p>批量分析在同一个计算进程中运行，复用 GPU 上下文。首次任务包含初始化与编译成本；图片读取、人工审核和报告绘制等步骤仍主要使用 CPU。</p>
<p>本机 RTX 4060 Laptop 的一个真实案例，预热后的完整报告约从 112 秒降到 39 秒（约 2.9 倍）；这不是对所有电脑和图片的速度保证。验证保留相同随机种子、有效布局和数值结果，详见 <code>验证摘要.json</code>。</p>
<h2>小屏幕与缩放</h2>
<p>主窗口及参数页支持滚动。鼠标滚轮上下滚动，Shift＋滚轮左右滚动；也可拖动底部／侧面的滚动条。窗口会按屏幕限制初始大小。导入、增强识别和出图设置对话框的操作按钮固定在底部。</p>
<h2>出现问题时</h2>
<p>启动错误见 <code>工作数据/logs/startup_error.txt</code>；常规启动日志见同目录的 <code>desktop_startup.log</code>。单案例计算记录保存在对应案例目录内。报告的 <code>logs/compute_backend.json</code> 记录实际计算设备与回退原因。反馈问题时提供错误日志、版本和复现步骤；原图是否提供由数据所有者决定。</p>
<h2>源码与公开发布</h2>
<p>源码在 <code>source</code>，第三方许可在 <code>licenses</code>；构建步骤见 <code>source/构建说明.txt</code>。目前交付的是可转交测试的便携包，没有代为上传到公共平台，也没有替版权所有者确定项目开源许可证。</p>
<p>PyMuPDF/MuPDF 提供 AGPL-3.0 与商业双许可。正式公开发布前，版权所有者需要选择并落实满足相关许可的开源分发方案，或取得适当的商业授权。附带源代码不等同于已完成全部 AGPL 合规要求。参见 <a href="https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright">官方许可说明</a>。</p>
</article></html>'''


def main():
    release = within(Path(load(ROOT/'logs/portable_build_inputs.json')['release']), ROOT.parent/'releases')
    pipeline = load(ROOT/'logs/portable_pipeline_validation.json')
    assert pipeline['status'] == 'passed' and Path(pipeline['release']) == release
    numerical = load(ROOT/'logs/upgrade_release_validation.json')
    assert numerical['status'] == 'passed'
    gui = load(ROOT/'logs/portable_final_gui_smoke.json')
    assert gui['ok'] and gui['gui'] and gui['frozen']
    english=load(ROOT/'logs/eoh_english_validation.json');assert english['status']=='passed'
    browser=load(ROOT/'logs/eoh_browser_validation.json');assert browser['status']=='passed'
    shutil.copyfile(ROOT.parent/'EOH_中文说明手册.html',release/'EOH_中文说明手册.html')
    (release/'README.txt').write_text('EOH — Eyes of heaven\nVersion 0.4.1 | Windows x64\n\nExtract the entire archive. Run EOH/EOH.exe and retain its _internal folder. Python is not required.\nThe interface and newly generated reports are in English. Open EOH_中文说明手册.html for the Chinese manual, or click Chinese manual in EOH.\nFor existing cases, use Output case folder > Browse to select your previous case folder.\n',encoding='utf-8')
    checks = dict(product='EOH',full_name='Eyes of heaven',version='0.4.1', verified_at=datetime.now().isoformat(),english_interface=english['checks'],browser_review=browser['checks'],
                  standalone=pipeline['checks'], numerical_and_ui=numerical['checks'],
                  packaged_gui_and_three_dialogs_without_python_path=True,
                  benchmark=dict(cpu_seconds=numerical['previous_cpu_full_report_seconds'],
                                 warm_gpu_seconds=numerical['gpu_full_report_seconds'],
                                 speedup=numerical['end_to_end_speedup'],
                                 hardware='NVIDIA GeForce RTX 4060 Laptop GPU',
                                 note='One real case on the development computer; not an independent-machine acceptance test.'),
                  no_private_images_reviews_or_reports=True)
    dump(release/'Validation_summary.json', checks)
    # Retain full ownership proof privately; do not ship the author's workstation path.
    provenance = load(release/'build_provenance.json')
    if 'workspace' in provenance:
        private = ROOT/'logs'/('release_provenance_'+release.name+'.json')
        dump(private, provenance)
        provenance.pop('workspace')
        dump(release/'build_provenance.json', provenance)
    source_code=release/'source/comment1_colocation/code'
    for name in ['build_portable.py','finalize_portable.py']:
        shutil.copyfile(ROOT/'code'/name, source_code/name)
    for name in ['verify_upgrade_release.py','verify_portable_pipeline.py','verify_batch_summary.py','verify_eoh_english.py','verify_eoh_browser.py']:
        shutil.copyfile(ROOT/'code'/name, source_code/name)
    archive = release.parent/(release.name+'.zip')
    assert not archive.exists(), 'Use a new release path instead of overwriting a previous distribution'
    io_root = Path('\\\\?\\'+str(release.resolve())) if os.name == 'nt' else release
    entries = sorted((p for p in io_root.rglob('*') if p.is_file()), key=str)
    forbidden = {'review_annotations.json','latest_report.json','case.json'}
    assert not any(p.name in forbidden or p.name.startswith('original.') for p in entries)
    assert not (release/'EOH/工作数据').exists(), 'Runtime data must not enter distribution'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=3, allowZip64=True) as z:
        for file in entries:
            rel=file.relative_to(io_root)
            z.write(file, 'EOH_0.4.1/'+rel.as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert 'EOH_0.4.1/EOH/EOH.exe' in z.namelist()
    digest=hashlib.sha256()
    with archive.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):digest.update(block)
    archive.with_suffix('.zip.sha256.txt').write_text(digest.hexdigest()+'  '+archive.name+'\n',encoding='utf-8')
    result=dict(release=str(release),archive=str(archive),bytes=archive.stat().st_size,
                files=len(entries),sha256=digest.hexdigest(),zip_crc_verified=True,checks=checks)
    dump(ROOT/'logs/portable_distribution.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
