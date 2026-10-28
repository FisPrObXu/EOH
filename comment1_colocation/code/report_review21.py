"""Readable Chinese report and comparison figure for the reviewed field 21."""
import html
import json
import re
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.transforms import ScaledTranslation
from matplotlib.ticker import PercentFormatter
from audit_panel_alignment import require_matplotlib_panel_alignment

def create_figures(out,d,s,c,groups):
    matplotlib.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Microsoft YaHei','DejaVu Sans'],
        'font.size':8.5,'axes.labelsize':8.5,'axes.titlesize':9,'xtick.labelsize':8,'ytick.labelsize':8,
        'pdf.fonttype':42,'svg.fonttype':'none','axes.spines.top':False,'axes.spines.right':False,
        'legend.frameon':False,'axes.linewidth':.65})
    fig=plt.figure(figsize=(180/25.4,140/25.4))
    gs=fig.add_gridspec(2,3,height_ratios=[1,1.05]);fig.subplots_adjust(left=.09,right=.98,top=.94,bottom=.20,wspace=.30,hspace=.42)
    colors=['#AA3377','#168A78','#D17B17'];linestyles=['-','-.',':']
    image_axes=[]
    for col,((title,df),color) in enumerate(zip(groups.items(),colors)):
        ax=fig.add_subplot(gs[0,col]);image_axes.append(ax)
        ax.imshow(d['g'],cmap='gray',vmin=0,vmax=255,interpolation='nearest')
        ax.contour(d['C'],levels=[.5],colors=['#2878B5'],linewidths=.35)
        ax.contour(d['W'],levels=[.5],colors=['#333333'],linewidths=.55,linestyles='--')
        ax.scatter(df.centroid_x_px,df.centroid_y_px,s=16,facecolors='none',edgecolors=color,linewidths=.9)
        ax.plot([55,55+10/d['s']],[750,750],color='black',lw=1.6)
        ax.text(65+10/d['s'],750,'10 μm',va='center',fontsize=8)
        ax.set_xlim(-.5,1023.5);ax.set_ylim(800,-.5);ax.set_axis_off()
        ax.set_title(title+f'（{len(df)} objects)',pad=8)
    ax=fig.add_subplot(gs[1,0:2])
    ax.fill_between(c.r_um,c.lower,c.upper,step='post',color='.88',label='95% random envelope',lw=0)
    ax.step(c.r_um,c.F0,where='post',color='.4',ls='--',lw=1,label='Expected random level')
    for name,color,ls in zip(groups,colors,linestyles): ax.step(c.r_um,c[name],where='post',color=color,ls=ls,lw=1.4,label=name)
    ax.set(xlim=(0,5),ylim=(0,1),xlabel='Distance to nearest gray region (μm)',ylabel='Fraction within distance')
    ax.yaxis.set_major_formatter(PercentFormatter(1));ax.set_yticks([0,.25,.5,.75,1]);ax.set_xticks(range(6))
    ax.legend(loc='upper left',bbox_to_anchor=(0,-.26),ncol=2,fontsize=7.5,handlelength=2.2,columnspacing=1)
    ax.set_title('Earlier curve rise means more grains near gray regions',loc='left',pad=9)
    histogram=fig.add_subplot(gs[1,2])
    arrays=np.load(out/'tables'/'null_simulations.npz')
    values=arrays['sim_T'];maxval=max(values.max(),s['T_observed'])*1.05
    histogram.hist(values,bins=np.linspace(0,maxval,24),color='#ADB9C6',edgecolor='white',linewidth=.3)
    histogram.axvline(s['T_observed'],color=colors[0],lw=1.6)
    histogram.set(xlabel='Overall deviation',ylabel='Random layouts')
    histogram.yaxis.labelpad=-1
    histogram.set_title(f'4999 random layouts\np = {s["p"]:.4f}',pad=9)
    histogram.text(.98,.9,'Purple: observed',transform=histogram.transAxes,ha='right',fontsize=7.5,color=colors[0])
    for a,label in zip([*image_axes,ax,histogram],'abcde'):
        a.text(0,1.09,label,transform=a.transAxes+ScaledTranslation(-11/72,0,fig.dpi_scale_trans),fontsize=10.5,fontweight='bold',va='bottom')
    require_matplotlib_panel_alignment(fig,json_out=out/'logs'/'Figure_21_Three_Groups_vx.alignment.json',strict=True)
    for ext in ['pdf','svg','png']:fig.savefig(out/'figures'/f'Figure_21_Three_Groups_vx.{ext}',dpi=600)
    plt.close(fig)

