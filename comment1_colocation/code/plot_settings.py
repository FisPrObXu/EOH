"""Editable presentation options; analysis parameters and reviewed masks stay frozen."""
import math
import re

SERIES_NAMES = dict(observed='Observed / pooled observed distances', baseline='Random expectation / baseline', even='Uniform layout', random_example='First random example',
                    random_cloud='Random-curve ensemble', upper='95% random upper bound / reference range', individual='Individual observed curves',
                    bright='Gold (bright)', gray='Chalcopyrite (dark gray)', hist_bars='Grain-size bars', density='Histogram density curve', mean_values='Mean-distance values',
                    grain_ci='Grain-size sample confidence bands')
SERIES_DEFAULT = dict(visible=True,label='',color='',linestyle='auto',linewidth=0.)


DEFAULTS = dict(schema_version=1, histogram_mode='auto', bright_bins=10, gray_bins=20,
                bright_bin_width_um=.1, gray_bin_width_um=.2, bar_width_fraction=1.,
                show_density_curve=False, density_bandwidth_factor=1.,
                curve_style='line', x_tick_count=8, random_curve_count=4999,
                figure_width_mm=0.,figure_height_mm=0.,custom_margins=False,
                margin_left_pct=16.,margin_right_pct=4.,margin_bottom_pct=25.,margin_top_pct=12.,
                legend_position='below',legend_font_size_pt=0.,legend_font_family='template',legend_text_color='#222222',
                legend_columns=2,legend_frame=False,legend_anchor_x=1.05,legend_anchor_y=1.,axis_font_size_pt=0.,grid_mode='hide')


