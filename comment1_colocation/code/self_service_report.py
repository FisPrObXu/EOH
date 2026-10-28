"""Generic, native-coordinate scientific figures and Chinese self-service reports.

One independent figure per file. Baseline and upper MC reference always belong
to the same model. Figure text remains editable; experimental pixels are kept.
"""
import html
import json
import math
from pathlib import Path
import shutil
import zipfile

import numpy as np
import pandas as pd
from PIL import Image
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams.update({'pdf.fonttype':42,'svg.fonttype':'none'})
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.collections import PolyCollection,LineCollection
from matplotlib.patches import Rectangle
from matplotlib.ticker import PercentFormatter,MaxNLocator

from publication21_figures import style,OBS,EVEN,RANDOM,NULL
from audit_panel_alignment import require_matplotlib_panel_alignment
from audit_pdf_text import audit_pdf as text_audit
from audit_figure_collisions import audit_pdf as collision_audit
from review21_display import saved_model,COLORS
from self_service_engine import ROOT,load,dump,UserError
from plot_settings import validate_settings,run_settings,draw_cdf,describe as describe_plot_settings
from plot_settings import apply_appearance,register_legend,tag


def save(fig,out,stem,figures,title):
    import fitz
    presentation=run_settings(out);apply_appearance(fig,presentation)
    require_matplotlib_panel_alignment(fig,json_out=out/'logs'/f'{stem}.alignment.json',strict=True)
    fig.savefig(out/'figures'/f'{stem}.pdf',dpi=600)
    fig.savefig(out/'figures'/f'{stem}.svg',dpi=600)
    fig.savefig(out/'figures'/f'{stem}.png',dpi=600)
    with Image.open(out/'figures'/f'{stem}.png') as im:im.convert('RGB').save(out/'figures'/f'{stem}.tiff',compression='tiff_lzw',dpi=(600,600))
    plt.close(fig)
    file=out/'figures'/f'{stem}.pdf';text=text_audit(file.read_bytes(),minimum_pt=5);collisions=collision_audit(file)
    dump(out/'logs'/f'{stem}.text.json',text);dump(out/'logs'/f'{stem}.collision.json',collisions)
    if not text['auditable'] or text['below_minimum_count'] or collisions['summary']['fail']:raise UserError('Figure layout checks failed. No report was published. See the case logs.')
    native=[]
    with fitz.open(file) as doc:
        page=doc[0];size=[page.rect.width,page.rect.height]
        for raster in page.get_images(full=True):
            for rect in page.get_image_rects(raster[0]):native.append(min(raster[2]/(rect.width/72),raster[3]/(rect.height/72)))
        # Screen-only QA thumbnails; publication raster companions above are 600 dpi.
        page.get_pixmap(matrix=fitz.Matrix(160/72,160/72)).save(out/'logs'/f'{stem}.preview.png')
    if getattr(fig,'_bse_applied_settings',None):dump(out/'logs'/f'{stem}.appearance.json',presentation)
    figures.append(dict(stem=stem,title=title,width_pt=size[0],height_pt=size[1],native_dpi=min(native) if native else None,
                        minimum_font_pt=text['minimum_found_pt'],collision=collisions['summary']))


def pixel_regions(ax,mask,color):
    y,x=np.where(mask)
    if len(x):
        vertices=np.stack([np.column_stack([x,y]),np.column_stack([x+1,y]),np.column_stack([x+1,y+1]),np.column_stack([x,y+1])],axis=1)
        ax.add_collection(PolyCollection(vertices,facecolors=color,edgecolors='none',antialiaseds=False))


def scale_length(width_um):
    if not math.isfinite(width_um) or width_um<=0:raise UserError('Physical image width must be positive.')
    target=width_um*.16
    power=10**math.floor(math.log10(target))
    return max(v*power for v in [.1,.2,.5,1,2,5] if v*power<=target)