def simple_table(headers,rows):
    return '<table><thead><tr>'+''.join('<th>'+html.escape(str(x))+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join(
        '<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table>'

def write_report(out,d,s,curves,groups,method):
    comparison=pd.read_csv(out/'tables'/'three_group_summary.csv')
    sensitivity=pd.read_csv(out/'tables'/'sensitivity_summary.csv')
    sim=np.load(out/'tables'/'null_simulations.npz');n_exceed=int((sim['sim_T_numerator']>=s['T_observed_numerator']).sum())
    info=d['info'];N=s['N'];f1=float(curves.loc[curves.r_um==1,'F0'].iloc[0]);obs=s['observed_within_1um']
    table_rows=[[r.group,int(r.N),f'{r.capped_mean_5um:.3f}',int(r.within_0_5um),int(r.within_1um),int(r.within_2um)] for _,r in comparison.iterrows()]
    observed=groups['Observed positions'];uniform=groups['Uniform layout'];random=groups['One random layout']
    names=['Observed positions','Uniform layout','One random layout']
    sorted_rows=[[k+1,*[f'{np.sort(groups[name].distance_to_in_image_gray_um.to_numpy())[k]:.4f}' for name in names]] for k in range(N)]
    sens_rows=[[r.condition,int(r.N),f'{r.p:.4f}','No departure from the random model detected' if not r.reject else 'Departure from the simple random model'] for _,r in sensitivity.iterrows()]
    subtitle=f'Based on reviewed field 21, save {info["revision"]}; 2026-10-25'
    parts=[f'<h1>21: three distance datasets and null-hypothesis test</h1><p class="subtitle">{subtitle}</p>',
      '<div class="key"><h2>Main result</h2>',
      f'<p>Reviewed field 21 contains <b>{N}</b> retained bright objects in the original eligible window. Under the no-position-preference random model, <b>p = {s["p"]:.4f}</b>。'
      'The data do not provide sufficient evidence that these objects are closer to gray regions than expected randomly. This does not prove absence of association.</p>',
      f'<p>Observed: <b>{obs}</b> points within 1 μm of gray regions. Placing the same number of random points in the same window gives an average of about <b>{s["expected_count_within_1um"]:.2f}</b>. The difference is approximately {obs-s["expected_count_within_1um"]:.2f} points, insufficient to exclude ordinary random variation.</p></div>',
      '<h2>1. Applying manual edits</h2>',
      f'<p>Using saved revision {info["revision"]}: added {info["added_gray_objects"]} gray regions and {info["added_bright_objects"]} bright objects; deleted {info["deleted_objects"]} original bright objects. The last active redraw is used. Undone actions are not applied, and repeated Keep actions do not increase grain counts.</p>',
      f'<p>The full image now has {info["eligible_bright"]} retained bright candidates and {info["gray_objects"]} gray regions. Formal comparison uses the original eligible window W, area <b>{s["W_area_um2"]:.3f} μm²</b>, including {N} bright objects. Of 16 added bright objects, 12 lie outside W. They remain in the complete object table.</p>',
      '<p><b>Why exclude centers outside W?</b>Image edges, voids and unreadable regions may hide nearby gray targets. To avoid interpreting missing targets as large distances, each used center has at least 5 μm of readable target context. Observed, uniform and random groups use the same window.</p>',
      '<h2>2. The three datasets</h2>',
      simple_table(['Group','Placement','Purpose'],[
        ['Observed positions','Centers of reviewed bright objects','Describe the observed image'],
        ['Uniform layout',f'Place the same {N} centers as evenly as possible in W, keeping gray regions fixed','Provide a uniform-layout reference'],
        ['One random layout',f'Place the same {N} centers independently and randomly in W once, keeping gray regions fixed','Illustrate one layout with no position preference']]),
      '<p>All groups retain the same count, window and gray geometry. Redistribution moves centers without splitting bright area into extra points. Uniform placement uses W alone, without targeting gray regions.</p>',
      '<p><b>Uniform and random differ:</b>uniform placement avoids crowding; random placement permits chance clusters and gaps. The uniform group is a spatial reference. The formal null test uses repeated random layouts, rather than one observed-versus-uniform comparison.</p>',
      '<h2>3. Measuring distances</h2>',
      '<p>Each bright-object center contributes its shortest distance to the nearest gray region, in μm. This is center-to-region, not center-to-center distance. A center inside a gray projection has distance zero; projected overlap alone does not establish interface contact.</p>',
      '<p>Each point contributes one distance, measured on native pixels. Field 21 uses 0.06099 μm/pixel. Observed and control positions use identical rounding and distance rules; gray targets are not cropped to W first.</p>',
      '<h2>4. Numerical comparison</h2>',
      simple_table(['Group','Count','Mean distance (μm)','Count ≤0.5 μm','Count ≤1 μm','Count ≤2 μm'],table_rows),
      '<p>All distances in these three groups are within 5 μm, so the means are ordinary arithmetic means. Complete data include native coordinates, IDs, distances to visible gray regions and exceedance of 5 μm.</p>',
      f'<p>Observed mean: {s["observed_capped_mean_5um"]:.3f} μm, below this random example at {s["one_random_capped_mean_5um"]:.3f} μm; uniform mean: {s["uniform_capped_mean_5um"]:.3f} μm, below the observed mean. <b>A single control can be misleading.</b>Repeated random layouts quantify ordinary variation.</p>',
      '<h2>5. The null hypothesis</h2>',
      '<p>The null assumes <b>no preference for gray regions: each allowed position is equally likely</b>. It provides a reference against which to assess the real image, rather than declaring the assumption true.</p>',
      '<ol><li><b>Fix the background:</b>keep gray regions, window and count unchanged.</li>'
      '<li><b>Generate 4999 random layouts:</b>replace the same number of points in W and remeasure, to quantify chance outcomes.</li>'
      '<li><b>Read distance curves:</b>x is distance to a gray region; y is the fraction within it. For example, 5/15 at 1 μm is 33.3%. An earlier rise indicates more nearby points.</li>'
      '<li><b>Compute expectation and envelope:</b>the expected level uses every allowed pixel exactly. The envelope describes typical whole-curve random variation for this count and prespecified distance range.</li>'
      '<li><b>Assess rarity:</b>compare the observed maximum deviation with the same statistic from all 4999 layouts, without selecting a favorable distance.</li></ol>',
      '<h2>6. Reading this test</h2>',
      f'<p>Among 4999 layouts, <b>{n_exceed}</b> have overall deviations at least as large as observed. Such a deviation is common under the model. The prespecified p-value is <b>{s["p"]:.4f}</b>, above the conventional 0.05 threshold.</p>',
      f'<p>At 1 μm, among 4999 layouts, <b>{s["random_trials_count_ge_observed_1um"]}</b> contain at least {obs} nearby points, a fraction of {s["random_trials_count_ge_observed_1um"]/4999:.1%}. Five nearby points are therefore not rare. This is an explanatory example, not a replacement for the formal whole-curve p-value.</p>',
      '<p><b>Supported conclusion:</b>within reviewed field 21 and its window, no clear departure from this simple random distance model was detected. This establishes neither specific chalcopyrite trapping nor absence of every possible association.</p>',
      '<h2>7. Figure guide</h2>',
      '<img class="figure" src="figures/Figure_21_Three_Groups_vx.png">',
      '<p class="caption">a–c: 15 observed, uniform and random positions. Blue = reviewed gray regions; dark dashed = W. d: cumulative curves, exact random expectation and 95% simultaneous random envelope. e: 4999 simulated deviations; purple = observed. Redistributed positions are model examples, not new experimental images.</p>',
      '<h2>8. Four supplementary checks</h2>',
      simple_table(['Condition','Included count','p','Result'],sens_rows),
      '<p>No departure was detected after moving gray boundaries by ±1 pixel, increasing the bright-area threshold or adding a 1 μm edge guard. The one-pixel perturbation is a numerical sensitivity check, not a measured boundary uncertainty. Fifteen points provide limited power for weak associations.</p>',
      '<h2>9. Next steps</h2>',
      '<p>Retain the observed result without tuning thresholds or windows for small p-values. Broader inference needs identified, deduplicated fields and checks of clustering, cracks and regional heterogeneity. Mineral identity remains unverified, so classes remain bright and gray candidates. Fields 21 and 24 are not pooled here.</p>',
      '<h2>Appendix: sorted distances</h2>',
      '<p>Rows show equal distance ranks across groups, <b>not matched grains</b>. Units: μm.</p>',
      simple_table(['Distance rank','Observed positions','Uniform layout','One random layout'],sorted_rows),
      '<h2>Data and reproduction</h2>',
      '<ul><li>tables/01_observed_distances.csv: 15 observed objects with original IDs.</li>'
      '<li>tables/02_evenly_spread_distances.csv: 15 uniform positions and distances.</li>'
      '<li>tables/03_random_example_distances.csv: 15 random-example positions and distances.</li>'
      '<li>tables/three_groups_sorted_distances.csv: machine-readable sorted table.</li>'
      '<li>tables/reviewed_objects.csv: all objects, including outside-window, deleted and undersized candidates.</li>'
      '<li>tables/null_simulations.npz: 4999 statistics, example random positions, uniform positions and distance map.</li>'
      '<li>masks/: reviewed native labels, C, A and W; logs/review_used.json snapshots the review used.</li></ul>',
      f'<p>Seed 2026102521; 15 points per layout; grid 0–5 μm, step 0.25 μm; B=4999. Uniform placement uses W-only centroidal coverage, with {method["iterations"]} iterations. It is not an independent uniform-random model. Simulations sample W pixel centers independently with replacement; duplicate positions are allowed and counts unchanged.</p>',
      '<p>Technical note: primary statistic max|Fobs−F0|; p=(1+number of simulated deviations ≥ observed)/5000. The critical value is the 4750th ordered simulation; only strict exceedance rejects. Integer numerators handle ties. The gray envelope is a 95% maximum-deviation simultaneous simulation envelope on the prespecified grid, not an observed-curve confidence interval. Distances above 5 μm remain in the denominator. Unknown targets outside the protected context prevent inference on uncapped true means.</p>']
    css='''body{font-family:sans-serif;color:#233342;font-size:10.5pt;line-height:1.65;margin:0}h1{font-size:23pt;color:#173d60;margin:0 0 8pt}h2{font-size:14pt;color:#245c88;margin:18pt 0 7pt;page-break-after:avoid}p{margin:6pt 0}b{font-weight:bold}.subtitle,.caption{color:#617180;font-size:9pt}.key{background:#edf4f9;border-left:4pt solid #2878b5;padding:10pt 12pt;margin:12pt 0}table{border-collapse:collapse;width:100%;font-size:9pt;margin:8pt 0}th,td{border:0.5pt solid #d7e0e8;padding:6pt;text-align:left}th{background:#edf2f7;font-weight:bold}.figure{width:100%}li{margin:5pt 0}'''
    body='\n'.join(parts)
    (out/'report'/'21_Null_Hypothesis_Explained_vx.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>21: null-hypothesis test explained</title><style>'+css+'html{background:#f1f4f7}body{max-width:1000px;margin:24px auto;padding:32px;background:white}img{max-width:100%}</style>'+body.replace('src="figures/','src="../figures/')+'</html>',encoding='utf-8')
    (out/'report'/'report_body.html').write_text(body,encoding='utf-8')
    (out/'logs'/'report_style.css').write_text(css,encoding='utf-8')
    (out/'report'/'21_Read_First.md').write_text(
      f'# Reviewed field 21: start here\n\nSaved revision {info["revision"]} applied; included {N} bright objects; W = {s["W_area_um2"]:.3f} μm²。\n\n'
      f'Group mean distances: observed {s["observed_capped_mean_5um"]:.3f} μm; uniform {s["uniform_capped_mean_5um"]:.3f} μm; random example {s["one_random_capped_mean_5um"]:.3f} μm。'
      f'Formal 4999-layout test p = {s["p"]:.4f}; no departure from the specified simple random model detected.\n\n'
      'Open [the full explanatory report](21_Null_Hypothesis_Explained_vx.html) or its PDF. Three distance CSVs are in the parent tables folder.\\n\\n'
      'Uniform placement is an illustrative reference and one random layout is an example; formal inference uses the overall comparison with 4999 random layouts.\\n',encoding='utf-8')

def render_report(out):
    import fitz
    body=(out/'report'/'report_body.html').read_text(encoding='utf-8')
    css=(out/'logs'/'report_style.css').read_text(encoding='utf-8')
    pdf=out/'report'/'21_Null_Hypothesis_Explained_vx.pdf'
    writer=fitz.DocumentWriter(str(pdf));page=fitz.paper_rect('a4');box=page+ (40,40,-40,-40)
    # Start the figure, the complete distance table, and technical appendix on fresh pages.
    # Explicit Story boundaries avoid orphaned headings in MuPDF's limited CSS pagination.
    chunks=re.split('(?=<h2>(?:7\\.|9\\.|Data and reproduction))',body)
    n=0
    for chunk in chunks:
        story=fitz.Story(html=chunk,user_css=css,archive=fitz.Archive(str(out)))
        more=1
        while more:
            device=writer.begin_page(page);more,_=story.place(box);story.draw(device);writer.end_page();n+=1
            if n>20:raise RuntimeError('Report layout did not finish')
    writer.close()
    doc=fitz.open(pdf)
    for k,p in enumerate(doc): p.get_pixmap(dpi=130).save(out/'logs'/f'report_page_{k+1}.png')
    for stem in ['Figure_21_Three_Groups_vx']:
        f=fitz.open(out/'figures'/f'{stem}.pdf');f[0].get_pixmap(dpi=180).save(out/'report'/f'{stem}_preview.png')
    return len(doc)

if __name__=='__main__':
    import argparse
    from apply_review21 import ROOT
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'_tmp'/'field21_reviewed_stage');args=p.parse_args();out=args.output
    from PIL import Image
    d={k:np.array(Image.open(out/'masks'/f'21_{k}.png'))>0 for k in ['C','W','A']}
    d.update(g=np.array(Image.open(ROOT/'report'/'21_native_grayscale.png')),s=.06099,
        info=json.loads((out/'logs'/'review_application.json').read_text(encoding='utf-8')),
        table=pd.read_csv(out/'tables'/'reviewed_objects.csv'))
    summary=json.loads((out/'logs'/'summary.json').read_text(encoding='utf-8'))
    curves=pd.read_csv(out/'tables'/'distance_curves_and_null_envelope.csv')
    groups={n:pd.read_csv(out/'tables'/f) for n,f in zip(['Observed positions','Uniform layout','One random layout'],
        ['01_observed_distances.csv','02_evenly_spread_distances.csv','03_random_example_distances.csv'])}
    method=json.loads((out/'logs'/'uniform_method.json').read_text(encoding='utf-8-sig'))
    create_figures(out,d,summary,curves,groups);write_report(out,d,summary,curves,groups,method)
    print('Report PDF pages:',render_report(out))