def validate_settings(value=None):
    value = dict(value or {})
    settings = {key: value.get(key, default) for key, default in DEFAULTS.items()}
    if settings['schema_version'] != 1:
        raise ValueError('Unknown plot-settings version.')
    if settings['histogram_mode'] not in ('auto', 'count', 'width'):
        raise ValueError('Binning must be automatic, count or width.')
    if settings['curve_style'] not in ('step', 'line', 'smooth'):
        raise ValueError('Cumulative-curve display must be step, line or smooth.')
    for key, low, high in [('bright_bins', 1, 200), ('gray_bins', 1, 200), ('x_tick_count', 3, 10), ('random_curve_count', 1, 4999)]:
        number = float(settings[key])
        if not math.isfinite(number) or not number.is_integer() or not low <= number <= high:
            label='Random-curve count' if key=='random_curve_count' else key
            raise ValueError(f'{label} must be {low}–{high} and an integer within this range.')
        settings[key] = int(number)
    for key in ('bright_bin_width_um', 'gray_bin_width_um', 'bar_width_fraction', 'density_bandwidth_factor'):
        number = float(settings[key])
        if not math.isfinite(number) or number <= 0:
            raise ValueError('Bin widths, bar width fraction and smoothing factor must be finite and positive.')
        settings[key] = number
    if not .1 <= settings['bar_width_fraction'] <= 1:
        raise ValueError('Bar width fraction must be 0.1–1; it controls gaps without changing bins.')
    if not .1 <= settings['density_bandwidth_factor'] <= 5:
        raise ValueError('Density smoothing factor must be 0.1–5.')
    if not isinstance(settings['show_density_curve'], bool):
        raise ValueError('Density display must be a Boolean.')
    for key in ['figure_width_mm','figure_height_mm','legend_font_size_pt','axis_font_size_pt']:
        v=float(settings[key]);low,high=(60,250) if key=='figure_width_mm' else (40,250) if key=='figure_height_mm' else (5,20)
        if not math.isfinite(v) or (v!=0 and not low<=v<=high):raise ValueError(f'{key} must be 0 (template) or {low}–{high}。')
        settings[key]=v
    for key in ['margin_left_pct','margin_right_pct','margin_bottom_pct','margin_top_pct']:
        v=float(settings[key])
        if not math.isfinite(v) or not 0<=v<=70:raise ValueError('Margins must be 0–70%.')
        settings[key]=v
    if settings['margin_left_pct']+settings['margin_right_pct']>85 or settings['margin_top_pct']+settings['margin_bottom_pct']>85:raise ValueError('Margins must retain at least 15% of canvas width and height for plotting.')
    if settings['legend_position'] not in ['template','right','below','upper right','upper left','lower right','lower left','custom','none']:raise ValueError('Unknown legend position.')
    if settings['grid_mode'] not in ['template','show','hide']:raise ValueError('Unknown grid setting.')
    if settings['legend_font_family'] not in ['template','Arial','Microsoft YaHei','SimHei','Times New Roman']:raise ValueError('Select a legend font from the list.')
    columns=float(settings['legend_columns'])
    if not math.isfinite(columns) or not columns.is_integer() or not 0<=columns<=4:raise ValueError('Legend columns must be 0 (template) or 1–4.')
    settings['legend_columns']=int(columns)
    for key in ['legend_anchor_x','legend_anchor_y']:
        v=float(settings[key])
        if not math.isfinite(v) or not -1<=v<=2:raise ValueError('Custom legend coordinates must be −1 to 2; 0–1 spans the plotting area.')
        settings[key]=v
    for key in ['custom_margins','legend_frame']:
        if not isinstance(settings[key],bool):raise ValueError('Layout switches must be Booleans.')
    if not re.fullmatch(r'#[0-9a-fA-F]{6}',settings['legend_text_color']):raise ValueError('Legend text color must use #RRGGBB.')
    series=value.get('series_options',{})
    settings['series_options']={}
    for role in SERIES_NAMES:
        item={**SERIES_DEFAULT,**series.get(role,{})}
        if not isinstance(item['visible'],bool) or not isinstance(item['label'],str) or len(item['label'])>120:raise ValueError('Invalid object visibility or legend label (maximum 120 characters).')
        if item['color'] and not re.fullmatch(r'#[0-9a-fA-F]{6}',item['color']):raise ValueError('Object color must be blank (template) or #RRGGBB.')
        if item['linestyle'] not in ['auto','-','--','-.',':']:raise ValueError('Unknown line style.')
        width=float(item['linewidth'])
        if not math.isfinite(width) or not 0<=width<=4:raise ValueError('Line width must be 0 (template) to 4 pt.')
        item['linewidth']=width;settings['series_options'][role]=item
    return settings


def tag(artist,*roles,label_role=None):
    artist._bse_roles=roles;artist._bse_label_role=label_role or roles[-1]
    return artist


def reference_style(value):
    """Change appearance only; preserve simulation count, binning and object choices."""
    settings=validate_settings(value)
    settings.update(curve_style='line',x_tick_count=8,figure_width_mm=0.,figure_height_mm=0.,
                    custom_margins=False,legend_position='below',legend_columns=2,
                    legend_font_size_pt=0.,legend_font_family='template',legend_frame=False,
                    legend_text_color='#222222',axis_font_size_pt=0.,grid_mode='hide')
    for role in ('observed','baseline','upper','even','random_example','random_cloud','individual'):
        settings['series_options'][role].update(color='',linestyle='auto',linewidth=0.)
    return settings


def register_legend(target,handles=None,**kwargs):
    fig=target.figure if hasattr(target,'figure') and target.figure is not None else target
    if handles is None:handles=target.get_legend_handles_labels()[0]
    for handle in handles:
        if not getattr(handle,'_bse_roles',()):
            role=role_from_label(handle.get_label())
            if role:tag(handle,role)
    if not hasattr(fig,'_bse_legends'):fig._bse_legends=[]
    fig._bse_legends.append((target,list(handles),dict(kwargs)));fig._bse_statistical=True
    return target.legend(handles=handles,**kwargs)


