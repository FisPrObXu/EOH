"""Equal-area finite-region redistribution for an individually reviewed field.

Keep the field's observed count and total native area. Synthetic compact pixel
regions fit wholly in W outside C and never overlap. This changes the null model;
it does not reinterpret the former point-location p values.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
from PIL import Image
from scipy import ndimage as ndi

from apply_review21 import ROOT, replay
from analyze_review21 import evenly_spread, point_table


def dump(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def footprints(area):
    """Nearest native lattice cells, with all distinct rotations/reflections."""
    radius = math.ceil(math.sqrt(area)) + 1
    y, x = np.mgrid[-radius:radius+1, -radius:radius+1]
    offsets = np.column_stack([y.ravel(), x.ravel()])
    order = np.lexsort((offsets[:, 1], offsets[:, 0], (offsets**2).sum(axis=1)))
    original = offsets[order[:area]]
    result = []
    seen = set()
    for reflection in [1, -1]:
        a = original * [1, reflection]
        for k in range(4):
            b = a.copy()
            for _ in range(k):
                b = np.column_stack([-b[:, 1], b[:, 0]])
            b = b[np.lexsort((b[:, 1], b[:, 0]))]
            key = tuple(b.ravel())
            if key not in seen:
                seen.add(key)
                result.append(b)
    return result


def valid_anchors(domain, offsets):
    h, w = domain.shape
    pad = int(np.abs(offsets).max()) + 1
    padded = np.pad(domain, pad)
    valid = domain.copy()
    for dy, dx in offsets:
        valid &= padded[pad+dy:pad+dy+h, pad+dx:pad+dx+w]
    return valid


def catalogue(domain, areas):
    cats = {}
    w = domain.shape[1]
    for area in sorted(set(areas)):
        variants = []
        for offsets in footprints(int(area)):
            valid = valid_anchors(domain, offsets)
            anchors = np.flatnonzero(valid).astype(np.int32)
            if not len(anchors):
                raise ValueError(f'No admissible placement for area {area}')
            variants.append(dict(offsets=offsets, linear=offsets[:, 0]*w+offsets[:, 1],
                                 valid=valid, anchors=anchors))
        cats[int(area)] = dict(variants=variants, cumulative=np.cumsum([len(v['anchors']) for v in variants]))
    return cats


def bank(domain, areas, cats, B, seed):
    """Reject entire overlapping configurations, rather than placing objects sequentially."""
    rng = np.random.default_rng(seed)
    w = domain.shape[1]
    anchors = np.empty((B, len(areas)), np.int32)
    variants = np.empty_like(anchors, dtype=np.int8)
    pixels = np.empty((B, int(sum(areas))), np.int32)
    proposals = 0
    for trial in range(B):
        while True:
            proposals += 1
            pieces = []
            for j, area in enumerate(areas):
                cat = cats[int(area)]
                choice = int(rng.integers(cat['cumulative'][-1]))
                v = int(np.searchsorted(cat['cumulative'], choice, side='right'))
                within = choice - (int(cat['cumulative'][v-1]) if v else 0)
                anchor = int(cat['variants'][v]['anchors'][within])
                anchors[trial, j] = anchor
                variants[trial, j] = v
                pieces.append(anchor + cat['variants'][v]['linear'])
            flat = np.concatenate(pieces)
            if len(np.unique(flat)) == len(flat):
                pixels[trial] = flat
                break
            if proposals > B*100:
                raise ValueError('Whole-configuration rejection is inefficient for this density')
    assert domain.ravel()[pixels].all()
    return dict(anchors=anchors, variants=variants, pixels=pixels,
                proposals=proposals, seed=seed, width=w)


def layout(anchors, variants, areas, cats, shape, D, scale, prefix):
    labels = np.zeros(shape, np.int32)
    points = []
    for j, (anchor, v, area) in enumerate(zip(anchors, variants, areas)):
        y, x = divmod(int(anchor), shape[1])
        offsets = cats[int(area)]['variants'][int(v)]['offsets']
        yy, xx = (offsets + [y, x]).T
        if (labels[yy, xx] > 0).any():
            raise AssertionError('Synthetic objects overlap')
        labels[yy, xx] = j+1
        points.append([yy.mean(), xx.mean()])
    frame = point_table(np.asarray(points), D, scale, prefix)
    frame['area_px'] = areas
    frame['area_um2'] = np.asarray(areas)*scale**2
    frame['anchor_y_px'] = np.asarray(anchors)//shape[1]
    frame['anchor_x_px'] = np.asarray(anchors)%shape[1]
    frame['footprint_variant'] = variants
    return labels, frame


def batched_bank(domain, areas, cats, B, seed):
    """Independent proposals in batches; reject each entire overlapping configuration."""
    rng=np.random.default_rng(seed)
    anchors=np.empty((B,len(areas)),np.int32);variants=np.empty_like(anchors,dtype=np.int8)
    pixels=np.empty((B,int(sum(areas))),np.int32)
    accepted=proposals=0
    while accepted<B:
        batch=128;aa=np.empty((batch,len(areas)),np.int32);vv=np.empty_like(aa,dtype=np.int8)
        pp=np.empty((batch,int(sum(areas))),np.int32);offset=0
        for j,area in enumerate(areas):
            cat=cats[int(area)];choice=rng.integers(cat['cumulative'][-1],size=batch)
            v=np.searchsorted(cat['cumulative'],choice,side='right');vv[:,j]=v
            for k,variant in enumerate(cat['variants']):
                rows=v==k;within=choice[rows]-(cat['cumulative'][k-1] if k else 0)
                aa[rows,j]=variant['anchors'][within]
                pp[rows,offset:offset+area]=aa[rows,j,None]+variant['linear']
            offset+=area
        good=np.flatnonzero((np.diff(np.sort(pp,axis=1),axis=1)>0).all(axis=1))[:B-accepted]
        n=len(good);anchors[accepted:accepted+n]=aa[good];variants[accepted:accepted+n]=vv[good]
        pixels[accepted:accepted+n]=pp[good];accepted+=n;proposals+=batch
        if proposals>B*200:raise ValueError('Low acceptance in whole-configuration rejection')
    assert domain.ravel()[pixels].all()
    return dict(anchors=anchors,variants=variants,pixels=pixels,proposals=proposals,seed=seed,width=domain.shape[1])


def run(out, review, image_id='21'):
    image_id=str(image_id)
    for folder in ['inputs', 'reviewed/masks', 'reviewed/tables', 'reviewed/logs', 'tables', 'masks', 'logs', 'figures', 'report', 'code']:
        (out/folder).mkdir(parents=True, exist_ok=True)
    d = replay(review, out/'reviewed',image_id)
    C, W, A, D, scale = (d[k] for k in ['C', 'W', 'A', 'D', 's'])
    domain = W & ~C
    selected = d['table'].loc[(d['table'].kind == 'bright') & d['table'].included].copy()
    N = len(selected)
    total = int(selected.area_px.sum())
    maximum = int(selected.area_px.max())
    cap = math.floor(.75*maximum)
    if image_id=='21' and N != 15:
        raise ValueError('The approved count was 15; updated object count needs an explicit new configuration')
    if N<1:raise ValueError('No included bright objects')
    areas = np.full(N, total//N, int)
    areas[:total % N] += 1
    assert areas.max() <= cap
    config = dict(image_id=image_id,pixel_size_um=scale,review_revision=d['info']['revision'], N=N, total_area_px=total, total_area_um2=total*scale**2,
                  largest_observed_area_px=maximum, per_region_cap_fraction=.75, per_region_cap_px=cap,
                  equalized_areas_px=areas.tolist(), count_rule='Preserve the included observed count for this field',
                  area_source='Whole native masks of the same objects selected by centroid in W',
                  domain_rule='Every synthetic pixel in W outside C; no synthetic regions overlap',
                  sampling='Uniform valid anchor/orientation pairs independently proposed, then whole configuration rejected if overlapping',
                  shapes='Compact nearest-lattice-cell footprints with distinct rotations/reflections; exact native pixel areas',
                  distance='Native rounded centroid to nearest C; identical to prior distance definition',
                  B=4999, calibration_B=4999, seed=2026102600+int(image_id), calibration_seed=2026102601+int(image_id),
                  grid_um=np.arange(.25, 5.001, .25).tolist(), exploratory=True,
                  baseline='Mean CDF of an independent 4999-layout calibration bank; not an exact pixel baseline',
                  caveat='Equalized sizes and whole-region exclusion change the null; observed boundary compatibility is audited separately',
                  original_fixed_point_analysis_retained=True)
    dump(out/'config.json', config)
    print(json.dumps(config, ensure_ascii=False, indent=2), flush=True)
    cats = catalogue(domain, areas)
    sampler=bank if image_id=='21' else batched_bank
    calibration = sampler(domain, areas, cats, config['calibration_B'], config['calibration_seed'])
    random = sampler(domain, areas, cats, config['B'], config['seed'])
    observed = point_table(selected[['centroid_y_px', 'centroid_x_px']].to_numpy(), D, scale, 'O')
    observed.insert(1, 'source_object_id', selected.object_id.to_list())
    observed['area_px'] = selected.area_px.to_numpy()
    observed['area_um2'] = selected.area_um2.to_numpy()
    source_labels = np.array(Image.open(out/'reviewed'/'masks'/f'{image_id}_bright_labels.tif'))
    gray_labels = np.array(Image.open(out/'reviewed'/'masks'/f'{image_id}_inclusion_labels.tif'))
    mapping = pd.read_csv(out/'reviewed'/'tables'/'reviewed_label_mapping.csv').set_index('object_id')
    observed_labels = np.zeros(C.shape, np.int32)
    diagnostics = []
    for j, (_, row) in enumerate(selected.iterrows()):
        mask = source_labels == int(mapping.loc[row.object_id, 'reviewed_native_label'])
        observed_labels[mask] = j+1
        qy, qx = int(row.grid_y_px), int(row.grid_x_px)
        fit = {f'fits_{area}px_footprint': any(v['valid'][qy, qx] for v in cat['variants'])
               for area, cat in cats.items()}
        diagnostics.append(dict(object_id=row.object_id, area_px=int(mask.sum()),
                                overlapping_dark_pixels=int((mask & C).sum()),
                                overlapping_dark_object_ids=' / '.join(mapping.index[(mapping.kind == 'gray') & mapping.reviewed_native_label.isin(np.unique(gray_labels[mask & C]))]),
                                outside_W_pixels=int((mask & ~W).sum()), **fit))
    pd.DataFrame(diagnostics).to_csv(out/'tables'/'observed_boundary_audit.csv', index=False, encoding='utf-8-sig')
    observed.to_csv(out/'tables'/'01_observed_distances.csv', index=False, encoding='utf-8-sig')
    common = np.logical_and.reduce([v['valid'] for cat in cats.values() for v in cat['variants']])
    uniform, method = evenly_spread(common, N)
    uniform_anchors = uniform[:, 0].astype(int)*C.shape[1] + uniform[:, 1].astype(int)
    uniform_variants = np.zeros(N, int)
    even_labels, even = layout(uniform_anchors, uniform_variants, areas, cats, C.shape, D, scale, 'U')
    even.to_csv(out/'tables'/'02_evenly_spread_distances.csv', index=False, encoding='utf-8-sig')
    masks = dict(observed=observed_labels, even=even_labels)
    for trial in range(5):
        labels, frame = layout(random['anchors'][trial], random['variants'][trial], areas, cats, C.shape, D, scale, 'R')
        masks[f'random_{trial+1:04d}'] = labels
        frame.to_csv(out/'tables'/f'random_layout_{trial+1:04d}.csv', index=False, encoding='utf-8-sig')
        if trial == 0:
            example = frame
            frame.to_csv(out/'tables'/'03_random_example_distances.csv', index=False, encoding='utf-8-sig')
    for name, labels in masks.items():
        Image.fromarray(labels).save(out/'masks'/f'{name}_labels.tif', compression='tiff_deflate')
    for name, mask in [('domain', domain), ('common_anchor_domain', common), ('C', C), ('W', W), ('A', A)]:
        Image.fromarray(mask.astype(np.uint8)*255).save(out/'masks'/f'{name}.png')
    # Centroid rounding maps these nearly symmetric footprints back to their anchors.
    assert all(np.abs(v['offsets'].mean(axis=0)).max() < .5 for cat in cats.values() for v in cat['variants'])
    grid = np.asarray(config['grid_um'])
    cal_distances = D.ravel()[calibration['anchors']]
    sim_distances = D.ravel()[random['anchors']]
    obs = observed.distance_to_in_image_gray_um.to_numpy()
    cal_counts = (cal_distances[:, :, None] <= grid).sum(axis=1)
    sim_counts = (sim_distances[:, :, None] <= grid).sum(axis=1)
    obs_counts = (obs[:, None] <= grid).sum(axis=0)
    base_total = cal_counts.sum(axis=0, dtype=np.int64)
    cal_B = config['calibration_B']
    obs_num = max(0, int((obs_counts*cal_B-base_total).max()))
    sim_num = np.maximum(0, (sim_counts*cal_B-base_total).max(axis=1))
    obs_mean = float(np.minimum(5, obs).mean())
    sim_means = np.minimum(5, sim_distances).mean(axis=1)
    sim_near = (sim_distances <= 1).sum(axis=1)
    observed_near = int((obs <= 1).sum())
    base_near = float((cal_distances <= 1).sum(axis=1).mean())
    diag = pd.DataFrame(diagnostics)
    incompatible = diag.loc[~diag.filter(like='fits_').any(axis=1), 'object_id'].to_list()
    summary = dict(**config, observed_mean_um=obs_mean, random_mean_um=float(np.minimum(5, cal_distances).mean()),
                   uniform_mean_um=float(even.distance_5um_capped_um.mean()),
                   random_example_mean_um=float(example.distance_5um_capped_um.mean()),
                   observed_near_1um=observed_near, random_expected_near_1um=base_near,
                   near_1um_ratio=float(observed_near/base_near),
                   positive_CDF_max=obs_num/(N*cal_B), positive_CDF_peak_um=float(grid[np.argmax(obs_counts*cal_B-base_total)]),
                   curve_p_MC=float((1+(sim_num >= obs_num).sum())/(config['B']+1)),
                   near_p_MC=float((1+(sim_near >= observed_near).sum())/(config['B']+1)),
                   mean_p_MC=float((1+(sim_means <= obs_mean).sum())/(config['B']+1)),
                   overlapping_observed_dark_pixels=int(diag.overlapping_dark_pixels.sum()),
                   observed_centers_incompatible_with_equalized_footprints=incompatible,
                   formal_interpretation_pending_boundary_review=bool(incompatible or diag.overlapping_dark_pixels.any()),
                   calibration_proposals=calibration['proposals'], test_proposals=random['proposals'])
    curves = pd.DataFrame(dict(r_um=grid, observed=obs_counts/N, random_reference=base_total/(N*cal_B),
                               evenly_spread=[(even.distance_to_in_image_gray_um <= r).mean() for r in grid],
                               random_example=[(example.distance_to_in_image_gray_um <= r).mean() for r in grid]))
    curves.to_csv(out/'tables'/'distance_curves.csv', index=False, encoding='utf-8-sig')
    groups = {'observed': observed, 'evenly_spread': even, 'random_example': example}
    pd.DataFrame([dict(group=k, N=len(f), area_px=int(f.area_px.sum()), mean_um=float(f.distance_5um_capped_um.mean()),
                            within_1um=int((f.distance_to_in_image_gray_um <= 1).sum())) for k, f in groups.items()]).to_csv(
        out/'tables'/'three_group_summary.csv', index=False, encoding='utf-8-sig')
    np.savez_compressed(out/'tables'/'simulations.npz', anchors=random['anchors'], variants=random['variants'],
                        calibration_anchors=calibration['anchors'], calibration_variants=calibration['variants'],
                        sim_distances=sim_distances, sim_positive_numerator=sim_num,
                        sim_mean_capped_5um=sim_means, sim_near_1um=sim_near, areas=areas,
                        baseline_total_counts=base_total)
    # Check every native synthetic pixel in both independent banks, not just the illustrated layouts.
    checks = dict(total_area_preserved=bool(all(int((m > 0).sum()) == total for m in masks.values())),
                  all_footprints_below_cap=bool(areas.max() <= cap), near_equal_areas=bool(np.ptp(areas) <= 1),
                  all_9998_layouts_inside_domain=bool(domain.ravel()[random['pixels']].all() and domain.ravel()[calibration['pixels']].all()),
                  all_layouts_nonoverlapping=bool(np.all(np.diff(np.sort(random['pixels'], axis=1), axis=1) > 0) and np.all(np.diff(np.sort(calibration['pixels'], axis=1), axis=1) > 0)),
                  uniform_inside_domain=bool(domain[even_labels > 0].all()),
                  actual_mask_unchanged=bool(np.array_equal(observed_labels > 0, np.isin(source_labels, [int(mapping.loc[o, 'reviewed_native_label']) for o in selected.object_id]))),
                  no_zero_distance_grid=bool((grid > 0).all()), all_observed_centroids_positive=bool((obs > 0).all()),
                  native_random_example_distances=bool(np.allclose(example.distance_to_in_image_gray_um, sim_distances[0], atol=1e-12, rtol=0)),
                  separate_calibration_and_test_seeds=config['seed'] != config['calibration_seed'])
    assert all(checks.values()), checks
    dump(out/'logs'/'numerical_validation.json', checks)
    dump(out/'logs'/'summary.json', summary)
    dump(out/'logs'/'uniform_method.json', method)
    dump(out/'logs'/'footprints.json', {str(a): [v['offsets'].tolist() for v in c['variants']] for a, c in cats.items()})
    shutil.copyfile(review, out/'inputs'/'review_annotations.json')
    shutil.copyfile(ROOT/'report'/f'{image_id}_native_grayscale.png', out/'inputs'/f'{image_id}_native_grayscale.png')
    dump(out/'logs'/'source_binding.json', dict(review_sha256=hashlib.sha256(Path(review).read_bytes()).hexdigest(),
                                              dataset_id=d['info']['dataset_id'], pixel_size_um=scale))
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return d, summary


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, default=ROOT/'_tmp'/'area_redistribution21_stage')
    p.add_argument('--review', type=Path, default=ROOT/'report'/'review_annotations'/'review_annotations.json')
    p.add_argument('--field',choices=['21','24'],default='21')
    args = p.parse_args()
    run(args.output, args.review,args.field)
