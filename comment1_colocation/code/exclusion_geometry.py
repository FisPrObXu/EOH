"""Native-pixel point/polyline buffers shared by preview and quantitative analysis."""
import base64
from io import BytesIO
import math
import numpy as np
from PIL import Image
from segmentation import protected_window


def active_exclusions(config,review):
    shapes={str(k):dict(r,id=str(k)) for k,r in enumerate(config.get('exclusion_shapes',[]))}
    active=set(review.get('active_ids',[]))
    for a in review.get('actions',[]):
        if a['id'] not in active or str(a.get('image_id'))!='1':continue
        if a['operation'] in ['add_exclusion','replace_exclusion']:shapes[a['object_id']]=dict(a['geometry'],id=a['object_id'])
        elif a['operation']=='delete_exclusion':shapes.pop(a['object_id'],None)
    return list(shapes.values())


def exclusion_mask(shape,scale,shapes):
    h,w=shape;result=np.zeros(shape,bool)
    for item in shapes:
        kind=item['kind'];points=np.asarray(item['points'],float)
        if points.ndim!=2 or points.shape[1]!=2 or not np.isfinite(points).all():raise ValueError('Invalid exclusion coordinates.')
        radius=float(item.get('radius_um',0))/scale
        if kind not in ['point','line','rectangle'] or not math.isfinite(radius) or radius<0:raise ValueError('Invalid exclusion type or radius.')
        if kind=='line' and len(points)<2:raise ValueError('A crack line needs at least two points.')
        if kind=='point' and len(points)!=1:raise ValueError('A hole exclusion needs one center point.')
        x0,y0=np.maximum([0,0],np.floor(points.min(axis=0)-radius-1)).astype(int)
        x1,y1=np.minimum([w,h],np.ceil(points.max(axis=0)+radius+2)).astype(int)
        if x1<=x0 or y1<=y0:continue
        yy,xx=np.mgrid[y0:y1,x0:x1];best=np.full(xx.shape,np.inf)
        if kind=='rectangle':
            lo=points.min(axis=0);hi=points.max(axis=0);inside=(xx>=lo[0])&(xx<hi[0])&(yy>=lo[1])&(yy<hi[1])
        else:
            segments=[(points[0],points[0])] if kind=='point' else zip(points[:-1],points[1:])
            for a,b in segments:
                delta=b-a;denom=float(delta@delta);t=np.zeros(xx.shape) if denom==0 else np.clip(((xx-a[0])*delta[0]+(yy-a[1])*delta[1])/denom,0,1)
                best=np.minimum(best,(xx-a[0]-t*delta[0])**2+(yy-a[1]-t*delta[1])**2)
            inside=best<=radius**2+1e-12
        result[y0:y1,x0:x1]|=inside
    return result


def context_masks(case,review):
    from self_service_engine import load
    cfg=load(case/'config.json');scale=cfg['images']['1']['pixel_size_um']
    path=case/'masks'/'1_base_A.png'
    if not path.exists():
        return np.array(Image.open(case/'masks'/'1_A.png'))>0,np.array(Image.open(case/'masks'/'1_W.png'))>0,[]
    base=np.array(Image.open(path))>0;shapes=active_exclusions(cfg,review);A=base&~exclusion_mask(base.shape,scale,shapes)
    W,_=protected_window(A,A,scale,cfg['analysis']['rmax_um'])
    return A,W,shapes


def update_field_context(case,field,review):
    if not (case/'masks'/'1_base_A.png').exists():return field
    from review_editor import paths,runs
    A,W,shapes=context_masks(case,review);rgba=np.zeros((*A.shape,4),np.uint8);rgba[~A]=[200,50,50,70]
    from self_service_engine import load
    cfg=load(case/'config.json');guard=cfg['analysis'].get('size_guard_um',1);sizeW,_=protected_window(A,A,cfg['images']['1']['pixel_size_um'],guard)
    stream=BytesIO();Image.fromarray(rgba).save(stream,format='PNG')
    field=dict(field,A_runs=runs(A),W_runs=runs(W),window_paths=paths(W),exclusion_shapes=shapes,
        exclusion_image='data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode(),size_W_runs=runs(sizeW),size_window_paths=paths(sizeW),size_guard_um=guard,distance_guard_um=cfg['analysis']['rmax_um'])
    return field