def role_from_label(label):
    text=str(label).lower()
    if 'individual observed' in text:return 'individual'
    if 'random layouts' in text:return 'random_cloud'
    if 'upper' in text or '95%' in text:return 'upper'
    if 'evenly' in text:return 'even'
    if 'first' in text and 'random' in text:return 'random_example'
    if 'baseline' in text or 'expectation' in text:return 'baseline'
    if 'observed' in text:return 'observed'
    if 'chalcopyrite' in text:return 'gray'
    if 'gold' in text:return 'bright'
    if 'kde' in text:return 'density'
    return None


def apply_appearance(fig,settings):
    """Apply presentation to tagged statistical artists; microscopy geometry is untouched."""
    if not getattr(fig,'_bse_statistical',False):return
    import numpy as np
    from matplotlib.font_manager import FontProperties
    s=validate_settings(settings);position=s['legend_position'];axes=fig.axes
    width=s['figure_width_mm'] or fig.get_figwidth()*25.4;height=s['figure_height_mm'] or fig.get_figheight()*25.4
    if position=='right' and not s['figure_width_mm']:width=max(width,183.)
    if position=='below':
        if not s['figure_width_mm']:width=max(width,135.)
        if not s['figure_height_mm']:height=max(height,120.)
    fig.set_size_inches(width/25.4,height/25.4,forward=False)
    legend_specs=getattr(fig,'_bse_legends',[])
    for ax in axes:
        box=ax.get_position();left,bottom,right,top=box.x0,box.y0,box.x1,box.y1
        if s['custom_margins']:
            left=s['margin_left_pct']/100;right=1-s['margin_right_pct']/100;bottom=s['margin_bottom_pct']/100;top=1-s['margin_top_pct']/100
        elif position=='right':right=min(right,.66)
        elif position=='below':
            count=max([sum(all(s['series_options'][r]['visible'] for r in getattr(h,'_bse_roles',())) for h in handles) for _,handles,_ in legend_specs] or [1])
            columns=s['legend_columns'] or 2;font=s['legend_font_size_pt'] or 6.5
            bottom=max(bottom,(math.ceil(count/columns)*(font*1.55)+28)/(height/25.4*72))
        ax.set_position([left,bottom,right-left,top-bottom])
        if s['axis_font_size_pt']:
            for text in [ax.xaxis.label,ax.yaxis.label,*ax.get_xticklabels(),*ax.get_yticklabels()]:text.set_fontsize(s['axis_font_size_pt'])
        if s['grid_mode']=='show':ax.grid(True,color='#e5e8ea',lw=.4)
        elif s['grid_mode']=='hide':ax.grid(False)
    def style_artist(artist):
        roles=getattr(artist,'_bse_roles',())
        if not roles:return
        artist.set_visible(all(s['series_options'][r]['visible'] for r in roles))
        for role in roles:
            option=s['series_options'][role]
            if option['color']:
                if hasattr(artist,'set_color'):artist.set_color(option['color'])
                elif hasattr(artist,'set_facecolor'):artist.set_facecolor(option['color'])
            if option['linestyle']!='auto' and hasattr(artist,'set_linestyle'):artist.set_linestyle(option['linestyle'])
            if option['linewidth'] and hasattr(artist,'set_linewidth'):artist.set_linewidth(option['linewidth'])
        custom=s['series_options'][getattr(artist,'_bse_label_role',roles[-1])]['label']
        if custom and hasattr(artist,'set_label'):artist.set_label(custom)
    for ax in axes:
        for artist in ax.get_children():style_artist(artist)
    # A right-hand legend shares the original mean-value column; reflow values into row labels.
    if position=='right' and hasattr(fig,'_bse_mean_rows'):
        ax=axes[0];show=s['series_options']['mean_values']['visible']
        ax.set_yticks(range(len(fig._bse_mean_rows)),[f'{r["case_code"]} (n = {r["N"]})'+(f'\n{r["observed_mean_um"]:.3f} / {r["random_expected_mean_um"]:.3f}' if show else '') for r in fig._bse_mean_rows])
        if show:ax.set_ylabel('Case (n)\nObserved / Random',fontsize=6.5)
        for artist in ax.texts:
            if 'mean_values' in getattr(artist,'_bse_roles',()):artist.set_visible(False)
    if s['axis_font_size_pt']:
        for ax in axes:
            for text in [ax.xaxis.label,ax.yaxis.label,*ax.get_xticklabels(),*ax.get_yticklabels()]:text.set_fontsize(s['axis_font_size_pt'])
    for ax in axes:
        if ax.get_legend() is not None:ax.get_legend().remove()
    for legend in list(fig.legends):legend.remove()
    for target,handles,kwargs in legend_specs:
        for handle in handles:style_artist(handle)
        handles=[h for h in handles if all(s['series_options'][r]['visible'] for r in getattr(h,'_bse_roles',()))]
        if not handles or position=='none':continue
        default_size=kwargs.pop('fontsize',None);size=s['legend_font_size_pt'] or default_size or 6.5
        family=s['legend_font_family'];family='Arial' if family=='template' else family
        prop=FontProperties(family=[family,'Microsoft YaHei','Arial','DejaVu Sans'],size=size)
        kwargs.update(prop=prop,labelcolor=s['legend_text_color'],frameon=s['legend_frame'])
        if s['legend_columns']:kwargs['ncol']=s['legend_columns']
        destination=target
        if position=='right':destination=axes[0];kwargs.update(loc='upper left',bbox_to_anchor=(1.08,1.),borderaxespad=0,ncol=s['legend_columns'] or 1)
        elif position=='below':destination=fig;kwargs.update(loc='lower left',bbox_to_anchor=(axes[0].get_position().x0,.012),borderaxespad=0,ncol=s['legend_columns'] or 2)
        elif position in ['upper right','upper left','lower right','lower left']:
            destination=axes[0];kwargs.pop('bbox_to_anchor',None);kwargs.update(loc=position,borderaxespad=.5)
        elif position=='custom':destination=axes[0];kwargs.update(loc='upper left',bbox_to_anchor=(s['legend_anchor_x'],s['legend_anchor_y']),borderaxespad=0)
        destination.legend(handles=handles,**kwargs)
    # Measure the actual rendered legend and axis label instead of estimating
    # legend rows: label spacing, font and columns all affect its height.
    if position=='below' and not s['custom_margins'] and fig.legends:
        fig.canvas.draw()
        renderer=fig.canvas.get_renderer()
        legend_top=max(legend.get_window_extent(renderer).y1 for legend in fig.legends)
        for ax in axes:
            if not ax.xaxis.label.get_visible() or not ax.xaxis.label.get_text():continue
            label_bottom=ax.xaxis.label.get_window_extent(renderer).y0
            shift=max(0.,legend_top+6*fig.dpi/72-label_bottom)/fig.bbox.height
            if shift:
                box=ax.get_position()
                if box.y1-box.y0-shift<.15:raise ValueError('The below-plot legend needs more room. Increase canvas height, reduce legend text or columns, or use a right-side legend.')
                ax.set_position([box.x0,box.y0+shift,box.width,box.height-shift])
    fig._bse_applied_settings=s


