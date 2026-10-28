"""Publication figures from the frozen reviewed field 21 and exclusion-model results."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import PercentFormatter, MaxNLocator
from matplotlib.transforms import ScaledTranslation
from scipy.stats import binom
from audit_panel_alignment import require_matplotlib_panel_alignment

OBS='#AA3377';GRAY='#0072B2';BRIGHT='#D55E00';EVEN='#009E73';RANDOM='#E69F00';NULL='#AAB4BF'


def style():
    matplotlib.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','DejaVu Sans'],
        'font.size':7,'axes.labelsize':7,'axes.titlesize':7,'xtick.labelsize':6.5,'ytick.labelsize':6.5,
        'legend.fontsize':6.5,'pdf.fonttype':42,'svg.fonttype':'none','axes.spines.top':False,
        'axes.spines.right':False,'axes.linewidth':.65,'xtick.major.width':.65,'ytick.major.width':.65,
        'legend.frameon':False,'savefig.facecolor':'white'})


def label_panels(fig,axes,letters):
    for ax,letter in zip(axes,letters):
        ax.text(0,1.075,letter,transform=ax.transAxes+ScaledTranslation(-11/72,0,fig.dpi_scale_trans),
            fontsize=8,fontweight='bold',va='bottom',ha='left')


def export(fig,out,stem):
    require_matplotlib_panel_alignment(fig,json_out=out/'logs'/f'{stem}.alignment.json',strict=True)
    fig.savefig(out/'figures'/f'{stem}.pdf',dpi=600)
    fig.savefig(out/'figures'/f'{stem}.svg',dpi=600)
    fig.savefig(out/'figures'/f'{stem}.png',dpi=600)
    # TIFF is a lossless RGB companion; PDF/SVG retain editable text and vector strokes.
    with Image.open(out/'figures'/f'{stem}.png') as raster:
        raster.convert('RGB').save(out/'figures'/f'{stem}.tiff',compression='tiff_lzw',dpi=(600,600))
    plt.close(fig)


def images(out):
    raw=np.array(Image.open(out/'inputs'/'21_native_grayscale.png'))
    C=np.array(Image.open(out/'inputs'/'21_C.png'))>0
    W=np.array(Image.open(out/'inputs'/'21_W.png'))>0
    bright=np.array(Image.open(out/'inputs'/'21_bright_labels.tif'))>0
    observed=pd.read_csv(out/'data'/'01_observed_distances.csv')
    scale=.06099
    fig,axs=plt.subplots(1,2,figsize=(7.2047244094,3.4251968504))
    fig.subplots_adjust(left=.045,right=.99,bottom=.18,top=.88,wspace=.08)
    for ax,title in zip(axs,['Original BSE image','Reviewed outlines and analysis window']):
        # The PDF embeds the original raster, without resolution-increasing resampling.
        ax.imshow(raw,cmap='gray',vmin=0,vmax=255,interpolation='none')
        ax.set_xlim(-.5,1023.5);ax.set_ylim(800,-.5);ax.set_axis_off();ax.set_title(title,pad=8)
        ax.plot([55,55+10/scale],[750,750],color='black',lw=1.8)
        ax.text(75+10/scale,750,'10 μm',va='center',fontsize=7)
    axs[1].contour(C,levels=[.5],colors=[GRAY],linewidths=.45)
    axs[1].contour(bright,levels=[.5],colors=[BRIGHT],linewidths=.45)
    axs[1].contour(W,levels=[.5],colors=['#222222'],linewidths=.65,linestyles='--')
    axs[1].scatter(observed.centroid_x_px,observed.centroid_y_px,s=13,facecolors='none',edgecolors=OBS,linewidths=.85)
    legend=[Line2D([],[],color=GRAY,lw=.9,label='Gray-region outlines'),
        Line2D([],[],color=BRIGHT,lw=.9,label='Retained bright outlines (53)'),
        Line2D([],[],color='#222222',lw=.8,ls='--',label='Original protected window W'),
        Line2D([],[],color=OBS,marker='o',markerfacecolor='none',ls='none',markersize=4,label='Analysed centroids (15)')]
    fig.legend(handles=legend,loc='lower center',bbox_to_anchor=(.52,.025),ncol=2,columnspacing=2.3,handlelength=2)
    label_panels(fig,axs,'ab')
    export(fig,out,'Figure_1_Reviewed_Image_vx')


def statistics(out):
    summary=json.loads((out/'logs'/'analysis_summary.json').read_text(encoding='utf-8'))
    curves=pd.read_csv(out/'data'/'positive_distance_curves.csv')
    sim=np.load(out/'data'/'directional_simulations.npz')
    denominator=summary['N']*summary['admissible_pixels']
    positive=sim['sim_positive_numerator']/denominator
    critical=float(np.partition(sim['sim_positive_numerator'],4749)[4749]/denominator)
    (out/'logs'/'directional_envelope.json').write_text(json.dumps(dict(B=4999,critical=critical,
        order_one_based=4750,grid_um=curves.r_um.to_list(),side='upper',
        meaning='95% simultaneous upper acceptance boundary for positive CDF excess on the fixed grid'),indent=2))
    fig,axs=plt.subplots(2,2,figsize=(7.2047244094,6.2992125984))
    fig.subplots_adjust(left=.09,right=.98,bottom=.16,top=.93,wspace=.34,hspace=.85)
    a,b,c,d=axs.ravel()
    a.step(curves.r_um,curves.F0_outside_gray,where='post',color='#555555',ls='--',lw=1,label='Exact null baseline')
    a.step(curves.r_um,np.minimum(1,curves.F0_outside_gray+critical),where='post',color='#999999',ls=(0,(1,2)),lw=.8,label='95% simultaneous upper limit')
    for column,color,line,name in [('Observed positions',OBS,'-','Observed'),('Uniform layout (outside gray)',EVEN,'-.','Evenly spread example'),
        ('One random layout (outside gray)',RANDOM,':','One random example')]:
        a.step(curves.r_um,curves[column],where='post',color=color,ls=line,lw=1.25,label=name)
    a.set(xlim=(.25,5),ylim=(0,1.02),xlabel='Distance to gray region (μm)',ylabel='Cumulative fraction')
    a.set_xticks([.25,1,2,3,4,5]);a.set_yticks([0,.25,.5,.75,1]);a.yaxis.set_major_formatter(PercentFormatter(1))
    a.set_title('Observed and redistributed distances',loc='left',pad=9)
    a.legend(loc='upper left',bbox_to_anchor=(0,-.28),ncol=2,columnspacing=.8,handlelength=2,borderaxespad=0)
    b.hist(positive,bins=24,color=NULL,edgecolor='white',linewidth=.4)
    b.axvline(summary['positive_CDF_max'],color=OBS,lw=1.3,label='Observed')
    b.axvline(critical,color='#555555',ls='--',lw=.9,label='Upper critical value (95%)')
    b.set(xlabel='Maximum positive CDF difference',ylabel='Simulations')
    b.set_title(f'Directional curve test  |  p = {summary["positive_CDF_p_MC"]:.4f}',loc='left',pad=9)
    b.yaxis.set_major_locator(MaxNLocator(4,integer=True))
    b.legend(loc='upper left',bbox_to_anchor=(0,-.28),borderaxespad=0)
    k=np.arange(16);probability=binom.pmf(k,15,summary['within_1um_null_fraction'])
    c.bar(k,probability,width=.8,color=[OBS if x>=5 else NULL for x in k],edgecolor='white',linewidth=.4)
    c.axvline(5,color=OBS,lw=1.1,label='Observed: 5 particles')
    c.set(xlim=(-.7,15.7),xlabel='Particles within 1 μm',ylabel='Null probability')
    c.set_xticks([0,3,5,10,15]);c.yaxis.set_major_formatter(PercentFormatter(1));c.yaxis.set_major_locator(MaxNLocator(4))
    c.set_title(f'Near-region count  |  p = {summary["within_1um_p_exact"]:.4f}',loc='left',pad=9)
    c.legend(handles=[Line2D([],[],color=OBS,lw=1.1,label='Observed: 5; null expectation: 3.65'),
        Line2D([],[],color=OBS,lw=5,label='Right-tail probability (exact)')],loc='upper left',bbox_to_anchor=(0,-.28),borderaxespad=0)
    means=sim['sim_mean_capped_5um']
    d.hist(means,bins=24,color=NULL,edgecolor='white',linewidth=.4)
    d.axvline(summary['observed_capped_mean_5um'],color=OBS,lw=1.3,label='Observed mean: 1.912 μm')
    d.axvline(summary['null_capped_mean_5um'],color='#555555',ls='--',lw=.9,label='Exact null mean: 1.929 μm')
    d.set(xlabel='Mean distance capped at 5 μm (μm)',ylabel='Simulations')
    d.yaxis.set_major_locator(MaxNLocator(4,integer=True))
    d.set_title(f'Overall distance  |  p = {summary["overall_closer_p_MC"]:.4f}',loc='left',pad=9)
    d.legend(loc='upper left',bbox_to_anchor=(0,-.28),borderaxespad=0)
    label_panels(fig,axs.ravel(),'abcd')
    export(fig,out,'Figure_2_Null_Comparison_vx')


def draw_all(out):
    style();images(out);statistics(out)
