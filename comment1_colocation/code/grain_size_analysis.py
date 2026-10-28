"""Count-weighted 2-D equivalent-circle diameters of complete regions inside W.

Figure contract: independent microscopy plates, phase histograms and one size ECDF.
Python/Matplotlib, same 89 mm journal style as the spatial figures; editable
PDF/SVG, 600 dpi PNG/TIFF, >=5 pt glyphs and rendered collision checks.
"""
import html
import math
from pathlib import Path
import shutil
import numpy as np
import pandas as pd
from PIL import Image
from scipy import ndimage as ndi
from skimage.measure import regionprops
import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams.update({'pdf.fonttype':42,'svg.fonttype':'none'})
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator,PercentFormatter
from self_service_engine import ROOT,load,dump,UserError
from self_service_report import save,plate,plot_axes,wpaths,legend,pixel_regions
from publication21_figures import style
from review21_display import saved_model,COLORS


def measure_grains(d,out):
    cfg=load(out/'inputs'/'config.json');scale=d['s'];rows=[];selected={}
    from segmentation import protected_window
    guard=cfg['analysis'].get('size_guard_um',cfg['analysis']['rmax_um']);W,_=protected_window(d['A'],d['A'],scale,guard);d['size_W']=W
    Image.fromarray(W.astype(np.uint8)*255).save(out/'masks'/'grain_size_W.png')
    bright=np.array(Image.open(out/'reviewed'/'masks'/'1_bright_labels.tif'))
    source_gray=np.array(Image.open(out/'reviewed'/'masks'/'1_inclusion_labels.tif'))
    # Connected dark masks avoid counting overlapping reviewer outlines twice.
    dark=ndi.label(d['C'],np.ones((3,3)))[0].astype(np.int32)
    mapping=pd.read_csv(out/'reviewed'/'tables'/'reviewed_label_mapping.csv')
    for kind,labels in [('bright',bright),('gray',dark)]:
        keep=np.zeros(labels.shape,np.int32)
        for region in regionprops(labels):
            mask=region.image;localW=W[region.slice];area=int(region.area);whole=bool(localW[mask].all())
            center=tuple(np.floor(np.array(region.centroid)+.5).astype(int));in_w=bool(W[center])
            if kind=='bright':ids=mapping.loc[(mapping.kind==kind)&(mapping.reviewed_native_label==region.label),'object_id'].tolist()
            else:
                ids=mapping.loc[(mapping.kind==kind)&mapping.reviewed_native_label.isin(np.unique(source_gray[region.slice][mask])),'object_id'].tolist()
            enough=kind=='bright' or area*scale**2>=cfg['segmentation']['gray_min_area_um2']
            included=whole and enough
            rows.append(dict(region_id=('Au' if kind=='bright' else 'Ccp')+f'{region.label:04d}',source_object_ids=';'.join(ids),
                phase='Gold' if kind=='bright' else 'Chalcopyrite',kind=kind,area_px=area,area_um2=area*scale**2,
                equivalent_circle_diameter_um=math.sqrt(4*area/math.pi)*scale,
                major_axis_um=region.axis_major_length*scale,minor_axis_um=region.axis_minor_length*scale,
                centroid_x_px=region.centroid[1],centroid_y_px=region.centroid[0],centroid_in_W=in_w,whole_region_in_W=whole,
                included=included,exclusion_reason='' if included else 'crosses_or_outside_W' if not whole else 'post_union_gray_below_minimum',
                fewer_than_9_native_pixels=area<9))
            if included:keep[region.slice][mask]=region.label
        selected[kind]=keep
        Image.fromarray(keep).save(out/'masks'/f'size_{kind}_labels.tif',compression='tiff_deflate')
    columns=['region_id','source_object_ids','phase','kind','area_px','area_um2','equivalent_circle_diameter_um','major_axis_um','minor_axis_um','centroid_x_px','centroid_y_px','centroid_in_W','whole_region_in_W','included','exclusion_reason','fewer_than_9_native_pixels']
    table=pd.DataFrame(rows,columns=columns);table.to_csv(out/'tables'/'grain_sizes_all.csv',index=False,encoding='utf-8-sig')
    summaries=[]
    for kind in ['bright','gray']:
        f=table[(table.kind==kind)&table.included];f.to_csv(out/'tables'/('gold_grain_sizes.csv' if kind=='bright' else 'chalcopyrite_grain_sizes.csv'),index=False,encoding='utf-8-sig')
        x=f.equivalent_circle_diameter_um.to_numpy();record=dict(kind=kind,phase='Gold' if kind=='bright' else 'Chalcopyrite',N=len(f),total_candidates=int((table.kind==kind).sum()),excluded=int(((table.kind==kind)&~table.included).sum()),below_9px=int(f.fewer_than_9_native_pixels.sum()),total_area_um2=float(f.area_um2.sum()))
        for label,func in [('mean',np.mean),('median',np.median),('min',np.min),('max',np.max)]:record[label+'_um']=float(func(x)) if len(x) else None
        record['q25_um']=float(np.quantile(x,.25)) if len(x) else None;record['q75_um']=float(np.quantile(x,.75)) if len(x) else None;summaries.append(record)
    pd.DataFrame(summaries).to_csv(out/'tables'/'grain_size_summary.csv',index=False,encoding='utf-8-sig')
    checks=dict(ecd_from_native_area=bool(np.allclose(table.equivalent_circle_diameter_um,np.sqrt(4*table.area_um2/np.pi))),
        selected_regions_complete_in_W=all(bool(W[v>0].all()) for v in selected.values()),no_clipped_particle_areas=True,
        selected_table_counts_match_labels=all(len(np.unique(v[v>0]))==sum((table.kind==k)&table.included) for k,v in selected.items()))
    if not all(checks.values()):raise UserError('Native-pixel grain-size consistency check failed.')
    dump(out/'logs'/'grain_size_validation.json',checks);dump(out/'logs'/'grain_size_summary.json',dict(phases=summaries,size_guard_um=guard,size_window_area_um2=float(W.sum()*scale**2),definition='2D equivalent circle diameter sqrt(4A/pi); count-weighted; complete regions in size-analysis window only',checks=checks))
    return table,summaries,selected