def read_settings(case):
    import json
    path = case / 'plot_settings.json'
    return validate_settings(json.loads(path.read_text(encoding='utf-8')) if path.exists() else None)


def run_settings(out):
    import json
    path = out / 'inputs' / 'plot_settings.json'
    return validate_settings(json.loads(path.read_text(encoding='utf-8')) if path.exists() else None)


def histogram_edges(x, kind, settings):
    import numpy as np
    lo, hi = float(x.min()), float(x.max())
    if lo == hi:
        lo, hi = max(0., lo * .7), max(hi * 1.3, lo + .01)
    mode = settings['histogram_mode']
    if mode == 'width':
        width = settings[kind + '_bin_width_um']
        first = max(0, math.floor(lo / width))
        last = max(first + 1, math.ceil(hi / width))
        if last - first > 400:
            raise ValueError('The selected bin width produces over 400 bins. Increase it in Plot settings.')
        return np.arange(first, last + 1) * width
    n = settings[kind + '_bins'] if mode == 'count' else min(40, max(1, len(np.histogram_bin_edges(x, bins='fd')) - 1))
    return np.linspace(lo, hi, n + 1)


def density_curve(x, edges, settings):
    """Reflection at zero keeps support positive; scale density to histogram counts."""
    import numpy as np
    from scipy.stats import gaussian_kde
    if len(x) < 2 or np.ptp(x) == 0:
        return None, 'Density curve omitted: fewer than 2 grains or all sizes identical.'
    kde = gaussian_kde(x, bw_method=lambda obj: obj.scotts_factor() * settings['density_bandwidth_factor'])
    xx = np.linspace(max(0., float(edges[0])), float(edges[-1]), 400)
    density = kde(xx) + kde(-xx)
    return (xx, density, density * len(x) * float(edges[1] - edges[0])), ('Few grains: the smooth curve is illustrative only.' if len(x) < 5 else '')