def plate(d,title,background):
    h,w=d['g'].shape;mm=min(89,max(60,w*25.4/(320*.88)));image_h=mm*.88*h/w;height=image_h+32
    fig=plt.figure(figsize=(mm/25.4,height/25.4));ax=fig.add_axes([.06,24/height,.88,image_h/height])
    ax.imshow(background,cmap='gray' if background.ndim==2 else None,vmin=0 if background.ndim==2 else None,vmax=255 if background.ndim==2 else None,
              interpolation='none',extent=(0,w,h,0))
    ax.set(xlim=(0,w),ylim=(h,0));ax.set_axis_off();ax.set_title(title,pad=8)
    length=scale_length(w*d['s']);x0=.06;x1=x0+.88*length/(w*d['s']);yy=19/height
    fig.add_artist(Line2D([x0,x1],[yy,yy],transform=fig.transFigure,color='black',lw=1.8))
    fig.text(x1+2/mm,yy,f'{length:g} μm',fontsize=7,va='center')
    return fig,ax


def legend(fig):
    fig.legend(handles=[Line2D([],[],color=COLORS['gray'],lw=1,label='Dark regions'),
        Line2D([],[],color=COLORS['bright'],lw=1,label='Bright regions'),
        Line2D([],[],color=COLORS['window'],ls='--',lw=1,label='Protected window W')],loc='lower center',bbox_to_anchor=(.5,.01),ncol=1)


def wpaths(ax,field):
    for path in field['window_paths']:
        p=np.asarray(path,float)+.5
        if len(p)>2:p=np.vstack([p,p[0]])
        ax.plot(p[:,0],p[:,1],color=COLORS['window'],ls=(0,(4,2.7)),lw=.5)


def layout_plate(d,field,labels,title,free=False):
    background=np.ones((*d['C'].shape,3));background[~d['A']]=[.91,.92,.93];background[d['A']&~d['W']]=[.97,.97,.98]
    if free:background[d['W']&~d['C']]=[.98,.92,.81]
    background[d['C']]=[.8,.87,.93]
    fig,ax=plate(d,title,background);h,w=d['C'].shape
    ax.contour(np.arange(w)+.5,np.arange(h)+.5,d['C'],[.5],colors=[COLORS['gray']],linewidths=.35)
    wpaths(ax,field)
    if labels is not None:pixel_regions(ax,labels>0,COLORS['bright'])
    legend(fig);return fig


def plot_axes():
    fig,ax=plt.subplots(figsize=(3.5039370079,3.5433070866));fig.subplots_adjust(left=.16,right=.97,bottom=.30,top=.88)
    return fig,ax


def random_layout_curves(out,model,n,grid,settings):
    """Use the existing evaluation bank in generation order; do not resimulate/select."""
    with np.load(out/'tables'/f'{model}_simulations.npz') as bank:
        counts=bank['counts'][:settings['random_curve_count']].copy()
        total=len(bank['counts'])
    if counts.shape[1]!=len(grid) or n<=0:raise UserError('Random cumulative curves do not match the distance grid or particle count.')
    cdfs=counts/n
    frame=pd.DataFrame(cdfs,columns=[f'r_{r:.10g}_um' for r in grid])
    frame.insert(0,'layout_index',np.arange(1,len(frame)+1))
    filename=f'{model}_random_layout_curves.csv';frame.to_csv(out/'tables'/filename,index=False,encoding='utf-8-sig')
    return cdfs,dict(model=model,requested=settings['random_curve_count'],displayed=len(frame),available=total,
                     particles_per_layout=int(n),selection='first layouts in generation order; no result-based selection',
                     grid_um=list(map(float,grid)),table=filename,layout_image_index=1)


def random_curve_cloud(ax,x,curves,settings):
    """Draw every selected realization; batching and rasterization keep large banks usable."""
    x=np.asarray(x,float);y=np.asarray(curves,float);count=len(y)
    if settings['curve_style']=='step':xx=np.repeat(x,2)[1:];yy=np.repeat(y,2,axis=1)[:,:-1]
    elif settings['curve_style']=='smooth' and len(x)>=3:
        from scipy.interpolate import PchipInterpolator
        xx=np.unique(np.r_[x,np.linspace(x[0],x[-1],500)])
        yy=np.clip(PchipInterpolator(x,y,axis=1)(xx),0.,1.)
    else:xx=x;yy=y
    vertices=np.stack([np.broadcast_to(xx,yy.shape),yy],axis=2)
    color='#76A3C1';alpha=max(.025,min(.32,1.3/math.sqrt(count)))
    collection=tag(LineCollection(vertices,colors=color,linewidths=.35,alpha=alpha,zorder=1,rasterized=count>200),'random_cloud')
    ax.add_collection(collection)
    return tag(Line2D([],[],color=color,lw=1,label=f'Random layouts (n = {count})'),'random_cloud')


