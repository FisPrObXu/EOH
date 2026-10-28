"""Selected-case export and descriptive synthesis of spatial and grain-size reports."""
from collections import defaultdict
from datetime import datetime
import html
from pathlib import Path
import shutil
import uuid
import zipfile

import self_service_engine as engine
from self_service_engine import ROOT,load,dump,within,tempdir,safe_remove,configure_temp,UserError,check_cancel
from plot_settings import read_settings,run_settings,validate_settings


def current_result(case):
    """Resolve a complete frozen result, including a previously flattened result folder."""
    meta=load(case/'case.json');review=load(case/'report'/'review_annotations'/'review_annotations.json')
    latest=load(case/'latest_report.json') if (case/'latest_report.json').exists() else {}
    candidates=[case/'results'/str(latest.get('run','missing'))]
    if latest.get('report'):candidates.append(Path(latest['report']).parent.parent)
    candidates.append(case/'results')
    for candidate in candidates:
        # An absolute index may still contain the previous folder name. It is
        # only a lookup hint; never follow it outside the selected case.
        try:result=within(candidate,case)
        except UserError:continue
        if not (result/'inputs'/'review.json').exists():continue
        frozen=load(result/'inputs'/'review.json')
        if frozen.get('dataset_id')!=meta['dataset_id'] or frozen.get('revision')!=review['revision']:continue
        if latest.get('review_revision')!=review['revision']:continue
        required=['report/Grain_Size_Report.html','report/Grain_Size_Report.pdf','tables/grain_sizes_all.csv','logs/grain_size_summary.json']
        if (result/'logs'/'point_summary.json').exists():required+=['report/Report.html','report/Report.pdf','tables/point_curves.csv','tables/point_simulations.npz','tables/point_evenly_spread.csv','tables/point_random_example.csv']
        if not all((result/name).exists() for name in required):continue
        repaired=dict(latest,report=str(result/'report'/('Report.html' if (result/'logs'/'point_summary.json').exists() else 'Grain_Size_Report.html')),grain_report=str(result/'report'/'Grain_Size_Report.html'))
        if repaired!=latest:
            dump(case/'logs'/'report_location_repair.json',dict(previous=latest,repaired=repaired,reason='resolve frozen report inside current case directory'))
            dump(case/'latest_report.json',repaired);latest=repaired
        if read_settings(case)!=validate_settings(latest.get('plot_settings')) or 'random_curve_count' not in (latest.get('plot_settings') or {}):continue
        if (result/'inputs'/'plot_settings.json').exists() and read_settings(case)!=run_settings(result):continue
        return result
    return None


def ensure_result(case,job):
    result=current_result(case)
    if result is not None:return result
    review=load(case/'report'/'review_annotations'/'review_annotations.json')
    latest=load(case/'latest_report.json') if (case/'latest_report.json').exists() else {}
    confirmed=bool(latest.get('human_review_confirmed') and latest.get('review_revision')==review['revision'])
    original_emit=engine.emit
    def progress(message,**extra):
        if extra.get('event')=='complete':extra={k:v for k,v in extra.items() if k not in ['event','report']}
        original_emit(message,**extra)
    original_emit('Updating case report: '+load(case/'case.json')['name'])
    engine.emit=progress
    try:return engine.analyze(case,review['revision'],human_review=confirmed)
    finally:
        engine.emit=original_emit;configure_temp(job/'_runtime');original_emit('Continuing selected-case summary…',job=str(job))


def copy_case(case,result,destination):
    """Export inputs and one frozen result; prior versions and redundant inner ZIPs stay at source."""
    destination.mkdir(parents=True)
    for name in ['inputs','masks','tables']:
        if (case/name).exists():shutil.copytree(case/name,destination/name)
    for name in ['case.json','config.json']:shutil.copyfile(case/name,destination/name)
    (destination/'report'/'review_annotations').mkdir(parents=True)
    for name in ['Object_Review.html','1_native_grayscale.png']:
        if (case/'report'/name).exists():shutil.copyfile(case/'report'/name,destination/'report'/name)
    shutil.copyfile(result/'inputs'/'review.json',destination/'report'/'review_annotations'/'review_annotations.json')
    shutil.copytree(result,destination/'result',ignore=shutil.ignore_patterns('Export.zip','.temporary-owner.json','_runtime','__pycache__'))


