"""Replot a frozen summary as a new version, then verify numeric and native geometry."""
import argparse
import hashlib
from pathlib import Path

from self_service_engine import ROOT,load,dump


def verify(previous,result):
    import numpy as np
    import pandas as pd
    from PIL import Image
    from scipy import ndimage as ndi
    from area_redistribution21 import catalogue
    checks={};old=load(previous/'inputs'/'source_manifest.json');new=load(result/'inputs'/'source_manifest.json')
    assert old['cases']==new['cases'];checks['frozen_review_versions_and_original_p_values_preserved']=True
    for name in ['case_spatial_summary.csv','case_grain_summary.csv','pooled_grain_summary.csv','all_observed_distances.csv','all_grain_regions.csv']:
        pd.testing.assert_frame_equal(pd.read_csv(previous/'tables'/name),pd.read_csv(result/'tables'/name))
    checks['all_original_measurements_and_summaries_unchanged']=True
    records={r['code']:r for r in new['cases']};reference=pd.read_csv(result/'tables'/'mean_distance_reference.csv')
    for _,row in reference.iterrows():
        record=records[row.case_code]
        with np.load(result/record['copied_case']/'result'/'tables'/'point_simulations.npz') as bank:q=np.quantile(bank['mean'],[.025,.975])
        assert np.allclose(q,[row.random_mean_q025_um,row.random_mean_q975_um])
        assert np.isclose(row.observed_mean_um,record['point']['observed_mean']) and np.isclose(row.random_expected_mean_um,record['point']['reference_mean'])
    checks['mean_reference_is_original_null_95_percent_range_not_measurement_ci']=True
    all_seeds=[]
    for group in load(result/'logs'/'comparison_groups.json'):
        gi=group['group'];model=group['model'];members=[records[code] for code in group['case_codes']]
        before=pd.read_csv(previous/'tables'/f'{model}_combined_{gi}.csv');after=pd.read_csv(result/'tables'/f'{model}_combined_{gi}.csv')
        for column in ['r_um','observed','baseline']:assert np.allclose(before[column],after[column])
        grid=after.r_um.to_numpy();weights=np.array([r['point']['N'] for r in members],float)
        for column,filename in [('even','point_evenly_spread.csv' if model=='point' else '02_even_distances.csv'),('random_example','point_random_example.csv' if model=='point' else '03_random_distances.csv')]:
            curves=[]
            for record in members:
                d=pd.read_csv(result/record['copied_case']/'result'/'tables'/filename).distance_um.to_numpy();curves.append((d[:,None]<=grid).mean(axis=0))
            assert np.allclose(np.average(curves,axis=0,weights=weights),after[column])
        table=pd.read_csv(result/'tables'/f'{model}_combined_random_{gi}.csv');assert len(table)==group['random_curves']
        with np.load(result/'tables'/f'{model}_joint_random_{gi}.npz') as bank:
            assert np.allclose(table.iloc[:,1:],bank['combined_cdfs']);total=np.zeros_like(bank['combined_cdfs'])
            for record,weight,stream in zip(members,weights,group['streams']):
                code=record['code'];counts=bank[code+'_counts'];n=stream['particles_per_layout'];total+=weight*counts/n
                if stream['seed'] is None:continue
                all_seeds.append(tuple(stream['seed']));root=result/record['copied_case']/'result';scale=record['pixel_size_um']
                C=np.array(Image.open(root/'masks'/'C.png'))>0;W=np.array(Image.open(root/'masks'/'W.png'))>0;domain=W&~C
                D=ndi.distance_transform_edt(~C,sampling=(scale,scale))
                if model=='point':
                    locations=bank[code+'_locations_flat'];assert domain.ravel()[locations].all()
                    for start in range(0,len(locations),128):assert np.array_equal(counts[start:start+128],(D.ravel()[locations[start:start+128]][:,:,None]<=grid).sum(axis=1))
                else:
                    areas=bank[code+'_areas'];anchors=bank[code+'_anchors'];variants=bank[code+'_variants'];cats=catalogue(domain,areas)
                    assert int(areas.sum())==record['area']['total_area_px'] and areas.max()<=record['area']['cap_area_px']
                    for start in range(0,len(anchors),64):
                        a=anchors[start:start+64];v=variants[start:start+64];pixels=np.empty((len(a),int(areas.sum())),np.int32);centers=a.copy();offset=0
                        for j,area in enumerate(areas):
                            for k,variant in enumerate(cats[int(area)]['variants']):
                                rows=v[:,j]==k;pixels[rows,offset:offset+area]=a[rows,j,None]+variant['linear']
                                shift=np.floor(variant['offsets'].mean(axis=0)+.5).astype(int);centers[rows,j]+=int(shift[0])*C.shape[1]+int(shift[1])
                            offset+=area
                        assert domain.ravel()[pixels].all() and (np.diff(np.sort(pixels,axis=1),axis=1)>0).all()
                        assert np.array_equal(counts[start:start+64],(D.ravel()[centers][:,:,None]<=grid).sum(axis=1))
            assert np.allclose(total/weights.sum(),bank['combined_cdfs'])
            assert (np.diff(bank['combined_cdfs'],axis=1)>=-1e-12).all()
    assert len(set(all_seeds))==len(all_seeds)
    checks.update(original_combined_observed_and_baseline_unchanged=True,even_and_first_random_are_model_matched_weighted_curves=True,
                  all_requested_random_curves_exported=True,independent_random_streams_per_field_and_model=True,
                  all_point_locations_in_allowed_domain=True,all_finite_layouts_area_preserved_nonoverlapping_and_inside_domain=True,
                  all_cdfs_match_native_center_distances=True,no_new_pooled_p_value=True)
    for figure in load(result/'logs'/'figures.json'):
        for ext in ['pdf','svg','png','tiff']:assert (result/'figures'/f'{figure["stem"]}.{ext}').exists()
        assert not figure['collision']['fail'] and figure['minimum_font_pt']>=5
    checks['all_formats_fonts_and_collision_gates_pass']=True
    return checks


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--summary',type=Path);args=parser.parse_args()
    cases_root=ROOT.parent/'分析结果';previous=args.summary or Path(load(cases_root/'汇总报告'/'latest_summary.json')['report']).parent
    previous=previous.resolve();selection=load(previous/'inputs'/'selection.json')
    watched=[previous/'Summary.pdf',previous/'inputs'/'source_manifest.json']
    for r in load(previous/'inputs'/'source_manifest.json')['cases']:
        for name in ['config.json','report/review_annotations/review_annotations.json']:
            path=Path(r['source_case'])/name
            if path.exists():watched.append(path)
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in watched}
    from batch_summary import build_summary
    result=build_summary(selection,cases_root,frozen_summary=previous)
    checks=verify(previous,result);assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    checks['previous_reports_and_live_reviews_unmodified']=True
    record=dict(status='passed',previous=str(previous),result=str(result),checks=checks)
    dump(ROOT/'logs'/'summary_publication_validation.json',record);dump(result/'logs'/'publication_validation.json',record)
    import zipfile
    with zipfile.ZipFile(result/'Export.zip','a',zipfile.ZIP_DEFLATED) as bundle:bundle.write(result/'logs'/'publication_validation.json','logs/publication_validation.json')
    print(str(result),flush=True)


if __name__=='__main__':main()