def distribution_figures(out,table,summaries):
    from plot_settings import run_settings,histogram_edges,density_curve,draw_cdf,register_legend,tag
    settings=run_settings(out);figures=[];diagnostics={}
    for kind,stem,title,color in [('bright','11_Gold_Size_Distribution','Gold grain sizes',COLORS['bright']),('gray','12_Chalcopyrite_Size_Distribution','Chalcopyrite region sizes',COLORS['gray'])]:
        f=table[(table.kind==kind)&table.included];x=f.equivalent_circle_diameter_um.to_numpy();fig,ax=plot_axes()
        if len(x):
            edges=histogram_edges(x,kind,settings);counts,_=np.histogram(x,edges)
            _,_,patches=ax.hist(x,bins=edges,color=color,alpha=.82,edgecolor='white',linewidth=.4,rwidth=settings['bar_width_fraction'])
            for patch in patches:tag(patch,'hist_bars',kind)
            pd.DataFrame(dict(left_um=edges[:-1],right_um=edges[1:],count=counts,fraction=counts/len(x))).to_csv(out/'tables'/f'{kind}_size_histogram.csv',index=False,encoding='utf-8-sig')
            diagnostics[kind]=dict(N=len(x),bin_count=len(counts),edges_um=edges.tolist(),density_drawn=False,density_note='')
            if settings['show_density_curve']:
                result,note=density_curve(x,edges,settings);diagnostics[kind]['density_note']=note
                if result is not None:
                    xx,density,scaled=result;tag(ax.plot(xx,scaled,color='#222222',lw=1.1)[0],kind,'density')
                    diagnostics[kind]['density_drawn']=True
                    pd.DataFrame(dict(diameter_um=xx,density_per_um=density,expected_count_per_bin=scaled)).to_csv(out/'tables'/f'{kind}_size_density_curve.csv',index=False,encoding='utf-8-sig')
        else:ax.text(.5,.5,'No complete eligible regions in W',transform=ax.transAxes,ha='center',fontsize=7)
        ax.set(xlabel='Equivalent-circle diameter (μm)',ylabel='Grain count');ax.set_title(title,loc='left',pad=8)
        ax.xaxis.set_major_locator(MaxNLocator(settings['x_tick_count']));ax.yaxis.set_major_locator(MaxNLocator(4,integer=True));ax.set_ylim(bottom=0)
        handles=[tag(Line2D([],[],color=color,lw=2,label=f'n = {len(x)}; complete regions in W'),kind)]
        if diagnostics.get(kind,{}).get('density_drawn'):handles.append(tag(Line2D([],[],color='#222222',lw=1.1,label='KDE trend (count scale)'),kind,'density'))
        register_legend(ax,handles=handles,loc='upper left',bbox_to_anchor=(0,-.28),borderaxespad=0)
        save(fig,out,stem,figures,'Gold grain-size distribution' if kind=='bright' else 'Chalcopyrite grain-size distribution')
    fig,ax=plot_axes();curve=[]
    for kind,name,color in [('bright','Gold',COLORS['bright']),('gray','Chalcopyrite',COLORS['gray'])]:
        x=np.sort(table.loc[(table.kind==kind)&table.included,'equivalent_circle_diameter_um'].to_numpy());y=np.arange(1,len(x)+1)/max(1,len(x))
        if len(x):draw_cdf(ax,np.r_[0,x],np.r_[0,y],settings,color=color,lw=1.2,label=f'{name} (n = {len(x)})')
        curve.extend(dict(kind=kind,diameter_um=float(a),fraction=float(b)) for a,b in zip(x,y))
    pd.DataFrame(curve,columns=['kind','diameter_um','fraction']).to_csv(out/'tables'/'grain_size_ecdf.csv',index=False,encoding='utf-8-sig')
    ax.set(xlabel='Equivalent-circle diameter (μm)',ylabel='Cumulative grain fraction',ylim=(0,1.02),xlim=(0,None));ax.set_title('Grain-size cumulative distributions',loc='left',pad=8)
    ax.xaxis.set_major_locator(MaxNLocator(settings['x_tick_count']));ax.set_yticks([0,.25,.5,.75,1]);ax.yaxis.set_major_formatter(PercentFormatter(1));register_legend(ax,loc='upper left',bbox_to_anchor=(0,-.28),borderaxespad=0)
    save(fig,out,'13_Grain_Size_Curves',figures,'Cumulative grain-size distributions')
    dump(out/'logs'/'plot_settings_effective.json',dict(settings=settings,histograms=diagnostics))
    return figures