def frozen_case_settings(cases_root,record,copied_case):
    """Match a live case by stable identity; missing live settings retain the snapshot."""
    meta=load(copied_case/'case.json')
    for case in Path(cases_root).iterdir():
        if not case.is_dir() or not (case/'case.json').exists():continue
        live=load(case/'case.json')
        if live.get('case_id')!=record['case_id'] or live.get('dataset_id')!=meta['dataset_id']:continue
        if (case/'plot_settings.json').exists():return read_settings(case),str(case/'plot_settings.json')
    return run_settings(copied_case/'result'),str(copied_case/'result'/'inputs'/'plot_settings.json')


def collect_case(case,result,code,relative):
    import pandas as pd
    meta=load(case/'case.json');cfg=load(result/'inputs'/'config.json');review=load(result/'inputs'/'review.json')
    grain=load(result/'logs'/'grain_size_summary.json');analysis=cfg['analysis']
    point=load(result/'logs'/'point_summary.json') if (result/'logs'/'point_summary.json').exists() else None
    area=load(result/'logs'/'area_summary.json') if (result/'logs'/'area_summary.json').exists() else dict(available=False,reason='No distance controls were generated for this case.')
    record=dict(code=code,name=meta['name'],case_id=meta['case_id'],source_sha256=meta.get('source_sha256'),
                source_case=str(case),source_result=str(result),copied_case=relative.as_posix(),review_revision=review['revision'],
                current_revision=load(case/'report'/'review_annotations'/'review_annotations.json')['revision'],
                human_review_confirmed=bool(review.get('human_review_confirmed',False)),
                distance_limit_um=analysis['rmax_um'],distance_step_um=analysis['step_um'],near_um=analysis['near_um'],
                size_guard_um=grain['size_guard_um'],pixel_size_um=meta['pixel_size_um'],
                spatial_available=point is not None,point=point,area=area,grain=grain,
                spatial_report=(relative/'result'/'report'/'Report.html').as_posix() if point else None,
                grain_report=(relative/'result'/'report'/'Grain_Size_Report.html').as_posix())
    table=pd.read_csv(result/'tables'/'grain_sizes_all.csv');table.insert(0,'case_code',code);table.insert(1,'case_name',meta['name'])
    distances=pd.read_csv(result/'tables'/'01_observed_distances.csv') if (result/'tables'/'01_observed_distances.csv').exists() else pd.DataFrame()
    if len(distances):distances.insert(0,'case_code',code);distances.insert(1,'case_name',meta['name'])
    return record,table,distances


