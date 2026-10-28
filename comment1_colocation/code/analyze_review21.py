"""Field 21: reviewed observations, evenly spread points, one random example, null test."""
import argparse
import json
import shutil
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from apply_review21 import replay, ROOT
from analysis import test

def evenly_spread(W,N):
    from acceleration import try_evenly_spread
    accelerated=try_evenly_spread(W,N)
    return accelerated if accelerated is not None else _evenly_spread_cpu(W,N)


def _evenly_spread_cpu(W,N):
    """Deterministic coverage of W; no gray mask or distance enters placement."""
    pixels=np.column_stack(np.where(W)).astype(float)
    mean=pixels.mean(axis=0)
    first=int(np.argmin(((pixels-mean)**2).sum(axis=1)))
    chosen=[pixels[first]]
    nearest=((pixels-chosen[0])**2).sum(axis=1)
    for _ in range(1,N):
        chosen.append(pixels[int(np.argmax(nearest))])
        nearest=np.minimum(nearest,((pixels-chosen[-1])**2).sum(axis=1))
    centers=np.array(chosen); tree=cKDTree(pixels)
    iterations=0
    for k in range(80):
        group=cKDTree(centers).query(pixels)[1]
        new=centers.copy()
        for j in range(N):
            if (group==j).any(): new[j]=pixels[group==j].mean(axis=0)
        # Hole-crossing centroids are projected to a distinct valid pixel of W.
        _,near=tree.query(new,k=min(N,len(pixels)))
        near=np.asarray(near).reshape(N,-1)
        used=set(); projected=[]
        for options in near:
            index=next(int(x) for x in options if int(x) not in used)
            used.add(index); projected.append(pixels[index])
        projected=np.array(projected); iterations=k+1
        if np.array_equal(projected,centers): break
        centers=projected
    return centers,dict(iterations=iterations,method='Deterministic centroidal coverage (farthest-point start, Voronoi centroid relaxation, projection into W)',
        target_regions_used_for_placement=False,interpretation='Illustrative evenly spread arrangement; not a sample from the independent uniform null')

def point_table(points,D,s,prefix):
    rounded=np.floor(points+.5).astype(int)
    distances=D[rounded[:,0],rounded[:,1]]
    return pd.DataFrame(dict(position_id=[f'{prefix}{k+1:02d}' for k in range(len(points))],
        centroid_x_px=points[:,1],centroid_y_px=points[:,0],grid_x_px=rounded[:,1],grid_y_px=rounded[:,0],
        x_um=(points[:,1]+.5)*s,y_um=(points[:,0]+.5)*s,
        distance_to_in_image_gray_um=distances,distance_5um_capped_um=np.minimum(5,distances),
        distance_gt_5um=distances>5))

