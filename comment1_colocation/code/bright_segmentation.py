"""Native-pixel bright candidates: local contrast seeds and per-particle boundaries.

The boundary is an operational intensity contour, not a chemical phase identity
or a subpixel size measurement. No distance-test result enters detection.
"""
import numpy as np
from scipy import ndimage as ndi
from skimage.segmentation import watershed

PRESETS = {
    'balanced':dict(bright_min_contrast=20.,bright_noise_sigma=4.,bright_peak_min_gray=0.),
    'sensitive':dict(bright_min_contrast=12.,bright_noise_sigma=3.,bright_peak_min_gray=0.),
    'strict':dict(bright_min_contrast=28.,bright_noise_sigma=5.,bright_peak_min_gray=0.),
}


def defaults(sensitivity='balanced',fraction=.35):
    if sensitivity not in PRESETS:raise ValueError('Bright-grain sensitivity must be balanced, sensitive or strict.')
    return dict(bright_detection_mode='local_contrast_v1',bright_sensitivity=sensitivity,
                bright_boundary_fraction=float(fraction),bright_background_window_px=17,
                bright_min_pixels=2,bright_min_area_um2=0.,**PRESETS[sensitivity])


def validate(p):
    if p.get('bright_detection_mode','threshold') not in ['threshold','local_contrast_v1']:
        raise ValueError('Unknown bright-grain detection mode.')
    if p.get('bright_detection_mode')!='local_contrast_v1':return
    for key,lo,hi in [('bright_boundary_fraction',.15,.8),('bright_min_contrast',4,100),
                      ('bright_noise_sigma',1,10),('bright_peak_min_gray',0,254)]:
        v=float(p[key])
        if not np.isfinite(v) or not lo<=v<=hi:raise ValueError(f'{key} must be {lo}–{hi}。')
    w=float(p['bright_background_window_px'])
    if not w.is_integer() or not 7<=w<=101 or int(w)%2!=1:raise ValueError('The local background window must be an odd pixel count from 7 to 101.')


def description(cfg):
    p=cfg['segmentation']
    if p.get('bright_detection_mode')!='local_contrast_v1':return ''
    return (f'<h2>Bright-grain candidate detection</h2><p>Local background brightness and noise identify bright peaks. Native pixels connected to a peak are retained when their local contrast reaches '
            f'{100*p["bright_boundary_fraction"]:g}% of that peak. Adjacent peaks are separated. Minimum candidate: {p["bright_min_pixels"]} pixels; '
            f'automatic area threshold: {p["bright_min_area_um2"]:g} μm². Original pixels and scale are retained. Outlines are reviewable intensity boundaries. '
            'Intensity alone cannot establish mineral identity or a subpixel true grain size. Statistics use the saved outlines and exclusion rules for this revision.</p>')


def detect_bright(g,p,readable=None):
    validate(p);raw=np.asarray(g,dtype=np.float32)
    valid=np.ones(raw.shape,bool) if readable is None else np.asarray(readable,bool)
    # Slight smoothing suppresses single-pixel noise while retaining 2–3 pixel spots.
    smooth=ndi.gaussian_filter(raw,.55)
    background=ndi.median_filter(smooth,size=int(p['bright_background_window_px']))
    background=ndi.gaussian_filter(background,1.)
    contrast=smooth-background
    typical=valid&(raw>25)&(raw<235)
    matrix=float(np.median(raw[typical])) if typical.any() else 170.
    highpass=raw-ndi.gaussian_filter(raw,1.)
    noise_values=highpass[typical]
    noise=float(np.median(np.abs(noise_values-np.median(noise_values)))/.67448975) if len(noise_values) else 1.
    noise=max(.5,noise)
    seed_cut=max(float(p['bright_min_contrast']),float(p['bright_noise_sigma'])*noise)
    floor=max(float(p['bright_peak_min_gray']),matrix+float(p['bright_min_contrast'])/2)
    peaks=valid&(smooth==ndi.maximum_filter(smooth,size=5))&(contrast>=seed_cut)&(smooth>=floor)
    peak_labels,n=ndi.label(peaks,np.ones((3,3),bool));markers=np.zeros(raw.shape,np.int32);seeds=[]
    for peak_id,sl in enumerate(ndi.find_objects(peak_labels),1):
        if sl is None:continue
        component=peak_labels[sl]==peak_id;local=np.where(component,contrast[sl],-np.inf)
        y,x=np.unravel_index(np.argmax(local),local.shape);y+=sl[0].start;x+=sl[1].start
        seeds.append((y,x));markers[y,x]=len(seeds)
    low=max(2.,1.5*noise)
    support=valid&(contrast>=low)
    basins=watershed(-smooth,markers,mask=support,connectivity=np.ones((3,3))) if seeds else markers
    labels=np.zeros(raw.shape,np.int32);records=[];fraction=float(p['bright_boundary_fraction'])
    for old,sl in enumerate(ndi.find_objects(basins),1):
        if sl is None:continue
        y,x=seeds[old-1];cut=max(low,fraction*float(contrast[y,x]))
        region=(basins[sl]==old)&(contrast[sl]>=cut)
        pieces,_=ndi.label(region,np.ones((3,3),bool));part=pieces[y-sl[0].start,x-sl[1].start]
        if not part:continue
        region=pieces==part;area=int(region.sum())
        if area<int(p['bright_min_pixels']):continue
        index=len(records)+1;labels[sl][region]=index
        records.append(dict(label=index,peak_x_px=int(x),peak_y_px=int(y),area_px=area,
                            peak_gray=float(raw[y,x]),background_gray=float(background[y,x]),
                            peak_contrast=float(contrast[y,x]),boundary_contrast=cut,
                            boundary_fraction=fraction,less_than_9_pixels=area<9))
    info=dict(method='local_contrast_v1',candidate_count=len(records),noise_gray=noise,
              seed_contrast=seed_cut,peak_floor=floor,background_window_px=int(p['bright_background_window_px']),
              boundary_fraction=fraction,minimum_pixels=int(p['bright_min_pixels']),objects=records,
              boundary_definition='connected local contrast >= fraction of its peak; watershed separates adjacent peaks; native pixels only')
    return labels,info