def summary_tables(records,grain,distances,out):
    import numpy as np
    import pandas as pd
    spatial=[];phases=[]
    for record in records:
        p=record['point'] or {};a=record['area']
        row={k:record[k] for k in ['code','name','review_revision','human_review_confirmed','spatial_available','distance_limit_um','distance_step_um','near_um','size_guard_um']}
        row.update({k:p.get(k) for k in ['N','supported','observed_near','expected_near','observed_fraction','reference_fraction','observed_mean','reference_mean','reduction_fraction','curve_p','near_p_exact','mean_p','all_grid_at_least_reference']})
        row.update({'area_'+k:a.get(k) for k in ['available','N','total_area_px','cap_area_px','reference_mean','even_mean','random_example_mean','curve_tail','mean_tail','same_count']})
        row['area_incompatible_ids']=' / '.join(a.get('incompatible_ids',[]));row['area_overlap_ids']=' / '.join(a.get('actual_overlap_ids',[]));spatial.append(row)
        for phase in record['grain']['phases']:phases.append(dict(case_code=record['code'],case_name=record['name'],review_revision=record['review_revision'],human_review_confirmed=record['human_review_confirmed'],size_guard_um=record['size_guard_um'],**phase))
    pd.DataFrame(spatial).to_csv(out/'tables'/'case_spatial_summary.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(phases).to_csv(out/'tables'/'case_grain_summary.csv',index=False,encoding='utf-8-sig')
    grain.to_csv(out/'tables'/'all_grain_regions.csv',index=False,encoding='utf-8-sig')
    distances.to_csv(out/'tables'/'all_observed_distances.csv',index=False,encoding='utf-8-sig')
    pooled=[]
    for kind in ['bright','gray']:
        x=grain.loc[(grain.kind==kind)&grain.included,'equivalent_circle_diameter_um'].to_numpy()
        pooled.append(dict(kind=kind,phase='Gold' if kind=='bright' else 'Chalcopyrite',N=len(x),mean_um=float(x.mean()) if len(x) else None,
                           median_um=float(np.median(x)) if len(x) else None,q25_um=float(np.quantile(x,.25)) if len(x) else None,
                           q75_um=float(np.quantile(x,.75)) if len(x) else None,min_um=float(x.min()) if len(x) else None,max_um=float(x.max()) if len(x) else None))
    pd.DataFrame(pooled).to_csv(out/'tables'/'pooled_grain_summary.csv',index=False,encoding='utf-8-sig')
    return pooled


def comparison_figures(records,out,settings):
    import numpy as np
    import pandas as pd
    from matplotlib.lines import Line2D
    from matplotlib.ticker import PercentFormatter,MaxNLocator
    import matplotlib.pyplot as plt
    from self_service_report import save,plot_axes
    from publication21_figures import OBS,style
    from plot_settings import draw_cdf,register_legend,tag
    from summary_publication import mean_distance_figures,combined_distance_figures
    style();figures=mean_distance_figures(records,out,settings)
    for start in range(0,len(records),12):
        block=records[start:start+12];suffix=f'_{start//12+1:02d}' if len(records)>12 else ''
        labels=[r['code'] for r in block];y=np.arange(len(block))
        for stem,title,fields,xlabel,percent in [('02_Near_Fractions','Case-specific near-distance fractions',('observed_fraction','reference_fraction'),'Near-distance fraction',True)]:
            if not any(r['point'] for r in block):continue
            fig,ax=plt.subplots(figsize=(5.3,max(2.8,.26*len(block)+1.5)));fig.subplots_adjust(left=.16,right=.95,bottom=.28,top=.85)
            for row,r in enumerate(block):
                if not r['point']:continue
                p=r['point'];actual,baseline=p[fields[0]],p[fields[1]]
                tag(ax.plot([actual,baseline],[row,row],color='#bbbbbb',lw=.7)[0],'observed','baseline')
                tag(ax.plot(actual,row,'o',color=OBS,ms=3)[0],'observed');tag(ax.plot(baseline,row,'s',color='#222222',ms=3)[0],'baseline')
            ax.set_yticks(y,labels);ax.invert_yaxis();ax.set(xlabel=xlabel,title=title)
            if percent:ax.set_xlim(0,1.02);ax.xaxis.set_major_formatter(PercentFormatter(1))
            else:ax.set_xlim(left=0);ax.xaxis.set_major_locator(MaxNLocator(5))
            register_legend(ax,handles=[Line2D([],[],marker='o',ls='',color=OBS,label='Observed'),Line2D([],[],marker='s',ls='',color='#222222',label='Random baseline')],loc='upper left',bbox_to_anchor=(0,-.25),ncol=2)
            save(fig,out,stem+suffix,figures,'Per-field capped mean-distance comparison' if not percent else 'Per-field near-distance fraction comparison')
        for kind,title,stem,color in [('bright','Gold sizes by case','21_Gold_By_Case','#aa3377'),('gray','Chalcopyrite sizes by case','22_Chalcopyrite_By_Case','#2878b5')]:
            fig,ax=plt.subplots(figsize=(5.3,max(2.8,.26*len(block)+1.5)));fig.subplots_adjust(left=.16,right=.95,bottom=.28,top=.85)
            ticklabels=[]
            for row,r in enumerate(block):
                phase=next(p for p in r['grain']['phases'] if p['kind']==kind);ticklabels.append(f'{r["code"]} (n={phase["N"]})')
                if phase['N']:
                    tag(ax.plot([phase['q25_um'],phase['q75_um']],[row,row],color=color,lw=1.5)[0],kind)
                    tag(ax.plot(phase['median_um'],row,'o',color=color,ms=3)[0],kind)
            ax.set_yticks(y,ticklabels);ax.invert_yaxis();ax.set(xlabel='Equivalent-circle diameter (μm)',title=title,xlim=(0,None));ax.xaxis.set_major_locator(MaxNLocator(5))
            register_legend(ax,handles=[tag(Line2D([],[],color=color,lw=1.5,marker='o',label='Median and interquartile range'),kind)],loc='upper left',bbox_to_anchor=(0,-.25))
            save(fig,out,stem+suffix,figures,'Per-field gold median size and interquartile range' if kind=='bright' else 'Per-field chalcopyrite median size and interquartile range')
    figures+=combined_distance_figures(records,out,settings)
    return figures


def number(value):
    return '—' if value is None else f'{value:.4g}'


def publish_summary(job,destination,folder):
    """Publish verified output even if Windows temporarily refuses a directory rename."""
    job=within(job,folder);destination=within(destination,folder)
    try:job.rename(destination);return 'rename'
    except PermissionError:
        import gc
        gc.collect()
        try:job.rename(destination);return 'rename_after_handle_release'
        except PermissionError:
            engine.emit('Windows prevented a folder rename; publishing a copy of the validated results…')
            # Exclusive creation proves this destination belongs to this call.
            destination.mkdir();dump(destination/'.temporary-owner.json',load(job/'.temporary-owner.json'))
            try:shutil.copytree(job,destination,dirs_exist_ok=True)
            except Exception:
                safe_remove(destination,folder)
                raise
            return 'copy_after_rename_denied'


def report_documents(records,pooled,figures,out):
    import fitz
    escaped=html.escape;confirmed=sum(r['human_review_confirmed'] for r in records)
    intro=f'<h1>Selected cases: spatial analysis and grain-size summary</h1><p>Generated: {datetime.now():%Y-%m-%d %H:%M}. Includes {len(records)} cases, of which {confirmed} are marked human-reviewed and {len(records)-confirmed} are candidates. Each result corresponds to the revision below.</p>'
    intro+='<table><tr><th>Code</th><th>Case name</th><th>Saved revision</th><th>Status</th><th>Distance / size guard (μm)</th></tr>'
    for r in records:intro+=f'<tr><td>{r["code"]}</td><td>{escaped(r["name"])}</td><td>r{r["review_revision"]}</td><td>'+('Reviewed' if r['human_review_confirmed'] else 'Candidate; review pending')+f'</td><td>{r["distance_limit_um"]:g} / {r["size_guard_um"]:g}</td></tr>'
    intro+='</table>'
    repeated=defaultdict(list)
    for r in records:
        if r['source_sha256']:repeated[r['source_sha256']].append(r['code'])
    duplicates=[v for v in repeated.values() if len(v)>1]
    if duplicates:intro+='<p>Repeated original-image sources: '+escaped('；'.join(' / '.join(v) for v in duplicates))+'. All selected cases are retained, including these duplicate sources in pooled distributions. They are not additional independent observations.</p>'
    methods='<h2>Summary methods and interpretation</h2><p>This report describes selected fields. Independent sample / batch identities are unavailable, so pooled figures are descriptive: no pooled significance p-value is computed, and neither grain counts nor 4999 simulations are independent sample counts. Original per-field p-values, controls and limitations remain in the individual reports.</p><p>Grain sizes use complete eligible grains and 2D equivalent-circle diameters. Pooled histograms and cumulative curves weight grains equally, rather than photographs; fields with more grains contribute more. Per-field plots show medians and interquartile ranges, which describe distributions rather than confidence intervals. See individual parameters for windows, scales and thresholds; cropped boundary fragments are not included.</p><p>Mean-distance plots are grouped by distance cap. Each row is a field, with n eligible bright grains. Magenta circles show observed means, black diamonds the matching center-model expectation; capped gray segments show the original 4999-layout 2.5%–97.5% random reference range. This describes random-model variability, not a confidence interval for the observed mean. Right-side values are observed / random expectation, retaining the original cap. Cases without distance results are listed without invented means.</p><p>Pooled distance curves are grouped by limit, step and near threshold, and weighted by eligible bright-grain counts. The legend occupies reserved space on the right: magenta solid = pooled observed; green dash-dot = uniform layout; orange dotted = weighted first saved random examples; black dashed = model expectation; light blue = pooled random results; light gray = individual observed curves. A uniform layout is not the random mean. Center and equal-area models retain their own controls.</p><p>For multiple fields, pooled random curves are regenerated with independent random-number streams within each frozen allowed domain, then combined with the same weights. This avoids pairing identically seeded kth layouts across fields. The center model retains per-field counts and excludes dark regions. The equal-area model preserves per-field total area, control counts, the original 75% area cap and non-overlap constraints. Single-field groups use saved evaluation curves. Pooled curves are descriptive: individual upper bounds are not averaged into a new bound and no pooled p-value is produced. Original p-values remain unchanged. Seeds, native positions / anchors and all curves are saved in tables as joint_random data and CSV.</p><p>All selected cases are retained. Missing distance tests are marked as not performed; grain-size results are still summarized. Plot display uses the first selected case settings. Interpolation adds no measurements. Separate figures are supplied as PDF, SVG and 600 dpi PNG/TIFF, with sources, parameters, original copies and grain-level data.</p>'
    methods=methods.replace('Magenta circles show observed means, black diamonds the matching center-model expectation; capped gray segments show ','Circles show observed means, diamonds the matching center-model expectation; capped segments show ')
    methods=methods.replace('Right-side values are observed / random expectation','Value labels are observed / random expectation; custom layouts may place them in row labels')
    methods=methods.replace('The legend occupies reserved space on the right: magenta solid = pooled observed; green dash-dot = uniform layout; orange dotted = weighted first saved random examples; black dashed = model expectation; light blue = pooled random results; light gray = individual observed curves.','Curves include pooled observed results, uniform layouts, saved first random examples, matching random expectations, pooled random results and individual observations. Legend position, labels, colors, styles and visibility follow this revision settings.')
    methods=methods.replace('Plot display uses the first selected case settings','Plot display uses the settings saved in inputs/plot_settings.json for this revision')
    from plot_settings import run_settings,describe,SERIES_NAMES
    presentation=run_settings(out);methods+='<h2>Plot settings for this revision</h2><p>'+escaped(describe(presentation))+'</p>'
    customized=[(SERIES_NAMES[role],value['label']) for role,value in presentation['series_options'].items() if value['label']]
    if customized:methods+='<p>Custom legend mapping: '+escaped('；'.join(label+'＝'+role for role,label in customized))+'。</p>'
    spatial='<h2>Per-field spatial analysis</h2><table><tr><th>Code</th><th>Bright count</th><th>Near fraction<br>Observed / random</th><th>Capped mean (μm)<br>Observed / random</th><th>Curve p</th><th>Mean p</th></tr>'
    for r in records:
        p=r['point']
        if p:spatial+=f'<tr><td>{r["code"]}</td><td>{p["N"]}</td><td>{100*p["observed_fraction"]:.1f}% / {100*p["reference_fraction"]:.1f}%<br>Threshold {r["near_um"]:g} μm</td><td>{number(p["observed_mean"])} / {number(p["reference_mean"])}<br>Cap {r["distance_limit_um"]:g} μm</td><td>{number(p["curve_p"])}</td><td>{number(p["mean_p"])}</td></tr>'
        else:spatial+=f'<tr><td>{r["code"]}</td><td colspan="5">Distance test not performed: grain-size-only mode or no eligible bright grains / dark targets in the distance window.</td></tr>'
    spatial+='</table><p>p-values are from each original model, not a pooled test. Incompatible exclusive models retain invalid / missing p-values as recorded in their reports.</p>'
    grain='<h2>Pooled grain sizes (equal grain weights; descriptive)</h2><table><tr><th>Class</th><th>Count</th><th>Mean (μm)</th><th>Median (μm)</th><th>Interquartile range (μm)</th></tr>'
    for p in pooled:grain+=f'<tr><td>{p["phase"]}</td><td>{p["N"]}</td><td>{number(p["mean_um"])}</td><td>{number(p["median_um"])}</td><td>{number(p["q25_um"])}–{number(p["q75_um"])}</td></tr>'
    grain+='</table><h2>Per-field grain sizes</h2><table><tr><th>Code</th><th>Class</th><th>Included / excluded</th><th>Mean (μm)</th><th>Median (μm)</th><th>Interquartile range (μm)</th></tr>'
    for r in records:
        for p in r['grain']['phases']:grain+=f'<tr><td>{r["code"]}</td><td>{p["phase"]}</td><td>{p["N"]} / {p["excluded"]}</td><td>{number(p["mean_um"])}</td><td>{number(p["median_um"])}</td><td>{number(p["q25_um"])}–{number(p["q75_um"])}</td></tr>'
    grain+='</table>'
    figure_blocks=[]
    for f in figures:
        stem=f['stem'];figure_blocks.append(f'<h2>{escaped(f["title"])}</h2><p>'+ ' / '.join(f'<a href="figures/{stem}.{ext}">{ext.upper()}</a>' for ext in ['pdf','svg','png','tiff'])+f'</p><img class="chart" src="figures/{stem}.png">')
    sources='<h2>Complete per-field reports and exported cases</h2><p>The merged PDF appendix includes both original PDF reports for each field, preserving their text and figures. Expand HTML sections to view them. sources retains selected inputs, outlines, parameters and results.</p>'
    for r in records:
        sources+=f'<h3>{r["code"]}　{escaped(r["name"])}</h3>'
        for title,key in [('Spatial analysis report','spatial_report'),('Grain-size report','grain_report')]:
            if r[key]:sources+=f'<details><summary>{title}: expand</summary><p><a href="{r[key]}">Open complete report</a></p><iframe loading="lazy" src="{r[key]}" title="{title}"></iframe></details>'
            else:sources+='<p>No spatial-distance report is available for this case; its grain-size report is retained.</p>'
    css='body{font:16px/1.85 Arial,"Microsoft YaHei",sans-serif;max-width:1150px;margin:30px auto;padding:20px;color:#243342}h1{font-size:26px}h2{font-size:21px;margin-top:32px}table{border-collapse:collapse;width:100%;font-size:14px}td,th{border:1px solid #d5dfe7;padding:8px;text-align:left}a{color:#24669b}.chart{width:750px;max-width:100%}iframe{width:100%;height:850px;border:1px solid #d5dfe7}details{margin:12px 0}'
    links='<p><a href="Summary.pdf">Download merged PDF (both reports per field)</a> / <a href="Export.zip">Download selected cases and summary figures</a> / <a href="tables/case_spatial_summary.csv">Spatial summary table</a> / <a href="tables/case_grain_summary.csv">Grain-size summary table</a></p>'
    (out/'Summary.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>Selected-case statistical summary</title><style>'+css+'</style>'+intro+links+methods+spatial+grain+''.join(figure_blocks)+sources+'</html>',encoding='utf-8')
    writer=fitz.DocumentWriter(str(out/'Summary.pdf'));page=fitz.paper_rect('a4');box=page+(40,40,-40,-40);toc=[];page_count=0
    chunks=[('Cases and review status',intro),('Summary methods',methods),('Per-field spatial statistics',spatial),('Grain-size statistics',grain)]
    chunks += [(f['title'],f'<h2>{escaped(f["title"])}</h2><img src="figures/{f["stem"]}.png" width="{min(500,f["width_pt"],480*f["width_pt"]/f["height_pt"])}">') for f in figures]
    try:
        for title,chunk in chunks:
            toc.append([1,title,page_count+1]);story=fitz.Story(html=chunk,user_css='body{font-family:sans-serif;font-size:10pt;line-height:1.5}h1{font-size:19pt}h2{font-size:14pt}td,th{padding:4pt}table{border-collapse:collapse}',archive=fitz.Archive(str(out)));more=1;count=0
            while more:
                device=writer.begin_page(page);more,_=story.place(box);story.draw(device);writer.end_page();page_count+=1;count+=1
                if count>100:raise UserError('Summary report pagination failed.')
    finally:
        try:writer.close()
        finally:del writer
    appended=[]
    with fitz.open(out/'Summary.pdf') as doc:
        for r in records:
            chapter=False
            for title,name in [('Spatial analysis','Report.pdf'),('Grain-size statistics','Grain_Size_Report.pdf')]:
                path=out/r['copied_case']/'result'/'report'/name
                if not path.exists():continue
                start=doc.page_count+1
                if not chapter:toc.append([1,r['code']+' '+r['name'],start]);chapter=True
                toc.append([2,title,start])
                with fitz.open(path) as part:appended.append(dict(case_code=r['code'],report=name,pages=part.page_count));doc.insert_pdf(part)
        doc.set_toc(toc);doc.save(out/'_merged.pdf',garbage=4,deflate=True)
    (out/'_merged.pdf').replace(out/'Summary.pdf')
    with fitz.open(out/'Summary.pdf') as doc:
        expected=page_count+sum(row['pages'] for row in appended)
        if doc.page_count!=expected:raise UserError('Merged PDF page-count check failed.')
        dump(out/'logs'/'pdf_validation.json',dict(pages=doc.page_count,overview_pages=page_count,source_reports=appended,page_count_matches=True))
        for i in range(min(4,doc.page_count)):doc[i].get_pixmap(matrix=fitz.Matrix(100/72,100/72)).save(out/'logs'/f'summary_page_{i+1:02d}.png')


def build_summary(selection,cases_root,frozen_summary=None,presentation=None):
    import pandas as pd
    cases_root=Path(cases_root).resolve();names=selection.get('cases',[])
    if not names or len(set(names))!=len(names):raise UserError('Select at least one case; each case can appear only once.')
    cases=[within(cases_root/name,cases_root) for name in names]
    if frozen_summary is None and any(not (case/'case.json').exists() for case in cases):raise UserError('A selected case is missing. Refresh the list and select again.')
    frozen=Path(frozen_summary).resolve() if frozen_summary is not None else None
    snapshot=load(frozen/'inputs'/'source_manifest.json') if frozen else None
    if snapshot and len(snapshot['cases'])!=len(names):raise UserError('Frozen summary selection and sources do not match.')
    folder=cases_root/'汇总报告';folder.mkdir(exist_ok=True);job=tempdir(folder/'_tmp','summary');configure_temp(job/'_runtime')
    engine.emit('Preparing selected-case summary…',job=str(job))
    try:
        for name in ['inputs','tables','figures','logs','sources','code']:(job/name).mkdir()
        dump(job/'inputs'/'selection.json',selection)
        settings=(validate_settings(presentation) if presentation is not None else read_settings(folder) if (folder/'plot_settings.json').exists() else validate_settings(load(frozen/'inputs'/'plot_settings.json')) if frozen else read_settings(cases[0]))
        dump(job/'inputs'/'plot_settings.json',settings)
        records=[];grain_frames=[];distance_frames=[];case_presentations=[]
        for index,case in enumerate(cases,1):
            check_cancel(job);code=f'C{index:02d}';relative=Path('sources')/code
            if frozen:
                record=dict(snapshot['cases'][index-1]);relative=Path(record['copied_case'])
                engine.emit(f'Redrawing frozen summary {index}/{len(cases)}：'+record['name'],job=str(job))
                shutil.copytree(within(frozen/relative,frozen),job/relative)
                root=job/relative/'result';case_settings,settings_source=frozen_case_settings(cases_root,record,job/relative)
                redrawn=case_settings!=run_settings(root)
                if redrawn:
                    engine.emit('Redrawing both case reports with saved plot settings: '+record['name'],job=str(job))
                    from self_service_report import redraw_saved_reports
                    redraw_saved_reports(job/relative,root,case_settings)
                    configure_temp(job/'_runtime')
                dump(job/relative/'plot_settings.json',case_settings)
                grains=pd.read_csv(root/'tables'/'grain_sizes_all.csv');grains.insert(0,'case_code',record['code']);grains.insert(1,'case_name',record['name'])
                distances=pd.read_csv(root/'tables'/'01_observed_distances.csv') if (root/'tables'/'01_observed_distances.csv').exists() else pd.DataFrame()
                if len(distances):distances.insert(0,'case_code',record['code']);distances.insert(1,'case_name',record['name'])
            else:
                result=ensure_result(case,job);check_cancel(job)
                engine.emit(f'Export {index}/{len(cases)}：'+load(case/'case.json')['name'],job=str(job))
                copy_case(case,result,job/relative);record,grains,distances=collect_case(case,result,code,relative)
                case_settings=run_settings(result);settings_source=str(case/'plot_settings.json');redrawn=False
                dump(job/relative/'plot_settings.json',case_settings)
            case_presentations.append(dict(code=record['code'],name=record['name'],settings=case_settings,settings_source=settings_source,redrawn_from_saved_data=redrawn))
            records.append(record);grain_frames.append(grains)
            if len(distances):distance_frames.append(distances)
        grain=pd.concat(grain_frames,ignore_index=True);distances=pd.concat(distance_frames,ignore_index=True) if distance_frames else pd.DataFrame(columns=['case_code','case_name','object_id','distance_um','distance_capped_um'])
        pooled=summary_tables(records,grain,distances,job)
        from acceleration import report as acceleration_report
        dump(job/'logs'/'compute_backend.json',acceleration_report())
        dump(job/'inputs'/'case_plot_settings.json',case_presentations)
        check_cancel(job);engine.emit('Drawing per-field comparisons and pooled distributions…',job=str(job))
        figures=comparison_figures(records,job,settings)
        from grain_size_analysis import distribution_figures
        figures+=distribution_figures(job,grain,[]);dump(job/'logs'/'figures.json',figures)
        dump(job/'inputs'/'source_manifest.json',dict(created=datetime.now().isoformat(),cases=records,pooled_inference=False,plot_design_version='summary-publication-v3',revised_from=str(frozen) if frozen else None))
        check_cancel(job);report_documents(records,pooled,figures,job)
        for name in ['acceleration.py','app_runtime.py','batch_summary.py','summary_publication.py','revise_summary_figures.py','self_service_engine.py','self_service_report.py','grain_size_analysis.py','bright_segmentation.py','plot_settings.py','publication21_figures.py','area_redistribution21.py','analyze_review21.py','apply_review21.py','audit_pdf_text.py','audit_figure_collisions.py','audit_panel_alignment.py']:shutil.copyfile(ROOT/'code'/name,job/'code'/name)
        check_cancel(job);engine.emit('Packaging summary and selected cases…',job=str(job))
        with zipfile.ZipFile(job/'Export.zip','w',zipfile.ZIP_DEFLATED) as archive:
            for file in job.rglob('*'):
                if file.is_file() and file.name!='Export.zip' and file.name!='.temporary-owner.json' and '_runtime' not in file.relative_to(job).parts:archive.write(file,file.relative_to(job))
        check_cancel(job);runtime=job/'_runtime'
        if runtime.exists():engine._remove_owned_tree(within(runtime,job))
        stamp='summary_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:4];destination=folder/stamp
        publication_mode=publish_summary(job,destination,folder);(destination/'.temporary-owner.json').unlink()
        dump(destination/'logs'/'publication.json',dict(method=publication_mode,complete=True))
        with zipfile.ZipFile(destination/'Export.zip','a',zipfile.ZIP_DEFLATED) as archive:archive.write(destination/'logs'/'publication.json','logs/publication.json')
        (folder/'Latest_summary_report.html').write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url='+stamp+'/Summary.html"><a href="'+stamp+'/Summary.html">Open latest summary report</a>',encoding='utf-8')
        dump(folder/'latest_summary.json',dict(report=str(destination/'Summary.html'),pdf=str(destination/'Summary.pdf'),cases=names,created=datetime.now().isoformat()))
        engine.emit(f'Exported {len(records)} selected cases, including both per-field reports, pooled statistics and separate figures.',event='complete',case=str(cases[0]),summary=str(destination),report=str(destination/'Summary.html'))
        return destination
    except Exception as error:
        if not isinstance(error,engine.Cancelled):
            log=ROOT/'logs'/('summary_failed_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.json');dump(log,dict(error=str(error),selection=selection))
        raise
    finally:
        if job.exists() and (job/'.temporary-owner.json').exists():safe_remove(job,folder/'_tmp')
