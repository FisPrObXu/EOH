"""Replay active native-coordinate review edits for field 21 without changing baseline files."""
import copy
import hashlib
import json
from pathlib import Path
import re
import cv2
import numpy as np
import pandas as pd
from PIL import Image
from scipy import ndimage as ndi

from app_runtime import ROOT

def replay(review_path, out, image_id='21', project_root=None):
    image_id=str(image_id)
    root=Path(project_root) if project_root is not None else ROOT
    raw = Path(review_path).read_bytes()
    review = json.loads(raw)
    html = (root/'report'/'Object_Review.html').read_text(encoding='utf-8')
    base = json.loads(re.search(r'<script id="review-data" type="application/json">(.*?)</script>',html,re.S).group(1))
    if review['dataset_id'] != base['dataset_id']: raise ValueError('Review and original object dataset differ')
    field = base['fields'][image_id]; objects = {r['object_id']:dict(copy.deepcopy(r),paths=[],modified=False,review_decision=None) for r in field['objects']}
    for c in field['contours']: objects[c['object_id']]['paths'] = copy.deepcopy(c['paths'])
    active = set(review['active_ids'])
    edits = [a for a in review['actions'] if a['id'] in active and a['image_id']==image_id]
    for a in edits:
        oid=a['object_id']; op=a['operation']
        if op in ['add_exclusion','replace_exclusion','delete_exclusion']:continue
        if op=='add_outline':
            if oid in objects: raise ValueError('Duplicate manual object ID: '+oid)
            objects[oid]=dict(object_id=oid,object_class=a['object_class'],paths=[a['points']],modified=True,
                              native_label=None,review_decision=None,manual_added=True)
        if oid not in objects: raise ValueError('Unknown object: '+oid)
        r=objects[oid]
        if op in ['replace_outline','delete_outline']:
            k=a.get('path_index',0)
            while len(r['paths'])<=k: r['paths'].append(None)
            r['paths'][k]=a.get('points') if op=='replace_outline' else None
            r['modified']=True
            if 'object_class' in a: r['object_class']=a['object_class']
        if op in ['keep','exclude','uncertain']: r['review_decision']=op
        r['last_review_operation']=op
        r['comment']=a.get('comment','')
    source_labels={k:np.array(Image.open(root/'masks'/f'{image_id}_{k}.tif')) for k in ['bright_labels','inclusion_labels','gray_raw_labels']}
    A=np.array(Image.open(root/'masks'/f'{image_id}_A.png'))>0
    W=np.array(Image.open(root/'masks'/f'{image_id}_W.png'))>0
    g=np.array(Image.open(root/'report'/f'{image_id}_native_grayscale.png'))
    cfg=json.loads((root/'config.json').read_text(encoding='utf-8-sig')); s=cfg['images'][image_id]['pixel_size_um']; p=cfg['segmentation']
    if image_id=='1' and (root/'masks'/'1_base_A.png').exists():
        from exclusion_geometry import context_masks
        A,W,_=context_masks(root,review)
        if not W.any():raise ValueError('W is empty after exclusions and boundary protection. Reduce the radius, remove incorrect exclusions or check the scale.')
    masks={}; bounds={}; rows=[]; overlaps=[]
    for oid,r in objects.items():
        category=r['object_class']
        if category=='gray_component_rejected' and not r['modified']: continue
        kind='bright' if category=='candidate_bright_particle' else 'gray'
        if r['modified']:
            valid_paths=[path for path in r['paths'] if path and len(path)>=3]
            if valid_paths:
                vertices=np.concatenate([np.asarray(p) for p in valid_paths])
                x0,y0=np.maximum(0,np.floor(vertices.min(axis=0)).astype(int)-2)
                x1,y1=np.minimum([A.shape[1],A.shape[0]],np.ceil(vertices.max(axis=0)).astype(int)+3)
            else:x0=y0=0;x1=y1=1
            if x0>=x1 or y0>=y1:x0=y0=0;x1=y1=1;valid_paths=[]
            mask=np.zeros((y1-y0,x1-x0),np.uint8)
            contours=[(np.rint(np.asarray(path)*256).astype(np.int32)-np.array([x0,y0])*256)[:,None,:] for path in valid_paths]
            if contours:cv2.fillPoly(mask,contours,1,shift=8)
            mask=mask>0
        else:
            key='bright_labels' if kind=='bright' else 'inclusion_labels'
            x0,y0,x1,y1=[int(r[k]) for k in ['bbox_x0','bbox_y0','bbox_x1','bbox_y1']]
            mask=source_labels[key][y0:y1,x0:x1]==r['native_label']
        area=int(mask.sum())
        if area:
            y,x=ndi.center_of_mass(mask);y+=y0;x+=x0;iy,ix=np.floor(np.array([y,x])+.5).astype(int)
            in_a=bool(A[iy,ix]); in_w=bool(W[iy,ix])
        else:
            y=x=0.; iy=ix=0; in_a=in_w=False
        manual=bool(r['modified'] or r['review_decision']=='keep')
        enough=area>=p['bright_min_pixels'] and area*s*s>=p['bright_min_area_um2']
        eligible=area>0 and r['review_decision']!='exclude' and (kind=='gray' or enough or manual)
        reason='user_excluded' if r['review_decision']=='exclude' else 'deleted_outline' if not area else 'below_auto_minimum' if kind=='bright' and not (enough or manual) else ''
        included=eligible and in_w if kind=='bright' else eligible
        if kind=='bright' and eligible and not in_w: reason='outside_protected_W'
        rows.append(dict(object_id=oid,object_class=category,kind=kind,manual_geometry=r['modified'],
            manual_added=r.get('manual_added',False),review_decision=r['review_decision'] or 'unchanged_after_user_review',
            source_native_label=r['native_label'],centroid_x_px=x,centroid_y_px=y,grid_x_px=ix,grid_y_px=iy,
            x_um=(x+.5)*s,y_um=(y+.5)*s,area_px=area,area_um2=area*s*s,auto_size_pass=enough,
            in_A=in_a,in_W=in_w,eligible=eligible,included=included,exclusion_reason=reason,comment=r.get('comment','')))
        if eligible:
            masks[oid]=mask
            bounds[oid]=(int(y0),int(y1),int(x0),int(x1))
    if not rows:raise ValueError('No usable objects')
    table=pd.DataFrame(rows)
    # Report actual intersections; never count an overlapping manual bright object twice silently.
    for kind in ['bright','gray']:
        ids=table.loc[(table.kind==kind)&table.eligible,'object_id'].tolist()
        for k,a in enumerate(ids):
            for b in ids[k+1:]:
                ay0,ay1,ax0,ax1=bounds[a];by0,by1,bx0,bx1=bounds[b]
                y0,y1=max(ay0,by0),min(ay1,by1);x0,x1=max(ax0,bx0),min(ax1,bx1)
                if y0>=y1 or x0>=x1:continue
                n=int((masks[a][y0-ay0:y1-ay0,x0-ax0:x1-ax0]&masks[b][y0-by0:y1-by0,x0-bx0:x1-bx0]).sum())
                if n: overlaps.append(dict(kind=kind,object_a=a,object_b=b,overlap_px=n))
    pd.DataFrame(overlaps,columns=['kind','object_a','object_b','overlap_px']).to_csv(out/'tables'/'review_overlap_checks.csv',index=False)
    bright_overlap=[r for r in overlaps if r['kind']=='bright']
    if bright_overlap: raise ValueError('Overlapping bright objects require resolution: '+str(bright_overlap))
    C=np.zeros(A.shape,bool); bright_labels=np.zeros(A.shape,np.int32); gray_labels=np.zeros(A.shape,np.int32)
    mapping=[]
    for kind,label_array in [('gray',gray_labels),('bright',bright_labels)]:
        for lab,oid in enumerate(table.loc[(table.kind==kind)&table.eligible,'object_id'],1):
            mask=masks[oid]
            y0,y1,x0,x1=bounds[oid];region=np.s_[y0:y1,x0:x1]
            if kind=='gray':
                local=mask&A[region];C[region]|=local;label_array[region][local]=lab
            else:label_array[region][mask]=lab
            mapping.append(dict(object_id=oid,reviewed_native_label=lab,kind=kind))
    if cfg.get('analysis',{}).get('exclusive_phases',False):
        C&=bright_labels==0;gray_labels[~C]=0
    D=ndi.distance_transform_edt(~C,sampling=(s,s))
    for j,row in table.iterrows():
        if row.area_px>0:
            table.loc[j,'distance_to_in_image_gray_um']=D[int(row.grid_y_px),int(row.grid_x_px)]
            table.loc[j,'distance_5um_capped_um']=min(5,D[int(row.grid_y_px),int(row.grid_x_px)])
            table.loc[j,'distance_gt_5um']=bool(D[int(row.grid_y_px),int(row.grid_x_px)]>5)
    table.to_csv(out/'tables'/'reviewed_objects.csv',index=False)
    pd.DataFrame(mapping).to_csv(out/'tables'/'reviewed_label_mapping.csv',index=False)
    for key,m in [('C',C),('W',W),('A',A)]: Image.fromarray(m.astype(np.uint8)*255).save(out/'masks'/f'{image_id}_{key}.png')
    for key,m in [('bright_labels',bright_labels),('inclusion_labels',gray_labels)]:
        Image.fromarray(m).save(out/'masks'/f'{image_id}_{key}.tif',compression='tiff_deflate')
    (out/'logs'/'review_used.json').write_bytes(raw)
    info=dict(revision=review['revision'],dataset_id=review['dataset_id'],review_sha256=hashlib.sha256(raw).hexdigest(),
        total_actions=len(review['actions']),image_id=image_id,active_field_actions=len(edits),
        added_gray_objects=int(((table.kind=='gray')&table.manual_added).sum()),
        added_bright_objects=int(((table.kind=='bright')&table.manual_added).sum()),
        deleted_objects=int((table.area_px==0).sum()),repeated_keep_one_object=any(sum(a['operation']=='keep' and a['object_id']==oid for a in edits)>1 for oid in objects),
        gray_objects=int(((table.kind=='gray')&table.eligible).sum()),
        gray_connected_regions=int(ndi.label(C,np.ones((3,3)))[1]),
        gray_overlap_pairs=len([r for r in overlaps if r['kind']=='gray']),
        eligible_bright=int(((table.kind=='bright')&table.eligible).sum()),
        N=int(((table.kind=='bright')&table.included).sum()),W_area_um2=float(W.sum()*s*s),
        manually_added_outside_W=table.loc[table.manual_added&(table.kind=='bright')&~table.in_W,'object_id'].tolist(),
        manual_eligibility_rule='User-drawn/explicitly-kept bright outlines retained even below automatic size threshold; require nonzero native area and W membership.',
        raster_rule='Unedited objects preserve original pixels; edited contour coordinates use OpenCV fillPoly shift=8 (1/256 native pixel). C is clipped to the original readable context A; W is unchanged.',
        phase_identity_validated=False,user_reports_editing_complete=bool(review.get('human_review_confirmed',True)),
        segmentation_status='user-edited geometry; unchanged objects retain automatic geometry')
    (out/'logs'/'review_application.json').write_text(json.dumps(info,indent=2,ensure_ascii=False),encoding='utf-8')
    return dict(C=C,W=W,A=A,g=g,s=s,table=table,info=info,D=D)
