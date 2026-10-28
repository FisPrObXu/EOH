"""Create a new bright-candidate version while retaining all manual review history."""
from datetime import datetime
from pathlib import Path
import copy
import hashlib
import json
import re
import shutil
import uuid
import numpy as np
import cv2
from PIL import Image
from scipy import ndimage as ndi

from self_service_engine import ROOT,load,dump,tempdir,safe_remove,configure_temp,within,validate_output_root,editor_document,emit,check_cancel
from bright_segmentation import defaults,validate,detect_bright


def enhance_case(case,options=None,cases_root=None):
    from analysis import build_particle_table
    from review_editor import paths
    case=Path(case).resolve();cases_root=validate_output_root(cases_root or case.parent);options=options or {}
    meta=load(case/'case.json');cfg=load(case/'config.json');review=load(case/'report/review_annotations/review_annotations.json')
    document=load(case/'inputs/review_dataset.json');field=document['fields']['1']
    if review['dataset_id']!=document['dataset_id']:raise ValueError('Review and case do not match. No enhanced copy was created.')
    p=dict(cfg['segmentation']);p.update(defaults(options.get('sensitivity','balanced'),options.get('boundary_fraction',.35)))
    minimum=options.get('minimum_pixels',2)
    if not np.isfinite(float(minimum)) or float(minimum)!=int(minimum) or not 1<=int(minimum)<=100:raise ValueError('Minimum pixel count must be an integer from 1 to 100.')
    p['bright_min_pixels']=int(minimum);validate(p)
    stage=tempdir(cases_root/'_tmp','bright');configure_temp(stage/'_runtime');committed=False
    try:
        emit('Detecting small bright grains by local contrast and determining boundaries…',job=str(stage))
        for name in ['inputs','masks','tables']:shutil.copytree(case/name,stage/name)
        for name in ['logs','results','report/review_annotations']:(stage/name).mkdir(parents=True,exist_ok=True)
        shutil.copyfile(case/'report/1_native_grayscale.png',stage/'report/1_native_grayscale.png')
        if (case/'plot_settings.json').exists():shutil.copyfile(case/'plot_settings.json',stage/'plot_settings.json')
        from exclusion_geometry import context_masks
        g=np.array(Image.open(stage/'report/1_native_grayscale.png'));readable,_,_=context_masks(case,review)
        old=np.array(Image.open(stage/'masks/1_bright_labels.tif'));detected,info=detect_bright(g,p,readable);check_cancel(stage)
        # Every historical target is protected, including undo/redo, explicit deletion
        # and rejection. Re-detection must not resurrect a manually removed object.
        touched={a['object_id'] for a in review['actions']};bright_class='candidate_bright_particle'
        protected={r['object_id']:r for r in field['objects'] if r['object_class']==bright_class and r['object_id'] in touched}
        bright_ids=set(protected)|{a['object_id'] for a in review['actions'] if a.get('object_class')==bright_class}
        reserved=np.isin(old,[r['native_label'] for r in protected.values()])
        geometry=np.zeros(g.shape,np.uint8)
        for a in review['actions']:
            points=a.get('points')
            if a['object_id'] in bright_ids and points and len(points)>=3:
                cv2.fillPoly(geometry,[np.rint(np.asarray(points)*256).astype(np.int32)],1,shift=8)
        reserved|=geometry>0
        # A one-native-pixel guard prevents a second proposal for the same reviewed spot.
        collisions=set(np.unique(detected[ndi.binary_dilation(reserved,structure=np.ones((3,3),bool))]));collisions.discard(0)
        labels=np.where(np.isin(old,[r['native_label'] for r in protected.values()]),old,0).astype(np.int32)
        next_label=int(old.max());mapping=[]
        for r in info['objects']:
            if r['label'] in collisions:continue
            next_label+=1;labels[detected==r['label']]=next_label;mapping.append(dict(detector_label=r['label'],object_id=f'B{next_label:04d}',native_label=next_label))
        m={name:np.array(Image.open(stage/'masks'/f'1_{name}.png'))>0 for name in ['A','W','C','crack']};m['bright_labels']=labels
        cfg=copy.deepcopy(cfg);cfg['segmentation']=p;cfg['parameter_version']='self-service-bright-v3'
        cfg['bright_enhancement']=dict(source_case_id=meta['case_id'],source_revision=review['revision'],manual_history_preserved=True)
        scale=meta['pixel_size_um'];table=build_particle_table('1',m,g,scale,p,m['W'],ndi.distance_transform_edt(~m['C'],sampling=scale),cfg)
        if len(table):table=table[~table.object_id.isin(protected)]
        fresh=json.loads(table.to_json(orient='records')) if len(table) else []
        kept=[r for r in field['objects'] if r['object_class']!=bright_class or r['object_id'] in protected]
        retained_ids={r['object_id'] for r in kept};contours=[c for c in field['contours'] if c['object_id'] in retained_ids]
        for row in fresh:
            x0,y0,x1,y1=[int(row[k]) for k in ['bbox_x0','bbox_y0','bbox_x1','bbox_y1']]
            pp=paths(labels[y0:y1,x0:x1]==row['native_label'])
            contours.append(dict(object_id=row['object_id'],object_class=bright_class,paths=[[[x+x0,y+y0] for x,y in path] for path in pp]))
        field['objects']=kept+fresh;field['contours']=contours
        import pandas as pd
        pd.DataFrame([r for r in field['objects'] if r['object_class']==bright_class]).to_csv(stage/'tables/1_particles.csv',index=False)
        Image.fromarray(labels).save(stage/'masks/1_bright_labels.tif',compression='tiff_deflate')
        key='case_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
        document['dataset_id']=hashlib.sha256(json.dumps(dict(case_id=key,config=cfg,field=field),sort_keys=True).encode()).hexdigest()[:20]
        document['api_base']='/case/'+key;document['start_full']=True;field['display_name']=meta['name']+' · Bright enhancement'
        dump(stage/'config.json',cfg);dump(stage/'inputs/review_dataset.json',document);editor_document(stage,document)
        original_review=copy.deepcopy(review);review['dataset_id']=document['dataset_id'];review['human_review_confirmed']=False
        dump(stage/'report/review_annotations/review_annotations.json',review)
        dump(stage/'inputs/source_review.json',original_review)
        newmeta=dict(meta,case_id=key,name=field['display_name'],dataset_id=document['dataset_id'],config=cfg,version=3,
                     config_sha256=hashlib.sha256((stage/'config.json').read_bytes()).hexdigest(),created=datetime.now().astimezone().isoformat(),
                     enhanced_from=dict(case=str(case),case_id=meta['case_id'],review_revision=review['revision']))
        dump(stage/'case.json',newmeta);dump(stage/'logs/bright_detection.json',info)
        dump(stage/'logs/bright_enhancement.json',dict(source_case=str(case),source_revision=review['revision'],
             preserved_auto_bright_objects=list(protected),preserved_actions=len(review['actions']),
             suppressed_near_manual_objects=len(collisions),new_candidates=len(fresh),candidate_mapping=mapping,
             old_reports_retained_at_source=True,requires_review=True))
        check_cancel(stage)
        from self_service_engine import _remove_owned_tree
        _remove_owned_tree(within(stage/'_runtime',stage))
        stem=re.sub(r'[<>:"/\\|?*]','_',case.name)+'_bright_enhanced';destination=within(cases_root/stem,cases_root);number=2
        while destination.exists():destination=within(cases_root/(stem+'_'+str(number)),cases_root);number+=1
        stage.rename(destination);committed=True;(destination/'.temporary-owner.json').unlink()
        emit(f'Manual records from revision r{review["revision"]} retained; generated {len(fresh)} bright candidates for review.')
        return destination
    finally:
        if not committed and stage.exists():safe_remove(stage,cases_root/'_tmp')