def cdf_plot(curves,title,extra=False,settings=None,random_cdfs=None):
    settings=validate_settings(settings)
    fig,ax=plot_axes()
    random_handle=random_curve_cloud(ax,curves.r_um,random_cdfs,settings) if random_cdfs is not None else None
    for col,color,ls,label in [('baseline','#222222','--','Random baseline'),('upper','#999999',':','Upper MC reference (95%)'),('observed',OBS,'-','Observed')]:
        draw_cdf(ax,curves.r_um,curves[col],settings,color=color,ls=ls,lw=1.1,label=label)
    if extra:
        draw_cdf(ax,curves.r_um,curves.even,settings,color=EVEN,ls='-.',lw=1,label='Evenly spread example')
        draw_cdf(ax,curves.r_um,curves.random_example,settings,color=RANDOM,ls=':',lw=1,label='First random example')
    ax.set(xlim=(curves.r_um.iloc[0],curves.r_um.iloc[-1]),ylim=(0,1.02),xlabel='Distance to dark region (μm)',ylabel='Cumulative fraction')
    ax.yaxis.set_major_formatter(PercentFormatter(1));ax.set_yticks([0,.25,.5,.75,1]);ax.xaxis.set_major_locator(MaxNLocator(settings['x_tick_count']));ax.set_title(title,loc='left',pad=8)
    handles,labels=ax.get_legend_handles_labels()
    if random_handle is not None:handles.append(random_handle)
    register_legend(ax,handles=handles,loc='upper left',bbox_to_anchor=(0,-.28),ncol=2,columnspacing=.6,handlelength=1.7,borderaxespad=0)
    return fig


def ptext(value):return 'not valid' if value is None else f'{value:.4f}'