def draw_cdf(ax, x, y, settings, **kwargs):
    import numpy as np
    x, y = np.asarray(x, float), np.asarray(y, float)
    role=kwargs.pop('role',None) or role_from_label(kwargs.get('label',''))
    if settings['curve_style'] == 'step':
        result=ax.step(x, y, where='post', **kwargs)
        for line in result:
            if role:tag(line,role)
        return result
    # Retain the last cumulative value at tied distances; never add observations.
    xx, reverse_indices = np.unique(x[::-1], return_index=True)
    yy = y[len(x) - 1 - reverse_indices]
    if settings['curve_style'] == 'smooth' and len(xx) >= 3:
        from scipy.interpolate import PchipInterpolator
        grid = np.unique(np.r_[xx, np.linspace(xx[0], xx[-1], 500)])
        result=ax.plot(grid, np.clip(PchipInterpolator(xx, yy)(grid), 0., 1.), **kwargs)
    else:result=ax.plot(xx, yy, **kwargs)
    for line in result:
        if role:tag(line,role)
    return result


def describe(settings):
    s = validate_settings(settings)
    mode = s['histogram_mode']
    bins = ('Automatic bins (Freedman–Diaconis suggestion, maximum 40)' if mode == 'auto' else
            f'Specified bin count: gold {s["bright_bins"]}, chalcopyrite {s["gray_bins"]} bins' if mode == 'count' else
            f'Specified bin width: gold {s["bright_bin_width_um"]:g} μm, chalcopyrite {s["gray_bin_width_um"]:g} μm; edges aligned to multiples of bin width')
    style = {'step': 'step', 'line': 'linear connections', 'smooth': 'monotone smooth connections'}[s['curve_style']]
    density = (f'Zero-boundary reflection density curve; Scott bandwidth × {s["density_bandwidth_factor"]:g}; scaled to counts using grain count × bin width; omitted for fewer than 2 grains or identical sizes' if s['show_density_curve'] else 'No smooth density curve')
    hidden='、'.join(SERIES_NAMES[k] for k,v in s['series_options'].items() if not v['visible']) or 'none'
    presentation=f'Statistical canvas width / height: {s["figure_width_mm"]:g}/{s["figure_height_mm"]:g} mm (0 = template); legend position: {s["legend_position"]}, font size: {s["legend_font_size_pt"]:g} pt (0 = template). Hidden objects: {hidden}. Visibility changes affect figures only; tables retain all data.'
    return f'{bins}; bar width fraction {s["bar_width_fraction"]:g}；{density}. Cumulative display: {style}; approximately {s["x_tick_count"]} major x intervals. Where available, distance comparisons show the first {s["random_curve_count"]} random-layout cumulative curves in generation order, one per layout; 4999 shows all evaluated layouts. The first layout map is shown. Above 200 curves, the random background is rasterized at 600 dpi; all raw curves remain in tables. Center-model tests use all 4999 layouts. Each layout retains its grain count. Linear and smooth connections display the original distance grid; tests use the recorded p-values.'+presentation