def run(review_path,out):
    for name in ['masks','tables','figures','report','logs']: (out/name).mkdir(parents=True,exist_ok=True)
    cfg=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
    cfg['field']='21'; cfg['review_source']=str(Path(review_path).resolve())
    cfg['uniform_group']='N centroids spread over original W by deterministic centroidal coverage, ignoring C'
    cfg['random_example']='First simulated arrangement of the fixed-seed 4999-trial null test, not selected by appearance'
    cfg['manual_review_scope']='Field 21 only; original 21/24 baseline products remain archived and identifiable'
    cfg['segmentation_reviewed']=True
    cfg['reviewed_fields']=['21']
    cfg['reviewed_sensitivity']=['gray erode 1 native pixel','gray dilate 1 native pixel',
        'minimum bright outline area 0.05 um2','additional 1 um context guard']
    cfg['statistics']['seed_base']=2026102500
    (out/'config.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
    d=replay(review_path,out)
    b=d['table'].loc[(d['table'].kind=='bright')&d['table'].included].copy()
    pts=b[['centroid_y_px','centroid_x_px']].to_numpy()
    N=len(pts)
    summary,curves,arrays=test(d['C'],d['W'],pts,d['s'],cfg,2026102521)
    uniform,uniform_method=evenly_spread(d['W'],N)
    random=arrays['example_random_yx'].astype(float)
    observed=point_table(pts,d['D'],d['s'],'O'); observed.insert(1,'source_object_id',b.object_id.to_list())
    uniform_df=point_table(uniform,d['D'],d['s'],'U')
    random_df=point_table(random,d['D'],d['s'],'R')
    groups={'Observed positions':observed,'Uniform layout':uniform_df,'One random layout':random_df}
    for name,df in zip(['01_observed_distances.csv','02_evenly_spread_distances.csv','03_random_example_distances.csv'],groups.values()):
        df.to_csv(out/'tables'/name,index=False,encoding='utf-8-sig')
    wide=pd.DataFrame({'Distance rank':np.arange(1,N+1)})
    for name,df in groups.items(): wide[name+'Distance_um']=np.sort(df.distance_to_in_image_gray_um.to_numpy())
    wide.to_csv(out/'tables'/'three_groups_sorted_distances.csv',index=False,encoding='utf-8-sig')
    comparison=[]
    for name,df in groups.items():
        distances=df.distance_to_in_image_gray_um.to_numpy()
        row=dict(group=name,N=N,capped_mean_5um=float(np.minimum(5,distances).mean()),
                 within_0_5um=int((distances<=.5).sum()),within_1um=int((distances<=1).sum()),
                 within_2um=int((distances<=2).sum()),within_5um=int((distances<=5).sum()),
                 over_5um=int((distances>5).sum()),median_capped_5um=float(np.median(np.minimum(5,distances))))
        comparison.append(row)
        curves[name]=[(distances<=r).mean() for r in curves.r_um]
    pd.DataFrame(comparison).to_csv(out/'tables'/'three_group_summary.csv',index=False,encoding='utf-8-sig')
    curves.to_csv(out/'tables'/'distance_curves_and_null_envelope.csv',index=False,encoding='utf-8-sig')
    # Additional simple, directional explanation: how often random counts reach the observed 1 μm count?
    valid=np.flatnonzero(d['W']); Dflat=d['D'].ravel(); rng=np.random.default_rng(2026102521)
    random_counts=[]; capped_means=[]; sim_cdf_sum=np.zeros(len(curves))
    for start in range(0,4999,256):
        index=valid[rng.integers(len(valid),size=(min(256,4999-start),N))]
        distances=Dflat[index]
        random_counts.extend((distances<=1).sum(axis=1).tolist())
        capped_means.extend(np.minimum(5,distances).mean(axis=1).tolist())
        sim_cdf_sum+=(distances[:,:,None]<=curves.r_um.to_numpy()).sum(axis=1).sum(axis=0)/N
    random_counts=np.array(random_counts); capped_means=np.array(capped_means)
    observed_1=int((observed.distance_to_in_image_gray_um<=1).sum())
    summary.update(review_revision=d['info']['revision'],reviewed_gray_objects=d['info']['gray_objects'],
        eligible_bright=d['info']['eligible_bright'],observed_within_1um=observed_1,
        expected_count_within_1um=float(curves.loc[curves.r_um==1,'F0'].iloc[0]*N),
        random_trials_count_ge_observed_1um=int((random_counts>=observed_1).sum()),
        main_test_description='Two-sided maximum CDF deviation over fixed 0:0.25:5 um grid',
        explanatory_1um_count_is_not_main_p=True,
        uniform_group_is_descriptive_not_null=True,
        observed_capped_mean_5um=float(observed.distance_5um_capped_um.mean()),
        exact_null_capped_mean_5um=float(np.minimum(5,d['D'][d['W']]).mean()),
        uniform_capped_mean_5um=float(uniform_df.distance_5um_capped_um.mean()),
        one_random_capped_mean_5um=float(random_df.distance_5um_capped_um.mean()))
    np.savez_compressed(out/'tables'/'null_simulations.npz',**arrays,random_count_within_1um=random_counts,
        random_capped_means_5um=capped_means,mean_simulated_CDF=sim_cdf_sum/4999,uniform_yx=uniform,
        observed_yx=pts,grid_um=curves.r_um.to_numpy())
    clearance=ndi.distance_transform_edt(np.pad(d['A'],1),sampling=d['s'])[1:-1,1:-1]
    sensitivity=[]; sensitive_curves=[]
    for k,(title,C,W,area) in enumerate([
        ('Gray boundaries eroded by 1 pixel',ndi.binary_erosion(d['C']),d['W'],0),
        ('Gray boundaries dilated by 1 pixel',ndi.binary_dilation(d['C'])&d['A'],d['W'],0),
        ('Bright object area at least 0.05 μm²',d['C'],d['W'],.05),
        ('Additional 1 μm edge guard',d['C'],d['W']&(clearance>=6),0)]):
        q=b.loc[b.area_um2>=area,['centroid_y_px','centroid_x_px']].to_numpy()
        iq=np.floor(q+.5).astype(int);q=q[W[iq[:,0],iq[:,1]]]
        ss,cc,_=test(C,W,q,d['s'],cfg,2026103521+k)
        sensitivity.append(dict(condition=title,**ss));sensitive_curves.append(cc.assign(condition=title))
    pd.DataFrame(sensitivity).to_csv(out/'tables'/'sensitivity_summary.csv',index=False,encoding='utf-8-sig')
    pd.concat(sensitive_curves).to_csv(out/'tables'/'sensitivity_curves.csv',index=False,encoding='utf-8-sig')
    validchecks=dict(three_groups_same_N=all(len(x)==N for x in groups.values()),
        all_actual_centroids_inside_W=bool(d['W'][np.floor(pts[:,0]+.5).astype(int),np.floor(pts[:,1]+.5).astype(int)].all()),
        uniform_all_inside_W=bool(d['W'][uniform[:,0].astype(int),uniform[:,1].astype(int)].all()),
        random_all_inside_W=bool(d['W'][random[:,0].astype(int),random[:,1].astype(int)].all()),
        uniform_positions_distinct=len(np.unique(uniform,axis=0))==N,
        simulation_count=bool(len(arrays['sim_T'])==4999),
        critical_and_p_agree=summary['reject']==(summary['p']<=.05),
        exact_pixel_baseline=bool(np.array_equal(curves.baseline_pixel_count,[(d['D'][d['W']]<=r).sum() for r in curves.r_um])),
        outside_rmax_stays_in_denominator=bool(np.isclose(curves.Fobs.iloc[-1],1-summary['above_rmax']/N)),
        uniform_placement_ignores_gray_mask=method_ignores_gray(uniform_method),
        C_keeps_context_outside_W=bool((d['C']&~d['W']).any()))
    if not all(validchecks.values()):raise AssertionError(validchecks)
    (out/'logs'/'validation.json').write_text(json.dumps(validchecks,indent=2))
    return d,summary,curves,groups,uniform_method

def method_ignores_gray(info): return info['target_regions_used_for_placement'] is False

def main():
    p=argparse.ArgumentParser();p.add_argument('--review',type=Path,required=True)
    p.add_argument('--publish',action='store_true')
    args=p.parse_args();out=ROOT/'_tmp'/'field21_reviewed_stage'
    d,summary,curves,groups,method=run(args.review,out)
    from report_review21 import create_figures,write_report,render_report
    create_figures(out,d,summary,curves,groups)
    write_report(out,d,summary,curves,groups,method)
    render_report(out)
    (out/'logs'/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'logs'/'uniform_method.json').write_text(json.dumps(method,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
    if args.publish:
        dest=ROOT/'field21_reviewed'
        if dest.exists():
            import zipfile
            archive=ROOT/'report'/'field21_reviewed_vx-1.zip'
            with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
                for f in dest.rglob('*'):
                    if f.is_file():z.write(f,f.relative_to(dest))
        shutil.copytree(out,dest,dirs_exist_ok=True)
        print('Published',dest)

if __name__=='__main__':main()