def plots(case,out,d,observed,point,area,review):
    style();figures=[];presentation=run_settings(out)
    fig,ax=plate(d,'Original BSE image',d['g']);save(fig,out,'00_Original',figures,'Original grayscale image')
    _,field,objects,_=saved_model(out/'inputs'/'review.json','1',project_root=case)
    fig,ax=plate(d,'Reviewed bright and dark regions',d['g']);wpaths(ax,field)
    for r in objects.values():
        if r['object_class']=='gray_component_rejected':continue
        color=COLORS['bright' if r['object_class']=='candidate_bright_particle' else 'gray']
        for path in r['paths']:
            if not path:continue
            if len(path)==1:ax.add_patch(Rectangle(path[0],1,1,fill=False,edgecolor=color,lw=.45));continue
            p=np.asarray(path,float)+.5
            if len(p)>2:p=np.vstack([p,p[0]])
            ax.plot(p[:,0],p[:,1],color=color,lw=.45,ls='--' if r['decision']=='exclude' else '-')
    legend(fig);save(fig,out,'01_Classified',figures,'Reviewed bright / dark outlines')
    obslabels=np.array(Image.open(out/'masks'/'observed_labels.tif'))
    save(layout_plate(d,field,obslabels,'Observed regions (native area)'),out,'02_Observed_Layout',figures,'Observed bright-region layout')
    save(layout_plate(d,field,None,'Free region: W outside dark',free=True),out,'03_Free_Region',figures,'Allowed redistribution domain')
    for stem,title,kind in [('04_Even_Layout','Uniform layout','even'),('05_Random_Layout','First random layout','random')]:
        if area['available']:labels=np.array(Image.open(out/'masks'/f'{kind}_labels.tif'));caption=title+' (actual equalized areas)'
        else:
            frame=pd.read_csv(out/'tables'/('point_evenly_spread.csv' if kind=='even' else 'point_random_example.csv'))
            labels=np.zeros(d['C'].shape,np.uint8);labels[frame.grid_y_px,frame.grid_x_px]=1;caption=title+' (centers only; single pixels have no area meaning)'
        save(layout_plate(d,field,labels,'Evenly spread layout' if kind=='even' else 'First random layout'),out,stem,figures,caption)
    curves=pd.read_csv(out/'tables'/'point_curves.csv')
    random_cdfs,point_cloud=random_layout_curves(out,'point',point['N'],curves.r_um,presentation)
    point_cloud['displayed_layout_image']='05_Random_Layout' if not area['available'] else None
    cloud_records=dict(point=point_cloud)
    save(cdf_plot(curves,'Point-location model',settings=presentation,random_cdfs=random_cdfs),out,'06_Point_Curves',figures,'Center model: observed, selected random curves and references')
    if area['available']:
        curves=pd.read_csv(out/'tables'/'area_curves.csv')
        random_cdfs,area_cloud=random_layout_curves(out,'area',area['N'],curves.r_um,presentation)
        area_cloud['displayed_layout_image']='05_Random_Layout'
        cloud_records['area']=area_cloud
        save(cdf_plot(curves,'Equal-area design comparison',True,presentation,random_cdfs),out,'07_Area_Curves',figures,'Equal-area design: selected random curves and observed / uniform references')
    dump(out/'logs'/'random_layout_curves.json',cloud_records)
    sim=np.load(out/'tables'/'point_simulations.npz');fig,ax=plot_axes()
    _,_,bars=ax.hist(sim['statistic'],bins=24,color=NULL,edgecolor='white',linewidth=.4)
    for bar in bars:tag(bar,'random_cloud')
    ax.axvline(point['observed_T'],color=OBS,lw=1.2,label='Observed')
    ax.axvline(point['critical'],color='#555555',ls='--',lw=.9,label='Upper reference (95%)')
    ax.set(xlabel='Maximum positive CDF difference',ylabel='Simulations');ax.set_title('Curve test | p = '+ptext(point['curve_p']),loc='left',pad=8)
    ax.yaxis.set_major_locator(MaxNLocator(4,integer=True));register_legend(ax,loc='upper left',bbox_to_anchor=(0,-.28),borderaxespad=0)
    save(fig,out,'08_Curve_Test',figures,'Random distribution of the primary whole-curve statistic')
    fig,ax=plot_axes();k=np.arange(point['N']+1);prob=np.bincount(sim['near'],minlength=point['N']+1)/point['B'];count=point['observed_near']
    bars=ax.bar(k,prob,color=[OBS if v>=count else NULL for v in k],width=.8,edgecolor='white',linewidth=.4)
    for bar in bars:tag(bar,'random_cloud')
    tag(ax.axvline(count,color=OBS,lw=1.1),'observed')
    xmax=min(point['N'],max(count,int(sim['near'].max()))+2);ticks=[0,count]
    for v in MaxNLocator(4,integer=True).tick_values(0,max(1,xmax)):
        if 0<=v<=xmax and min(abs(v-x) for x in ticks)>=max(1,.12*xmax):ticks.append(v)
    ax.set_xticks(sorted(set(ticks)));ax.set(xlim=(-.7,xmax+.7),xlabel='Near-region count',ylabel='Simulated probability')
    ax.yaxis.set_major_formatter(PercentFormatter(1));ax.yaxis.set_major_locator(MaxNLocator(4));ax.set_title('Near-region count',loc='left',pad=8)
    register_legend(ax,handles=[Line2D([],[],color=OBS,lw=1,label=f'Observed: {count}; expected: {point["expected_near"]:.2f}')],loc='upper left',bbox_to_anchor=(0,-.28),borderaxespad=0)
    save(fig,out,'09_Near_Count',figures,'Random distribution of near-region counts')
    fig,ax=plot_axes();_,_,bars=ax.hist(sim['mean'],bins=24,color=NULL,edgecolor='white',linewidth=.4)
    for bar in bars:tag(bar,'random_cloud')
    ax.axvline(point['observed_mean'],color=OBS,lw=1.2,label=f'Observed: {point["observed_mean"]:.3g} μm')
    ax.axvline(point['reference_mean'],color='#555555',ls='--',lw=.9,label=f'Random baseline: {point["reference_mean"]:.3g} μm')
    ax.set(xlabel='Mean distance capped at analysis limit (μm)',ylabel='Simulations');ax.set_title('Mean-distance test | p = '+ptext(point['mean_p']),loc='left',pad=8)
    ax.yaxis.set_major_locator(MaxNLocator(4,integer=True));register_legend(ax,loc='upper left',bbox_to_anchor=(0,-.28),borderaxespad=0)
    save(fig,out,'10_Mean_Test',figures,'Random distribution of capped mean distances')
    return figures


