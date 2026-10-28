"""Candidate BSE segmentation, independent of particle-to-inclusion distances."""
import numpy as np
from scipy import ndimage as ndi
from skimage.measure import regionprops

def disk(radius):
    r = int(np.ceil(radius))
    y, x = np.mgrid[-r:r+1, -r:r+1]
    return x*x+y*y <= radius*radius

def label(mask):
    return ndi.label(mask, np.ones((3,3), dtype=bool))[0].astype(np.int32)

def make_masks(g, s, p, context_mask=None):
    # Background is recognized by border connectivity, separately from bright objects.
    outside = np.zeros(g.shape, bool)
    labels = label((g >= 245) | (g <= 20))
    edges = np.unique(np.r_[labels[0], labels[-1], labels[:,0], labels[:,-1]])
    for k in edges[edges != 0]:
        comp = labels == k
        if comp.sum() >= 100:
            outside |= comp
    sample = ~outside
    void = (g < p['void_threshold']) & sample
    # Large black regions plus a fixed physical halo are unreadable target context.
    unknown = ndi.binary_dilation(void, structure=disk(p['void_halo_um']/s))
    A = sample & ~unknown
    if context_mask is not None:
        if np.asarray(context_mask).shape!=g.shape:raise ValueError('Readable context mask dimensions differ from image')
        A=np.asarray(context_mask,dtype=bool).copy();sample=A.copy();outside=~A;unknown=~A;void=np.zeros_like(A)
    smooth = ndi.gaussian_filter(g.astype(float), p['smooth_sigma_px'])
    valid_bg = sample & (g > p.get('background_min_gray',130)) & (g < p.get('background_max_gray',230))
    sig = p['background_sigma_um']/s
    bg = ndi.gaussian_filter(np.where(valid_bg,g,0).astype(float), sig) / np.maximum(
        ndi.gaussian_filter(valid_bg.astype(float), sig), 1e-6)
    residual = bg-smooth
    gray = (residual >= p['gray_residual']) & (smooth >= p.get('gray_floor',130)) & (smooth < p.get('gray_ceiling',193)) & A
    gray = ndi.binary_opening(gray, structure=disk(1))
    glab = label(gray)
    records = []
    C = np.zeros_like(gray)
    for r in regionprops(glab, intensity_image=residual):
        ratio = r.axis_major_length/max(r.axis_minor_length, .1)
        keep = (r.area*s*s >= p['gray_min_area_um2'] and ratio <= p['gray_max_axis_ratio']
                and r.solidity >= p['gray_min_solidity'])
        records.append(dict(raw_label=int(r.label), keep=bool(keep), area_px=int(r.area),
                            axis_ratio=float(ratio), solidity=float(r.solidity),
                            mean_residual=float(r.intensity_mean)))
        if keep:
            sl = r.slice
            component = glab[sl] == r.label
            # Only fully enclosed holes supported by a closed dark contour are filled.
            C[sl] |= ndi.binary_fill_holes(component)
    C &= A
    bright_info=None
    if p.get('bright_detection_mode')=='local_contrast_v1':
        from bright_segmentation import detect_bright
        bright_labels,bright_info=detect_bright(g,p,A)
    else:
        bright_labels=label((g>=p['bright_threshold'])&sample)
    # Crack marker excludes broad gray blobs; no nanoparticle splitting is attempted.
    crack = (smooth < p['crack_intensity']) & sample
    crack = ndi.binary_dilation(crack, structure=disk(.15/s))
    return dict(A=A, sample=sample, outside=outside, unknown=unknown, void=void,
                C=C, inclusion_labels=label(C), bright_labels=bright_labels,
                crack=crack, residual=residual, gray_raw_labels=glab,
                gray_decisions=records,bright_diagnostics=bright_info)

def protected_window(A, observable, s, rmax):
    clearance = ndi.distance_transform_edt(np.pad(A,1), sampling=(s,s))[1:-1,1:-1]
    return (clearance >= rmax) & observable, clearance