def build_grain_report(case,out,d,grain,review,spatial_available):
    import fitz
    style();table,summaries,selected=grain;figures=[];meta=load(case/'case.json');cfg=load(out/'inputs'/'config.json');confirmed=bool(review.get('human_review_confirmed',False));guard=cfg['analysis'].get('size_guard_um',cfg['analysis']['rmax_um'])
    _,field,objects,_=saved_model(out/'inputs'/'review.json','1',project_root=case)
    from review_editor import paths
    size_field=dict(field,window_paths=paths(d['size_W']))
    if not spatial_available:
        fig,ax=plate(d,'Original BSE image',d['g']);save(fig,out,'00_Original',figures,'Original grayscale image')
        fig,ax=plate(d,'Candidate regions with size-analysis window',d['g']);wpaths(ax,size_field)
        for r in objects.values():
            if r['object_class']=='gray_component_rejected':continue
            for path in r['paths']:
                if not path:continue
                pp=np.asarray(path,float)+.5
                if len(pp)>2:pp=np.vstack([pp,pp[0]])
                ax.plot(pp[:,0],pp[:,1],color=COLORS['bright' if r['object_class']=='candidate_bright_particle' else 'gray'],lw=.45)
        legend(fig);save(fig,out,'01_Classified',figures,'Bright / dark candidate outlines')
    figures+=distribution_figures(out,table,summaries)
    fig,ax=plate(d,f'Size window: {guard:g} μm guard; complete regions',d['g']);wpaths(ax,size_field)
    pixel_regions(ax,selected['gray']>0,COLORS['gray']);pixel_regions(ax,selected['bright']>0,COLORS['bright']);legend(fig)
    save(fig,out,'14_Grain_Size_Selection',figures,f'Complete grains included in size statistics ({guard:g} μm edge guard)')
    status='Human-reviewed results' if confirmed else 'Automatic candidates: outlines and hole / crack exclusions require review'
    name=html.escape(meta['name']);intro=f'<h1>{name}: grain sizes inside the safe window</h1><p><b>{status}</b>. Saved revision r{review["revision"]}; scale {d["s"]:.8g} μm/pixel.</p>'
    intro+='<p>Classes follow the user-supplied interpretation: dark gray = candidate chalcopyrite; bright white = candidate gold. The software does not independently identify mineral phases.</p>'
    intro+='<table><tr><th>Class</th><th>Count</th><th>Mean diameter (μm)</th><th>Median diameter (μm)</th><th>Excluded regions</th></tr>'
    for r in summaries:
        text=lambda value:'—' if value is None else f'{value:.4g}'
        intro+=f'<tr><td>{r["phase"]}</td><td>{r["N"]}</td><td>{text(r["mean_um"])}</td><td>{text(r["median_um"])}</td><td>{r["excluded"]}</td></tr>'
    intro+='</table>'
    methods=f'<h2>Methods and purpose</h2><ol><li>Retain native pixels, remove instrument text panels, and calibrate using the image scale bar or an explicit pixel size.</li><li>Remove voids and manual exclusions from the readable domain, then apply a grain-size edge guard of {guard:g} μm; distance tests retain a guard of {cfg["analysis"]["rmax_um"]:g} μm. The orange line on the grain-inclusion map marks the {guard:g} μm grain-size window. Orange lines in distance and null-model maps mark the distance window. Red hole / crack buffers use the specified radii; the safe window adds the edge guard.</li><li>Include only connected grains lying completely inside the grain-size window. Exclude boundary-crossing grains as whole objects; never count cropped fragments as smaller grains. Distance tests select by center, so counts can differ.</li><li>Area A = native pixel count × pixel size²; 2D equivalent-circle diameter d = √(4A/π). Major / minor axes and areas are also exported. This is not a true 3D sphere diameter.</li><li>Histograms show grain counts; cumulative curves show the fraction at or below a diameter, weighting each grain equally. Bin edges are exported with the tables.</li><li>Dark regions use connected masks, merging overlapping outlines to avoid double counting. Touching unresolved grains may form one region and require manual separation.</li></ol>'
    from plot_settings import run_settings,describe
    methods+='<h2>Plot settings for this revision</h2><p>'+html.escape(describe(run_settings(out)))+'</p>'
    from bright_segmentation import description as bright_description
    methods+=bright_description(cfg)
    diagnostics=load(out/'logs'/'plot_settings_effective.json')
    for kind,record in diagnostics['histograms'].items():
        if record.get('density_note'):methods+='<p>'+('Gold: ' if kind=='bright' else 'Chalcopyrite: ')+html.escape(record['density_note'])+'</p>'
    if any(r['N']==0 for r in summaries):methods+='<p>A zero count means no complete region qualifies under the current segmentation and safe window. It does not establish absence of that material from the original image.</p>'
    if meta.get('calibration',{}).get('method')=='visually_verified_2um_bar':methods+='<p>Pixel size was calibrated from the center-to-center cap distance of a 2 μm scale bar, with approximately ±1 native pixel endpoint uncertainty. Print DPI was not treated as a physical scale.</p>'
    if cfg['analysis'].get('exclusive_phases'):methods+='<p>Bright pixels are subtracted from the dark mask, preventing the same pixel from contributing to both phase areas.</p>'
    if cfg.get('adaptive_segmentation'):methods+='<p>Dark / void thresholds adapt to the image background; exact values are saved in config.json. Original displays and area calculations do not repaint intensities. Candidate boundaries still require review.</p>'
    for r in summaries:
        if r['below_9px']:methods+=f'<p>{r["phase"]}There are {r["below_9px"]} included objects smaller than 9 native pixels. Their size is sensitive to thresholds and pixel resolution; results describe segmented area without claiming subpixel boundary accuracy.</p>'
    methods+='<p>The independent experimental unit is the image / sample, not each grain. Fields are not automatically combined into a population distribution. Regenerating after review preserves this revision.</p>'
    shown=[]
    if spatial_available:
        for f in load(out/'logs'/'figures.json'):
            if f['stem'] in ['00_Original','01_Classified']:shown.append(f)
    shown+=figures;blocks=[]
    for f in shown:
        stem=f['stem'];blocks.append(f'<h2>{html.escape(f["title"])}</h2><p>'+ ' / '.join(f'<a href="../figures/{stem}.{ext}">{ext.upper()}</a>' for ext in ['pdf','svg','png','tiff'])+f'</p><img src="../figures/{stem}.png" style="width:850px;max-width:100%">')
    links='<p><a href="../tables/gold_grain_sizes.csv">Gold grain data</a> / <a href="../tables/chalcopyrite_grain_sizes.csv">Chalcopyrite grain data</a> / <a href="../tables/grain_sizes_all.csv">All candidates and exclusion reasons</a> / <a href="Grain_Size_Report.pdf">PDF report</a></p>'
    css='body{font:17px/1.8 Arial,"Microsoft YaHei",sans-serif;max-width:1000px;margin:35px auto;padding:20px;color:#243342}table{border-collapse:collapse}th,td{padding:10px;border:1px solid #ccd6df}h1{font-size:26px}h2{font-size:21px}a{color:#226bb0}'
    (out/'report'/'Grain_Size_Report.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>'+name+' grain-size report</title><style>'+css+'</style>'+intro+links+methods+''.join(blocks)+'</html>',encoding='utf-8')
    writer=fitz.DocumentWriter(str(out/'report'/'Grain_Size_Report.pdf'));page=fitz.paper_rect('a4');box=page+(40,40,-40,-40)
    chunks=[intro,methods]+[f'<h2>{html.escape(f["title"])}</h2><img src="figures/{f["stem"]}.png" width="{min(500,f["width_pt"],480*f["width_pt"]/f["height_pt"])}">' for f in shown]
    for chunk in chunks:
        story=fitz.Story(html=chunk,user_css='body{font-family:sans-serif;font-size:10.5pt;line-height:1.6}h1{font-size:20pt}h2{font-size:14pt}td,th{padding:6pt}table{border-collapse:collapse}',archive=fitz.Archive(str(out)));more=1;count=0
        while more:
            device=writer.begin_page(page);more,_=story.place(box);story.draw(device);writer.end_page();count+=1
            if count>30:raise UserError('Grain-size report pagination failed.')
    writer.close()
    with fitz.open(out/'report'/'Grain_Size_Report.pdf') as doc:
        for i,p in enumerate(doc):p.get_pixmap(matrix=fitz.Matrix(100/72,100/72)).save(out/'logs'/f'grain_report_page_{i+1:02d}.png')
    dump(out/'logs'/'grain_figures.json',figures)