def summary_text(point):
    if not point['supported']:return 'Some observed centers lie inside dark regions, outside the exclusive center-model domain. All observations are retained, but formal test interpretation is deferred. Check the review issues.'
    if point['curve_p']>=.05:return 'The data do not provide sufficient evidence against the specified uniform random-center model. Near-distance fractions and effect sizes may be described, but an overall distance advantage is not established.'
    if point['all_grid_at_least_reference'] and point['mean_p']<.05:return 'On the prespecified distance grid, the observed distribution favors shorter distances and has a smaller capped mean. This supports spatial proximity beyond the specified uniform random-center model in this field.'
    return 'The prespecified grid shows a near-distance cumulative advantage over the uniform random-center model. Interpret its extent using the full curve and mean; it does not establish shorter distances at every scale.'


def build_report(case,out,d,observed,point,area,review,bundle=True):
    import fitz
    cfg=load(case/'config.json');meta=load(case/'case.json');a=cfg['analysis'];figures=plots(case,out,d,observed,point,area,review)
    name=html.escape(meta['name']);near=a['near_um'];cap=a['rmax_um'];revision=review['revision']
    source=out/'inputs'/'native.png';shutil.copyfile(case/'report'/'1_native_grayscale.png',source)
    flags=[]
    if not review.get('human_review_confirmed',False):flags.append('This is an automatic candidate analysis. Outlines and exclusions are not human-confirmed; numerical results describe the candidate segmentation and are not final mineral-phase statistics.')
    if not point['supported']:flags.append('Observed centers inside dark regions: '+', '.join(point['zero_ids'])+'. These points are retained; tail probabilities from an incompatible model are not treated as valid p-values.')
    if area['available']:
        if area['actual_overlap_ids']:flags.append('Observed bright / dark pixel overlap requires review: '+', '.join(area['actual_overlap_ids'])+'. Check raster boundaries; do not alter real image geometry to fit a model.')
        if area['incompatible_ids']:flags.append('An equalized standard region does not fit at these observed centers: '+', '.join(area['incompatible_ids'])+'. This may reflect smaller original objects or the W boundary, rather than segmentation error. Equal-area results are design controls only.')
        if not area['same_count']:flags.append('Control and observed region counts differ. Compare layouts and distributions descriptively; no equal-sample-size formal test is claimed.')
    else:flags.append(area['reason'])
    for f in figures:
        if f['native_dpi'] and f['native_dpi']<300:flags.append(f['title']+f'At this displayed size, effective native resolution is approximately {f["native_dpi"]:.0f} dpi. Exporting at 600 dpi adds no image information.')
        if f['collision']['warn']:flags.append(f['title']+'Layout warnings are present. Inspect the corresponding previews before submission.')
    status='Human-reviewed' if review.get('human_review_confirmed',False) else 'Automatic candidates; review pending'
    header=f'<h1>{name}: spatial proximity analysis</h1><p><b>{status}</b>; saved revision {revision}; pixel size {d["s"]:g} μm; native image {d["g"].shape[1]}×{d["g"].shape[0]} pixels. A field is not automatically an independent sample replicate.</p>'
    intro=header+'<div class="key"><b>Main interpretation: </b>'+summary_text(point)+'</div>'
    intro+=f'<p>Included: {point["N"]} bright objects; within {near:g} μm: {point["observed_near"]} objects ({100*point["observed_fraction"]:.1f}%); random expectation: {point["expected_near"]:.2f} objects ({100*point["reference_fraction"]:.1f}%）。</p>'
    intro+=f'<p>{cap:g} μm capped mean distance: observed {point["observed_mean"]:.4g} μm, random expectation {point["reference_mean"]:.4g} μm. Whole-curve one-sided MC p = {ptext(point["curve_p"])}; mean-distance one-sided MC p = {ptext(point["mean_p"])}. MC resolution is 1/{point["B"]+1}; zero extreme simulations do not imply p = 0.</p>'
    if flags:intro+='<h2>Review issues and scope</h2><ul>'+''.join('<li>'+html.escape(s)+'</li>' for s in flags)+'</ul>'
    if point['zero_ids']:
        intro+='<p>Select these objects on the review page: '+', '.join(html.escape(x) for x in point['zero_ids'])+'. Original records and previous reports are retained.</p>'
    table=d['table'];nsmall=int((table.exclusion_reason=='below_auto_minimum').sum());nout=int(((table.kind=='bright')&table.eligible&~table.in_W).sum())
    methods=f'<h2>Method, step by step</h2><ol><li>Read native grayscale using the supplied scale and crop. Manual rectangles and automatically detected unreadable regions define A.</li><li>Protect the interior of A by {cap:g} μm to define W; inspect the orange window. Dark distance targets use the complete readable context, without cropping them to W first.</li><li>Apply all active edits from saved revision {revision} and retain manually added, redrawn or explicitly confirmed objects. A further {nsmall} original small bright candidates fail the size threshold, and {nout} retained bright centers lie outside W; see the object table.</li><li>Measure each equally weighted center to the nearest dark region. Objects beyond {cap:g} μm remain in the denominator, and means use the same distance cap. Curves start at {a["step_um"]:g} μm.</li><li>The center model fixes dark regions and W, then independently redistributes the same number of centers uniformly outside dark regions. Its baseline is computed exactly from all allowed native pixels.</li><li>Use 4999 simulations to compare the maximum positive cumulative-fraction difference across the grid; also report near counts and capped means. Simulations do not increase the number of independent samples.</li></ol>'
    methods+='<h2>Baseline and upper MC</h2><p>The baseline is the expected cumulative fraction under the specified random model. Upper MC is its 95% simulation reference upper bound on the prespecified grid. Baselines and bounds are paired within each model; center and equal-area model references are not interchangeable. This is not a measurement-error band for the observed curve.</p>'
    methods+='<h2>Plot settings for this revision</h2><p>'+html.escape(describe_plot_settings(run_settings(out)))+'</p>'
    from bright_segmentation import description as bright_description
    methods+=bright_description(cfg)
    clouds=load(out/'logs'/'random_layout_curves.json')
    methods+=f'<h2>Random layouts and result curves</h2><p>The center model shows {clouds["point"]["displayed"]} random curves, each representing one complete layout. They are the first layouts in generation order from the 4999 evaluation simulations, without selection by closeness to observations. Light-blue curves are neither measurement-error bands nor additional independent samples. Display count controls the number drawn; formal tests use all 4999.</p>'
    if 'area' in clouds:methods+=f'<p>The equal-area model separately shows {clouds["area"]["displayed"]} random curves from its own model. The first layout map corresponds to the first curve, highlighted in orange. Each model uses its own random results.</p>'
    else:methods+='<p>The first random layout map uses the center model and corresponds to layout 1 in the random-curve table.</p>'
    methods+='<p>tables/point_random_layout_curves.csv and, when available, area_random_layout_curves.csv store every displayed curve: one row per layout; layout_index=1 is the first example, and subsequent columns give cumulative fractions within specified distances. All 4999 results remain in the corresponding simulations.npz.</p>'
    if area['available']:
        counts={v:area['areas'].count(v) for v in sorted(set(area['areas']))};eq=' + '.join(f'{n}×{v}' for v,n in counts.items())
        methods+=f'<h2>Equal-area design controls</h2><p>Observed total area: {area["total_area_px"]} pixels, divided into {area["N"]} regions: {eq}. Each region satisfies the integer-pixel cap of 75% of the largest original bright region: {area["cap_area_px"]}. Simulated regions lie completely inside W and outside dark regions, without overlap. Whole-layout rejection sampling is used. The uniform layout illustrates coverage; the random map is the first valid layout under a fixed seed.</p>'
        methods+=f'<p>Equal-area random reference mean: {area["reference_mean"]:.4g} μm; uniform example: {area["even_mean"]:.4g} μm; first random example: {area["random_example_mean"]:.4g} μm. An independent set of 4999 layouts estimates the reference curve, so one random example does not replace the expected level. Equal-area tail fractions are design-specific comparisons; do not change counts, thresholds or windows to seek smaller p-values.</p>'
    methods+='<p>Bright / dark intensity classes do not independently identify chemical phases. The uniform model does not preserve grain clustering or spatial heterogeneity; rejecting it does not establish a specific trapping process or geological mechanism. Independent sample identities require experimental records.</p>'
    methods+='<h2>Result files</h2><p>Each figure is supplied separately as PDF, SVG and 600 dpi PNG/TIFF. tables contains object distances and simulation statistics; reviewed contains applied native labels; inputs and code preserve sources and code for this revision. Regenerate after further review edits.</p>'
    blocks=[]
    for i,f in enumerate(figures,1):
        stem=f['stem'];description='Each light-blue line is one center-model random result; darker lines show observations and matching references.' if stem=='06_Point_Curves' else 'Each light-blue line is one equal-area random result; orange marks the first layout example. Interpret these within the design constraints.' if stem=='07_Area_Curves' else 'Native area and scale retained; figures exported separately.'
        blocks.append(f'<h2>Figure {i}　{html.escape(f["title"])}</h2><p>{description}</p><p>'+ ' / '.join(f'<a href="../figures/{stem}.{e}">{e.upper()}</a>' for e in ['pdf','svg','png','tiff'])+f'</p><div class="viewport"><img src="../figures/{stem}.png" alt="{html.escape(f["title"])}"></div>')
    css='body{font-family:Arial,"Microsoft YaHei",sans-serif;max-width:1050px;margin:30px auto;padding:22px;line-height:1.8;color:#243342}h1{font-size:26px}h2{margin-top:32px}.key{background:#eef6f2;padding:15px;border-left:4px solid #42856d}.viewport{overflow:auto;border:1px solid #dce3eb}.viewport img{width:900px;max-width:none}.large .viewport img{width:2102px}a{color:#24669b}button{font:inherit;padding:8px 12px}'
    body=intro+'<p><button onclick="document.body.classList.toggle(\'large\')">Enlarge / restore images</button>\u3000<a href="Report.pdf">PDF report</a></p>'+methods+''.join(blocks)
    (out/'report'/'Report.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>'+name+' analysis report</title><style>'+css+'</style>'+body+'</html>',encoding='utf-8')
    # Text plus one independently exported figure per page; image size respects its native figure dimensions.
    pdf=out/'report'/'Report.pdf';writer=fitz.DocumentWriter(str(pdf));page=fitz.paper_rect('a4');box=page+(40,40,-40,-40)
    chunks=[intro,methods]
    for i,f in enumerate(figures,1):
        width=min(500,f['width_pt'],480*f['width_pt']/f['height_pt'])
        chunks.append(f'<h2>Figure {i}　{html.escape(f["title"])}</h2><p>Review revision {revision}; separate figures and full data are included.</p><img src="figures/{f["stem"]}.png" width="{width}">')
    for chunk in chunks:
        story=fitz.Story(html=chunk,user_css='body{font-family:sans-serif;font-size:10.5pt;line-height:1.65;color:#243342}h1{font-size:21pt}h2{font-size:14pt}p,li{margin:6pt 0}',archive=fitz.Archive(str(out)))
        more=1;count=0
        while more:
            device=writer.begin_page(page);more,_=story.place(box);story.draw(device);writer.end_page();count+=1
            if count>30:raise UserError('Report pagination failed. Check unusually tall or wide images.')
    writer.close()
    with fitz.open(pdf) as doc:
        if not len(doc):raise UserError('The PDF report is empty.')
        # These are report layout previews, separate from scientific PNG/TIFF exports.
        for i,p in enumerate(doc):p.get_pixmap(matrix=fitz.Matrix(100/72,100/72)).save(out/'logs'/f'report_page_{i+1:02d}.png')
    dump(out/'logs'/'figures.json',figures);dump(out/'logs'/'summary.json',dict(point=point,area=area,flags=flags,review_revision=revision))
    # Bind numeric outputs to this native data, with no silently dropped observations.
    q=observed[['grid_y_px','grid_x_px']].to_numpy();checks=dict(N_matches_table=len(observed)==point['N'],
        native_distances=bool(np.allclose(observed.distance_um,d['D'][q[:,0],q[:,1]],rtol=0,atol=1e-12)),
        protected_centers=bool(d['W'][q[:,0],q[:,1]].all()),all_4999_simulations=len(np.load(out/'tables'/'point_simulations.npz')['mean'])==4999,
        all_font_floors=all(f['minimum_font_pt']>=5 for f in figures),all_collision_audits_clear=all(f['collision']['fail']==0 for f in figures))
    if not all(checks.values()):raise UserError('Numerical / export consistency checks failed. Results were not published.')
    dump(out/'logs'/'validation.json',checks)
    for name in ['acceleration.py','app_runtime.py','self_service_engine.py','self_service_report.py','apply_review21.py','segmentation.py','bright_segmentation.py','analysis.py','analyze_review21.py','area_redistribution21.py','review21_display.py','publication21_figures.py','audit_pdf_text.py','audit_figure_collisions.py','audit_panel_alignment.py']:
        (out/'code').mkdir(exist_ok=True);shutil.copyfile(ROOT/'code'/name,out/'code'/name)
    shutil.copyfile(case/'inputs'/'review_dataset.json',out/'inputs'/'review_dataset.json')
    # The bundle is a result export; the full case folder retains original inputs and editable review history.
    files=[p for p in out.rglob('*') if p.is_file() and '_runtime' not in p.relative_to(out).parts and p.name!='.temporary-owner.json']
    if bundle:
        with zipfile.ZipFile(out/'Export.zip','w',zipfile.ZIP_DEFLATED) as z:
            for p in files:z.write(p,p.relative_to(out))


