"""Native-pixel measurements and fixed-N uniform-position Monte Carlo test."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from skimage.measure import regionprops
from segmentation import make_masks, protected_window, label, disk

def save_json(path, obj):
    Path(path).write_text(json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')

def read_image(root, cfg, image_id):
    im=Image.open((root/cfg['input_directory']/f'ccpsph1-{image_id}.tif').resolve()).convert('L')
    return np.asarray(im.crop(cfg['images'][image_id]['crop_xyxy']))

def rounded(yx, shape):
    return np.clip(np.floor(yx+.5).astype(int),[0,0],np.array(shape)-1)

def build_particle_table(image_id, masks, g, s, p, W, D, cfg):
    crack_distance=ndi.distance_transform_edt(~masks['crack'],sampling=s)
    rows=[]
    for r in regionprops(masks['bright_labels'],intensity_image=g):
        y,x=r.centroid; iy,ix=rounded(np.array([y,x]),g.shape)
        enough=r.area >= p['bright_min_pixels'] and r.area*s*s >= p['bright_min_area_um2']
        in_a=bool(masks['A'][iy,ix]); in_w=bool(W[iy,ix])
        accepted=bool(enough and in_w)
        why=('below_minimum_size' if not enough else 'unreadable_context' if not in_a else
             'outside_protected_W' if not in_w else '')
        distance=float(D[iy,ix])
        inside=bool(masks['C'][iy,ix])
        near=distance <= .25 and not inside
        rows.append(dict(image_id=image_id,object_id=f'B{r.label:04d}',native_label=int(r.label),
            object_class='candidate_bright_particle',centroid_x_px=float(x),centroid_y_px=float(y),
            original_x_px=float(x+cfg['images'][image_id]['crop_xyxy'][0]),
            original_y_px=float(y+cfg['images'][image_id]['crop_xyxy'][1]),
            x_um=float((x+.5)*s),y_um=float((y+.5)*s),grid_x_px=int(ix),grid_y_px=int(iy),
            area_px=int(r.area),area_um2=float(r.area*s*s),
            area_status='measurable_candidate' if r.area>=p['area_measurable_pixels'] else 'pixel_limited_candidate' if p.get('bright_detection_mode')=='local_contrast_v1' else 'unresolved_core_area_only',
            max_intensity=int(r.intensity_max),bbox_y0=r.bbox[0],bbox_x0=r.bbox[1],
            bbox_y1=r.bbox[2],bbox_x1=r.bbox[3],
            review_status='pending_user_review',agent_qa='automated_criteria_then_visual_overlay',
            quality_candidate=bool(enough),in_A=in_a,in_W=in_w,included_main=accepted,
            boundary_flag=bool(not in_w),crack_distance_um=float(crack_distance[iy,ix]),
            crack_near_1um=bool(crack_distance[iy,ix]<=1),distance_um=distance,
            internal_projection=inside,position_class='inside_projection' if inside else 'near_edge_0.25um' if near else 'outside',
            exclusion_reason=why,parameter_version=cfg['parameter_version']))
    return pd.DataFrame(rows)

def inclusion_table(image_id,masks,s,cfg):
    rows=[]
    for group,lab in [('candidate_gray_inclusion',masks['inclusion_labels']),('gray_component_rejected',masks['gray_raw_labels'])]:
        rejects={x['raw_label']:x for x in masks.get('gray_decisions',[]) if not x['keep']}
        for r in regionprops(lab,intensity_image=masks.get('residual',np.zeros(lab.shape))):
            if group.endswith('rejected') and r.label not in rejects: continue
            y,x=r.centroid
            sl=r.slice; region=lab[sl]==r.label
            filled=int((region&(masks['gray_raw_labels'][sl]==0)).sum()) if group.startswith('candidate') else 0
            bright_ids=np.unique(masks['bright_labels'][sl][region]); bright_ids=bright_ids[bright_ids>0]
            rows.append(dict(image_id=image_id,object_id=('C' if group.startswith('candidate') else 'X')+f'{r.label:04d}',
                native_label=int(r.label),object_class=group,centroid_x_px=x,centroid_y_px=y,
                original_x_px=x+cfg['images'][image_id]['crop_xyxy'][0],original_y_px=y+cfg['images'][image_id]['crop_xyxy'][1],
                x_um=(x+.5)*s,y_um=(y+.5)*s,area_px=int(r.area),area_um2=r.area*s*s,
                mean_dark_residual=float(r.intensity_mean),axis_ratio=r.axis_major_length/max(r.axis_minor_length,.1),
                solidity=r.solidity,bbox_y0=r.bbox[0],bbox_x0=r.bbox[1],bbox_y1=r.bbox[2],bbox_x1=r.bbox[3],
                review_status='pending_user_review',boundary_flag=r.bbox[0]==0 or r.bbox[1]==0 or r.bbox[2]==lab.shape[0] or r.bbox[3]==lab.shape[1],
                exclusion_reason='area_or_elongation_or_solidity' if group.endswith('rejected') else '',
                occlusion_rule='fully_enclosed_holes_only; no filling at open bright margins',
                enclosed_hole_pixels=filled,
                overlapping_bright_labels=';'.join(str(k) for k in bright_ids),
                occlusion_review='pending_closed_contour_check' if filled else 'no_enclosed_fill',
                parameter_version=cfg['parameter_version']))
    return pd.DataFrame(rows)

def test(C,W,points,s,cfg,seed):
    if not C.any() or not W.any() or len(points)==0:
        raise ValueError('No target, W or particles: no valid test')
    D=ndi.distance_transform_edt(~C,sampling=(s,s))
    grid=np.arange(round(cfg['statistics']['rmax_um']/cfg['statistics']['grid_step_um'])+1)*cfg['statistics']['grid_step_um']
    valid=np.flatnonzero(W)
    base=D.ravel()[valid]
    yx=rounded(np.asarray(points),W.shape)
    assert W[yx[:,0],yx[:,1]].all()
    obs=D[yx[:,0],yx[:,1]]
    N=len(obs); M=len(base)
    obs_counts=np.array([(obs<=r).sum() for r in grid],dtype=np.int64)
    base_counts=np.array([(base<=r).sum() for r in grid],dtype=np.int64)
    # Integer numerators make tie handling exact: |k*M - m*N| / (N*M).
    obs_num=int(np.max(np.abs(obs_counts*M-base_counts*N)))
    B=cfg['statistics']['B']; rng=np.random.default_rng(seed)
    sim_num=np.empty(B,dtype=np.int64)
    exemplar=None
    for start in range(0,B,256):
        sampled=rng.integers(M,size=(min(256,B-start),N))
        indices=valid[sampled]
        assert indices.shape[1]==N and W.ravel()[indices].all()
        ds=D.ravel()[indices]
        counts=(ds[:,:,None]<=grid).sum(axis=1,dtype=np.int64)
        sim_num[start:start+len(ds)]=np.max(np.abs(counts*M-base_counts*N),axis=1)
        if exemplar is None: exemplar=np.column_stack(np.unravel_index(indices[0],W.shape))
    kth=cfg['statistics']['critical_order_one_based']-1
    critical_num=int(np.partition(sim_num,kth)[kth])
    c=critical_num/(N*M); p=(1+int((sim_num>=obs_num).sum()))/(B+1)
    reject=obs_num>critical_num
    assert reject == (p<=cfg['statistics']['alpha'])
    F0=base_counts/M; Fobs=obs_counts/N
    curves=pd.DataFrame(dict(r_um=grid,observed_count=obs_counts,baseline_pixel_count=base_counts,
        Fobs=Fobs,F0=F0,lower=np.maximum(0,F0-c),upper=np.minimum(1,F0+c),
        delta=Fobs-F0,enrichment_ratio=np.divide(Fobs,F0,out=np.full_like(Fobs,np.nan),where=F0>=.01)))
    summary=dict(N=N,M=M,W_area_um2=M*s*s,C_objects=int(label(C).max()),
        C_area_um2=int(C.sum())*s*s,C_fraction_in_W=float(C[W].mean()),seed=int(seed),B=B,
        T_observed=obs_num/(N*M),critical=c,p=p,reject=bool(reject),
        T_observed_numerator=obs_num,critical_numerator=critical_num,denominator=N*M,
        above_rmax=int((obs>grid[-1]).sum()),internal_projection=int((obs==0).sum()),
        positive_peak=float((Fobs-F0).max()),negative_peak=float((Fobs-F0).min()),
        max_deviation_r_um=float(grid[np.argmax(np.abs(Fobs-F0))]),
        dominant_direction='closer' if (Fobs-F0)[np.argmax(np.abs(Fobs-F0))]>0 else 'farther',
        area_measurable_is_not_particle_resolution=True)
    return summary,curves,dict(distance_map=D,sim_T=sim_num/(N*M),sim_T_numerator=sim_num,
                               example_random_yx=exemplar,observed_distances=obs)

def save_masks(out,i,m):
    for key in ['A','sample','outside','unknown','void','C','observable','W','crack','protection_band']:
        Image.fromarray(m[key].astype(np.uint8)*255).save(out/'masks'/f'{i}_{key}.png')
    for key in ['inclusion_labels','bright_labels','gray_raw_labels']:
        Image.fromarray(m[key].astype(np.int32)).save(out/'masks'/f'{i}_{key}.tif',compression='tiff_deflate')
    np.savez_compressed(out/'masks'/f'{i}_auxiliary.npz',residual=m['residual'])
    save_json(out/'masks'/f'{i}_gray_decisions.json',m.get('gray_decisions',[]))

def load_masks(root,i):
    keys=['A','sample','outside','unknown','void','C','observable','W','crack','protection_band']
    m={key:np.array(Image.open(root/'masks'/f'{i}_{key}.png'))>0 for key in keys}
    m.update({key:np.array(Image.open(root/'masks'/f'{i}_{key}.tif')) for key in ['inclusion_labels','bright_labels','gray_raw_labels']})
    # Native label raster is authoritative when an inclusion contour is edited.
    m['C']=m['inclusion_labels']>0
    m['residual']=np.load(root/'masks'/f'{i}_auxiliary.npz')['residual']
    m['gray_decisions']=json.loads((root/'masks'/f'{i}_gray_decisions.json').read_text(encoding='utf-8-sig'))
    return m

def analyze(root,out,cfg,reuse=False):
    p=cfg['segmentation']; rmax=cfg['statistics']['rmax_um']
    summaries=[]; sensitive=[]; effect_rows=[]; objects=[]; data={}
    for i in ['21','24']:
        print('Analyzing',i,flush=True)
        s=cfg['images'][i]['pixel_size_um']; g=read_image(root,cfg,i)
        m=load_masks(root,i) if reuse else make_masks(g,s,p)
        m['observable']=m['A'].copy() if not reuse else m['observable']
        W,clearance=protected_window(m['A'],m['observable'],s,rmax)
        if reuse: W &= m['W']  # Keep manually restricted windows; enforce safety clearance.
        m['W']=W; m['protection_band']=m['A']&~W
        D=ndi.distance_transform_edt(~m['C'],sampling=s)
        bright=build_particle_table(i,m,g,s,p,W,D,cfg)
        gray=inclusion_table(i,m,s,cfg)
        bright.to_csv(out/'tables'/f'{i}_particles.csv',index=False)
        gray.to_csv(out/'tables'/f'{i}_inclusions_and_rejected.csv',index=False)
        objects.extend([bright,gray]); save_masks(out,i,m)
        Image.fromarray(g).save(out/'report'/f'{i}_native_grayscale.png')
        pts=bright.loc[bright.included_main,['centroid_y_px','centroid_x_px']].to_numpy()
        seed=cfg['statistics']['seed_base']+int(i)
        summary,curves,arrays=test(m['C'],W,pts,s,cfg,seed)
        summary.update(image_id=i,candidate_bright_quality=int(bright.quality_candidate.sum()),
            bright_components_total=len(bright),A_area_um2=int(m['A'].sum())*s*s,
            sample_area_um2=int(m['sample'].sum())*s*s,unknown_area_um2=int(m['unknown'].sum())*s*s,
            protection_excluded_area_um2=int(m['protection_band'].sum())*s*s,
            near_edge_count=int(((bright.distance_um>0)&(bright.distance_um<=.25)&bright.included_main).sum()),
            phase_identity_validated=False,segmentation_reviewed=False,independence='unknown')
        # Descriptive NN diagnostic only, no second hypothesis test.
        nn=cKDTree(pts*s).query(pts*s,k=2)[0][:,1].mean()
        rng=np.random.default_rng(seed+500); valid=np.column_stack(np.where(W)); random_nn=[]
        for _ in range(199):
            xy=valid[rng.integers(len(valid),size=len(pts))]*s
            random_nn.append(float(cKDTree(xy).query(xy,k=2)[0][:,1].mean()))
        summary.update(mean_particle_NN_um=float(nn),iid_mean_NN_um=float(np.mean(random_nn)),
                       NN_ratio=float(nn/np.mean(random_nn)))
        np.savez_compressed(out/'tables'/f'{i}_monte_carlo.npz',**arrays,particle_NN_random_means=random_nn,
                            grid_um=curves.r_um.to_numpy(),N=len(pts),M=int(W.sum()),seed=seed)
        curves.to_csv(out/'tables'/f'{i}_distance_curves.csv',index=False)
        summaries.append(summary)
        for radius in cfg['statistics']['effect_distances_um']:
            row=curves.loc[np.isclose(curves.r_um,radius)].iloc[0].to_dict()
            effect_rows.append(dict(image_id=i,**row))
        variants=[]
        for sign in [-1,1]:
            C=ndi.binary_erosion(m['C'],structure=disk(1)) if sign<0 else ndi.binary_dilation(m['C'],structure=disk(1))&m['A']
            variants.append((f'gray_boundary_{sign:+d}px',C,W,pts))
        pp=p|{'gray_residual':cfg['sensitivity']['gray_residual_strict']}
        strict=make_masks(g,s,pp)
        variants.append(('gray_residual_12',strict['C'],W,pts))
        for threshold in cfg['sensitivity']['bright_thresholds']:
            mm=m.copy(); mm['bright_labels']=label((g>=threshold)&m['sample'])
            bb=build_particle_table(i,mm,g,s,p,W,D,cfg)
            variants.append((f'bright_threshold_{threshold}',m['C'],W,bb.loc[bb.included_main,['centroid_y_px','centroid_x_px']].to_numpy()))
        bb=bright.loc[bright.included_main&(bright.area_um2>=cfg['sensitivity']['bright_min_area_strict_um2'])]
        variants.append(('bright_min_area_0.05um2',m['C'],W,bb[['centroid_y_px','centroid_x_px']].to_numpy()))
        Wsafe= W & (clearance>=rmax+cfg['sensitivity']['extra_unknown_halo_um'])
        iyx=rounded(pts,W.shape); use=Wsafe[iyx[:,0],iyx[:,1]]
        variants.append(('extra_context_guard_1um',m['C'],Wsafe,pts[use]))
        baseline_curve=curves.assign(image_id=i,condition='main')
        sensitivity_curves=[baseline_curve]
        sensitive.append(dict(condition='main',**summary))
        for k,(name,C,ww,xx) in enumerate(variants):
            ss,cc,aa=test(C,ww,xx,s,cfg,seed+1000+k)
            sensitive.append(dict(image_id=i,condition=name,**ss))
            sensitivity_curves.append(cc.assign(image_id=i,condition=name))
            np.savez_compressed(out/'tables'/f'{i}_{name}_sensitivity.npz',
                C=C,W=ww,points_yx=xx,**aa)
        pd.concat(sensitivity_curves,ignore_index=True).to_csv(out/'tables'/f'{i}_sensitivity_curves.csv',index=False)
        data[i]=dict(g=g,m=m,s=s,bright=bright,gray=gray,summary=summary,curves=curves,
                     sensitivity=pd.concat(sensitivity_curves),arrays=arrays,points=pts)
        print(json.dumps(summary,ensure_ascii=False),flush=True)
    pd.concat(objects,ignore_index=True).to_csv(out/'tables'/'all_objects.csv',index=False)
    pd.DataFrame(summaries).to_csv(out/'tables'/'field_summary.csv',index=False)
    save_json(out/'tables'/'field_summary.json',summaries)
    pd.DataFrame(sensitive).to_csv(out/'tables'/'sensitivity_summary.csv',index=False)
    pd.DataFrame(effect_rows).to_csv(out/'tables'/'prespecified_effects.csv',index=False)
    # 10 is explicitly diagnostic, with no CDF/p-value.
    i='10'; s=cfg['images'][i]['pixel_size_um']; g=read_image(root,cfg,i)
    m=make_masks(g,s,p); m['observable']=m['A'].copy()
    m['W'],_=protected_window(m['A'],m['A'],s,rmax); m['protection_band']=m['A']&~m['W']
    save_masks(out,i,m)
    return data

def validation(data,cfg):
    checks={}
    C=np.zeros((7,9),bool); C[3,4]=True
    D=ndi.distance_transform_edt(~C,sampling=(2.,3.))
    checks['edt_direction_anisotropic_units']=bool(D[3,4]==0 and D[2,4]==2 and D[3,3]==3 and np.isclose(D[2,3],np.sqrt(13)))
    checks['right_tail_retained_in_denominator']=bool(np.mean(np.array([0.,1.,7.])<=5)==2/3)
    checks['centroid_rounding_half_up']=bool(np.array_equal(rounded(np.array([[1.5,2.49]]),(8,8)),[[2,2]]))
    for i,d in data.items():
        cc=d['curves']; summary=d['summary']; W=d['m']['W']; D=d['arrays']['distance_map']
        checks[i+'_F0_all_pixels']=bool(np.array_equal(cc.baseline_pixel_count,[(D[W]<=r).sum() for r in cc.r_um]))
        checks[i+'_N_matches_object_table']=int(d['bright'].included_main.sum())==summary['N']
        checks[i+'_CDF_right_tail']=bool(np.isclose(cc.Fobs.iloc[-1],1-summary['above_rmax']/summary['N']))
        checks[i+'_critical_exact_order']=int(np.sort(d['arrays']['sim_T_numerator'])[4749])==summary['critical_numerator']
        checks[i+'_p_envelope_agree']=summary['reject']==(summary['p']<=.05)
        checks[i+'_all_4999_simulations']=len(d['arrays']['sim_T'])==4999
        checks[i+'_observable_and_context_consistent']=bool((W&~d['m']['A']).sum()==0)
        checks[i+'_targets_not_clipped_to_W']=bool((d['m']['C']&~W).any())
    checks['no_overlapping_fields_pooled']=list(data)==['21','24']
    if not all(checks.values()): raise AssertionError(checks)
    return checks