def redraw_saved_reports(case,out,settings):
    """Redraw from frozen masks, measurements and simulation banks; no analysis rerun."""
    from scipy import ndimage as ndi
    from grain_size_analysis import build_grain_report
    cfg=load(out/'inputs'/'config.json');review=load(out/'inputs'/'review.json')
    d={key:np.array(Image.open(out/'masks'/f'{key}.png'))>0 for key in ['A','W','C']}
    d.update(g=np.array(Image.open(case/'report'/'1_native_grayscale.png')),s=cfg['images']['1']['pixel_size_um'],
             table=pd.read_csv(out/'reviewed'/'tables'/'reviewed_objects.csv'),
             size_W=np.array(Image.open(out/'masks'/'grain_size_W.png'))>0)
    d['D']=ndi.distance_transform_edt(~d['C'])*d['s']
    dump(out/'inputs'/'plot_settings.json',validate_settings(settings))
    spatial_available=(out/'logs'/'point_summary.json').exists()
    if spatial_available:
        observed=pd.read_csv(out/'tables'/'01_observed_distances.csv');point=load(out/'logs'/'point_summary.json')
        area=load(out/'logs'/'area_summary.json')
        build_report(case,out,d,observed,point,area,review,bundle=False)
        path=out/'report'/'Report.html';content=path.read_text(encoding='utf-8')
        path.write_text(content.replace('<h1>','<p><a href="Grain_Size_Report.html">Open gold / chalcopyrite grain-size report</a></p><h1>',1),encoding='utf-8')
    grain=pd.read_csv(out/'tables'/'grain_sizes_all.csv');summaries=load(out/'logs'/'grain_size_summary.json')['phases']
    selected={kind:np.array(Image.open(out/'masks'/f'size_{kind}_labels.tif')) for kind in ['bright','gray']}
    build_grain_report(case,out,d,(grain,summaries,selected),review,spatial_available)
    for name in ['self_service_report.py','grain_size_analysis.py','plot_settings.py']:
        shutil.copyfile(ROOT/'code'/name,out/'code'/name)
    dump(out/'logs'/'presentation_redraw.json',dict(source='saved native masks, measurements and simulations',
         review_revision=review['revision'],analysis_rerun=False,settings=validate_settings(settings)))
