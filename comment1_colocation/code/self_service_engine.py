"""Case-isolated import and analysis for the desktop BSE workflow."""
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import traceback
import uuid

from app_runtime import ROOT,error_message
CASES=ROOT/'self_service_cases'


class UserError(RuntimeError):pass
class Cancelled(UserError):pass


def emit(message,**extra):
    value=dict(event='progress',message=message);value.update(extra)
    print(json.dumps(value,ensure_ascii=False),flush=True)


def load(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def dump(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    # Keep the atomic-write name short: the user project already has a deep path.
    pending=path.with_name('.write_'+uuid.uuid4().hex[:8])
    pending.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');pending.replace(path)


def within(path,parent):
    p,base=Path(path).resolve(),Path(parent).resolve()
    if p==base or not p.is_relative_to(base):raise UserError('The path must be inside the specified project subdirectory.')
    return p


def safe_remove(path,parent):
    p=within(path,parent)
    if not (p/'.temporary-owner.json').exists():raise UserError('Temporary folder retained because ownership is unknown: '+str(p))
    ownership=(p/'.temporary-owner.json').read_bytes()
    try:_remove_owned_tree(p)
    except Exception:
        # A locked file can interrupt deletion after the marker was removed.
        # Preserve the original proof of ownership so cleanup can be retried.
        if p.is_dir() and not (p/'.temporary-owner.json').exists():
            try:(p/'.temporary-owner.json').write_bytes(ownership)
            except OSError:pass
        raise


def _remove_owned_tree(path):
    """Remove only a previously verified task-owned tree, including OneDrive read-only flags."""
    root=Path(path).resolve()
    def retry(function,child,error):
        resolved=Path(str(child).removeprefix('\\\\?\\')).resolve()
        if resolved!=root and not resolved.is_relative_to(root):raise UserError('Cleanup path is outside the verified directory.')
        if not isinstance(error,PermissionError):raise error
        os.chmod(child,stat.S_IWRITE|stat.S_IREAD)
        function(child)
    # A completed run folder can acquire a longer path when it is renamed into results.
    io_root='\\\\?\\'+str(root) if os.name=='nt' and not str(root).startswith('\\\\?\\') else root
    shutil.rmtree(io_root,onexc=retry)


def tempdir(parent,prefix):
    parent=Path(parent);parent.mkdir(parents=True,exist_ok=True)
    p=parent/(prefix+'_'+uuid.uuid4().hex[:10]);p.mkdir()
    dump(p/'.temporary-owner.json',dict(owner='bse-self-service',purpose='temporary',created=datetime.now().isoformat()))
    return p


def configure_temp(path):
    import tempfile
    p=Path(path);p.mkdir(parents=True,exist_ok=True)
    for key in ['TEMP','TMP','TMPDIR']:os.environ[key]=str(p)
    tempfile.tempdir=str(p)
    os.environ['MPLCONFIGDIR']=str(p/'mpl');os.environ['PYTHONDONTWRITEBYTECODE']='1';os.environ['PYTHONUTF8']='1'
    sys.dont_write_bytecode=True


def case_path(key,cases=CASES):
    if not re.fullmatch(r'case_[A-Za-z0-9_]+',key):raise UserError('Invalid case identifier.')
    direct=Path(cases)/key
    if (direct/'case.json').exists():return within(direct,cases)
    if Path(cases).exists():
        for folder in Path(cases).iterdir():
            if folder.is_dir() and (folder/'case.json').exists():
                if load(folder/'case.json').get('case_id')==key:return within(folder,cases)
    return within(direct,cases)


def validate_output_root(path):
    path=Path(path).resolve()
    from app_runtime import FROZEN
    if not FROZEN and path.drive.lower()!=ROOT.drive.lower():raise UserError('Select an output folder on drive E, as required for this project.')
    return path


def adaptive_parameters(g,p):
    import numpy as np
    p=dict(p);values=g[(g>25)&(g<235)];matrix=float(np.median(values)) if len(values) else 170.
    p.update(void_threshold=max(12,matrix*.24),gray_floor=max(20,matrix*.38),gray_ceiling=min(230,matrix*.98),
        background_min_gray=matrix*.78,background_max_gray=min(240,matrix*1.3),gray_residual=max(5,matrix*.055),crack_intensity=matrix*.62,
        adaptive_matrix_gray=matrix)
    return p


def validate_spec(spec,size):
    import numpy as np
    w,h=size;crop=[int(v) for v in spec.get('crop',[0,0,w,h])]
    if len(crop)!=4 or not (0<=crop[0]<crop[2]<=w and 0<=crop[1]<crop[3]<=h):raise UserError('Crop coordinates are outside the image, or the crop is empty.')
    if crop[2]-crop[0]<32 or crop[3]-crop[1]<32:raise UserError('The crop must retain at least 32 × 32 native pixels.')
    scale=float(spec['pixel_size_um']);a=spec.get('analysis',{})
    rmax=float(a.get('rmax_um',5));step=float(a.get('step_um',.25));near=float(a.get('near_um',1));size_guard=float(a.get('size_guard_um',1))
    if not np.isfinite(size_guard) or size_guard<0:raise UserError('The grain-size edge guard must be finite and nonnegative, in μm.')
    if not all(np.isfinite(v) and v>0 for v in [scale,rmax,step,near]):raise UserError('Pixel size and distance parameters must be finite and positive.')
    if step>rmax or near>rmax or abs(rmax/step-round(rmax/step))>1e-6:raise UserError('Distance limit must be a multiple of step size; the near threshold cannot exceed the limit. Example: 5 / 0.25 / 1 μm.')
    if rmax/step>400:raise UserError('The distance grid exceeds 400 points. Select a step consistent with localization precision.')
    controls=a.get('control_count');controls=None if controls in [None,''] else int(controls)
    if controls is not None and controls<1:raise UserError('Control count must be a positive integer, or blank to use the observed count.')
    a=dict(rmax_um=rmax,step_um=step,near_um=near,B=4999,seed=int(a.get('seed',20261026)),
           finite=bool(a.get('finite',True)),control_count=controls,mode=a.get('mode','full'),exclusive_phases=bool(a.get('exclusive_phases',False)),size_guard_um=size_guard)
    if a['mode'] not in ['full','sizes']:raise UserError('Invalid analysis mode.')
    from bright_segmentation import defaults as bright_defaults,validate as validate_bright
    p=load(ROOT/'config.json')['segmentation'];p.update(bright_defaults());p.update(spec.get('segmentation',{}));validate_bright(p)
    if not 0<float(p['bright_threshold'])<=255 or int(p['bright_min_pixels'])<1 or float(p['bright_min_area_um2'])<0:raise UserError('Bright threshold must be 1–255 and minimum pixel count at least 1.')
    if float(p['gray_residual'])<=0 or float(p['gray_min_area_um2'])<0:raise UserError('Dark residual threshold must be positive and minimum area nonnegative.')
    return crop,scale,a,p


def editor_document(case,document):
    t=(ROOT/'code'/'review_editor.html').read_text(encoding='utf-8-sig')
    t=t.replace('__REVIEW_DATA__',json.dumps(document,ensure_ascii=False).replace('</','<\\/'))
    addon=(ROOT/'code'/'review_exclusions.js').read_text(encoding='utf-8')
    t=t.replace('init().catch(e=>',addon+'\ninit().catch(e=>')
    t=t.replace('href="http://127.0.0.1:8765/"','href="'+document.get('review_url','#')+'"')
    (case/'report'/'Object_Review.html').write_text(t,encoding='utf-8')


def import_image(spec,cases=CASES):
    import numpy as np
    from PIL import Image
    from scipy import ndimage as ndi
    from segmentation import make_masks,protected_window
    from analysis import build_particle_table,inclusion_table,save_masks
    from review_editor import paths,runs
    import pandas as pd
    cases=validate_output_root(cases)
    key='case_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
    stage=tempdir(cases/'_tmp','import');committed=False
    configure_temp(stage/'_runtime')
    try:
        source=Path(spec['source']).resolve();emit('Reading image and checking scale and crop…')
        with Image.open(source) as image:
            if getattr(image,'n_frames',1)!=1:raise UserError('Select or export a single-frame image first.')
            if image.mode not in ['L','P','RGB','RGBA']:raise UserError('This tool uses 8-bit BSE intensities. Export an 8-bit TIFF / PNG copy using a known intensity mapping and retain the original.')
            crop,scale,a,p=validate_spec(spec,image.size);g=np.array(image.convert('L').crop(crop));original_mode=image.mode;size=list(image.size)
        for folder in ['inputs','masks','tables','report/review_annotations','logs','results']:(stage/folder).mkdir(parents=True,exist_ok=True)
        original=stage/'inputs'/('original'+source.suffix.lower());shutil.copy2(source,original)
        native=stage/'report'/'1_native_grayscale.png';Image.fromarray(g).save(native)
        if spec.get('adaptive_segmentation',False):p=adaptive_parameters(g,p)
        emit('Building bright / dark candidate outlines and window W…')
        m=make_masks(g,scale,p)
        if m.get('bright_diagnostics'):dump(stage/'logs'/'bright_detection.json',m['bright_diagnostics'])
        context=m['A'].copy() if spec.get('auto_domain',True) else np.ones(g.shape,bool)
        if not np.array_equal(context,m['A']):m=make_masks(g,scale,p,context_mask=context)
        Image.fromarray(context.astype(np.uint8)*255).save(stage/'masks'/'1_base_A.png')
        shapes=list(spec.get('exclusion_shapes',[]))
        for rect in spec.get('exclusions',[]):
            x0,y0,x1,y1=[int(v) for v in rect];x0=max(0,x0-crop[0]);x1=min(g.shape[1],x1-crop[0]);y0=max(0,y0-crop[1]);y1=min(g.shape[0],y1-crop[1])
            if x1>x0 and y1>y0:shapes.append(dict(kind='rectangle',points=[[x0,y0],[x1,y1]],radius_um=0))
        from exclusion_geometry import exclusion_mask
        context&=~exclusion_mask(g.shape,scale,shapes);m['A']=context;m['C']&=context
        m['observable']=m['A'].copy();m['W'],_=protected_window(m['A'],m['A'],scale,a['rmax_um']);m['protection_band']=m['A']&~m['W']
        if not m['W'].any():raise UserError('W is empty at the current guard distance. Check pixel size, crop and exclusions, or choose a justified smaller distance limit before viewing results.')
        cfg=dict(parameter_version='self-service-v2',segmentation=p,images={'1':dict(pixel_size_um=scale,crop_xyxy=crop)},statistics=dict(rmax_um=a['rmax_um']),analysis=a,exclusion_shapes=shapes,
            phase_names=dict(gray='Chalcopyrite',bright='Gold'),phase_identity_basis='User supplied class mapping; not independently chemically verified',adaptive_segmentation=bool(spec.get('adaptive_segmentation',False)))
        dump(stage/'config.json',cfg)
        D=ndi.distance_transform_edt(~m['C'],sampling=scale)
        bright=build_particle_table('1',m,g,scale,p,m['W'],D,cfg);gray=inclusion_table('1',m,scale,cfg)
        bright.to_csv(stage/'tables'/'1_particles.csv',index=False);gray.to_csv(stage/'tables'/'1_inclusions_and_rejected.csv',index=False);save_masks(stage,'1',m)
        objects=json.loads(pd.concat([bright,gray],ignore_index=True).to_json(orient='records'))
        contours=[]
        for row in objects:
            if row['object_class']=='gray_component_rejected':continue
            stem='bright_labels' if row['object_class']=='candidate_bright_particle' else 'inclusion_labels'
            x0,y0,x1,y1=[int(row[k]) for k in ['bbox_x0','bbox_y0','bbox_x1','bbox_y1']]
            pp=paths(m[stem][y0:y1,x0:x1]==row['native_label'])
            contours.append(dict(object_id=row['object_id'],object_class=row['object_class'],paths=[[[x+x0,y+y0] for x,y in path] for path in pp]))
        source_hash=hashlib.sha256(original.read_bytes()).hexdigest()
        field=dict(width=g.shape[1],height=g.shape[0],display_name=spec.get('name',source.stem),pixel_size_um=scale,objects=objects,
                   contours=contours,window_paths=paths(m['W']),W_runs=runs(m['W']),A_runs=runs(m['A']),exclusion_shapes=[dict(r,id=str(k)) for k,r in enumerate(shapes)],
                   image='data:image/png;base64,'+base64.b64encode(native.read_bytes()).decode())
        rgba=np.zeros((*g.shape,4),np.uint8);rgba[~m['A']]=[200,50,50,55]
        from io import BytesIO
        buffer=BytesIO();Image.fromarray(rgba).save(buffer,format='PNG');field['exclusion_image']='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()
        binding=dict(case_id=key,source_sha256=source_hash,config=cfg,field={k:v for k,v in field.items() if k not in ['image','exclusion_image']})
        dataset_id=hashlib.sha256(json.dumps(binding,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:20]
        document=dict(schema_version=1,dataset_id=dataset_id,fields={'1':field},api_base='/case/'+key,start_full=True,editable_exclusions=True)
        dump(stage/'inputs'/'review_dataset.json',document);dump(stage/'logs'/'review_dataset.json',dict(dataset_id=dataset_id))
        editor_document(stage,document)
        dump(stage/'report'/'review_annotations'/'review_annotations.json',dict(schema_version=1,dataset_id=dataset_id,reviewer='',revision=0,actions=[],active_ids=[],redo_ids=[]))
        dump(stage/'case.json',dict(case_id=key,name=spec.get('name',source.stem),created=datetime.now().astimezone().isoformat(),
             source_name=source.name,source_original=str(source),source_sha256=source_hash,original_dimensions=size,original_mode=original_mode,
             cropped_dimensions=[g.shape[1],g.shape[0]],pixel_size_um=scale,crop_xyxy=crop,calibration=spec.get('calibration',{}),
             notes=spec.get('notes',''),dataset_id=dataset_id,config=cfg,config_sha256=hashlib.sha256((stage/'config.json').read_bytes()).hexdigest(),version=2))
        if (stage/'_runtime').exists():_remove_owned_tree(within(stage/'_runtime',stage))
        folder_name=re.sub(r'[<>:"/\\|?*]','_',source.stem).strip(' .') or key
        dest=within(cases/folder_name,cases);n=2
        while dest.exists():dest=within(cases/(folder_name+'_'+str(n)),cases);n+=1
        try:stage.rename(dest)
        except PermissionError:
            import gc
            gc.collect()
            try:stage.rename(dest)
            except PermissionError:
                emit('Windows prevented a folder rename; saving the imported case by copying…')
                dest.mkdir();dump(dest/'.temporary-owner.json',load(stage/'.temporary-owner.json'))
                try:shutil.copytree(stage,dest,dirs_exist_ok=True)
                except Exception:
                    safe_remove(dest,cases)
                    raise
                safe_remove(stage,cases/'_tmp')
        committed=True
        (dest/'.temporary-owner.json').unlink()
        return dest
    finally:
        if not committed and stage.exists():safe_remove(stage,cases/'_tmp')


@contextmanager
def analysis_lock(case):
    import msvcrt
    f=(case/'logs'/'analysis.lock').open('a+b')
    try:
        if f.tell()==0:f.write(b'0');f.flush()
        f.seek(0)
        try:msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise UserError('This case is being processed in another window. Wait for completion.')
        yield
    finally:
        try:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
        except OSError:pass
        f.close()


def check_cancel(job):
    if (job/'cancel.flag').exists():raise Cancelled('Calculation stopped. Original images, review records and previous reports are retained.')


def measure(points,D,scale,cap,areas=None,ids=None):
    import numpy as np
    import pandas as pd
    points=np.asarray(points,float);q=np.floor(points+.5).astype(int);dd=D[q[:,0],q[:,1]]
    f=pd.DataFrame(dict(object_id=ids or [f'P{k+1:04d}' for k in range(len(q))],centroid_y_px=points[:,0],centroid_x_px=points[:,1],
        grid_y_px=q[:,0],grid_x_px=q[:,1],y_um=(points[:,0]+.5)*scale,x_um=(points[:,1]+.5)*scale,
        distance_um=dd,distance_capped_um=np.minimum(cap,dd),above_rmax=dd>cap))
    if areas is not None:f['area_px']=areas;f['area_um2']=np.asarray(areas)*scale**2
    return f


def point_model(d,observed,settings,job,out):
    import numpy as np
    from scipy.stats import binom
    from analyze_review21 import evenly_spread
    C,W,D=d['C'],d['W'],d['D'];domain=W&~C;valid=np.flatnonzero(domain);base=D.ravel()[valid]
    if not len(valid):raise UserError('No positions outside dark regions are available in W. Check dark outlines and the protected window.')
    N=len(observed);B=settings['B'];cap=settings['rmax_um'];near=settings['near_um'];grid=np.arange(1,round(cap/settings['step_um'])+1)*settings['step_um']
    obs=observed.distance_um.to_numpy();oc=(obs[:,None]<=grid).sum(axis=0);bc=np.array([(base<=r).sum() for r in grid]);M=len(base)
    obs_num=max(0,int((oc*M-bc*N).max()));rng=np.random.default_rng(settings['seed'])
    sim_counts=np.empty((B,len(grid)),np.int32);means=np.empty(B);nears=np.empty(B,np.int32);first=None
    for start in range(0,B,128):
        check_cancel(job);indices=valid[rng.integers(M,size=(min(128,B-start),N))];dd=D.ravel()[indices]
        n=len(dd);sim_counts[start:start+n]=(dd[:,:,None]<=grid).sum(axis=1);means[start:start+n]=np.minimum(cap,dd).mean(axis=1);nears[start:start+n]=(dd<=near).sum(axis=1)
        if first is None:first=np.column_stack(np.unravel_index(indices[0],C.shape))
    nums=np.maximum(0,(sim_counts*M-bc*N).max(axis=1));critical=int(np.partition(nums,int(math.ceil(.95*(B+1)))-1)[int(math.ceil(.95*(B+1)))-1])
    supported=bool((obs>0).all());count=int((obs<=near).sum());pnear=float((base<=near).mean());mean=float(np.minimum(cap,obs).mean());refmean=float(np.minimum(cap,base).mean())
    emit('Generating uniform position reference…');uniform,method=evenly_spread(domain,N);check_cancel(job)
    uf=measure(uniform,D,d['s'],cap,ids=[f'U{k+1:04d}' for k in range(N)]);rf=measure(first,D,d['s'],cap,ids=[f'R{k+1:04d}' for k in range(N)])
    uf.to_csv(out/'tables'/'point_evenly_spread.csv',index=False,encoding='utf-8-sig');rf.to_csv(out/'tables'/'point_random_example.csv',index=False,encoding='utf-8-sig')
    pdict=dict(N=N,M=M,B=B,seed=settings['seed'],supported=supported,zero_ids=observed.loc[observed.distance_um==0,'object_id'].tolist(),
        observed_mean=mean,reference_mean=refmean,reduction_fraction=1-mean/refmean,observed_near=count,expected_near=N*pnear,
        observed_fraction=count/N,reference_fraction=pnear,near_ratio=(count/N/pnear if pnear else None),
        curve_p=float((1+(nums>=obs_num).sum())/(B+1)) if supported else None,
        near_p_exact=float(binom.sf(count-1,N,pnear)) if supported else None,
        mean_p=float((1+(means<=mean).sum())/(B+1)) if supported else None,
        observed_T=obs_num/(N*M),critical=critical/(N*M),all_grid_at_least_reference=bool((oc*M>=bc*N).all()),
        example_kind='point centers, no physical area implied')
    import pandas as pd
    curves=pd.DataFrame(dict(r_um=grid,observed=oc/N,baseline=bc/M,upper=np.minimum(1,bc/M+critical/(N*M))))
    curves.to_csv(out/'tables'/'point_curves.csv',index=False,encoding='utf-8-sig')
    np.savez_compressed(out/'tables'/'point_simulations.npz',counts=sim_counts,statistic=nums/(N*M),mean=means,near=nears,first_yx=first,even_yx=uniform)
    dump(out/'logs'/'point_summary.json',pdict);return pdict,curves


def finite_bank(domain,areas,cats,B,seed,job,probe=None,with_diagnostics=False):
    from acceleration import try_finite_bank
    try:
        accelerated=try_finite_bank(domain,areas,cats,B,seed,job)
        result=accelerated if accelerated is not None else _finite_bank_cpu(domain,areas,cats,B,seed,job)
        info=dict(method='independent whole-layout rejection',approximate=False,count=B,seed=seed if isinstance(seed,list) else int(seed))
    except UserError as error:
        if 'Whole-layout rejection sampling is inefficient' not in str(error):raise
        emit('Dense layout: using approximate independent random-move chains for descriptive equal-area comparisons.')
        from dense_layout import sample
        aa,vv,info=sample(domain,areas,cats,B,seed,job,probe=probe)
        result=(aa,vv)
    return (*result,info) if with_diagnostics else result


def _finite_bank_cpu(domain,areas,cats,B,seed,job):
    import numpy as np
    rng=np.random.default_rng(seed);N=len(areas);total=int(sum(areas));aa=np.empty((B,N),np.int32);vv=np.empty((B,N),np.int8)
    accepted=proposed=0;batch=max(1,min(128,2_000_000//total));width=domain.shape[1]
    while accepted<B:
        check_cancel(job);anchors=np.empty((batch,N),np.int32);variants=np.empty((batch,N),np.int8);flat=np.empty((batch,total),np.int32);offset=0
        for j,area in enumerate(areas):
            cat=cats[int(area)];choice=rng.integers(cat['cumulative'][-1],size=batch);which=np.searchsorted(cat['cumulative'],choice,side='right')
            variants[:,j]=which
            for k,v in enumerate(cat['variants']):
                rows=which==k;ii=choice[rows]-(cat['cumulative'][k-1] if k else 0)
                anchors[rows,j]=v['anchors'][ii];flat[rows,offset:offset+area]=anchors[rows,j,None]+v['linear']
            offset+=area
        good=np.flatnonzero((np.diff(np.sort(flat,axis=1),axis=1)>0).all(axis=1))[:B-accepted]
        n=len(good);aa[accepted:accepted+n]=anchors[good];vv[accepted:accepted+n]=variants[good];accepted+=n;proposed+=batch
        if (proposed>=1024 and accepted==0) or proposed>B*200:raise UserError('Whole-layout rejection sampling is inefficient at this density. Center-model results are retained; equal-area controls were not generated.')
    return aa,vv


def finite_measure(anchors,variants,areas,cats,D,scale,cap,prefix):
    import numpy as np
    labels=np.zeros(D.shape,np.int32);points=[]
    for j,(a,v,area) in enumerate(zip(anchors,variants,areas)):
        y,x=divmod(int(a),D.shape[1]);offset=cats[int(area)]['variants'][int(v)]['offsets'];yy,xx=(offset+[y,x]).T
        if (labels[yy,xx]>0).any():raise UserError('Control regions overlap.')
        labels[yy,xx]=j+1;points.append([yy.mean(),xx.mean()])
    return labels,measure(points,D,scale,cap,areas,[f'{prefix}{j+1:04d}' for j in range(len(points))])


def finite_model(d,observed,settings,job,out,observed_labels):
    import numpy as np
    import pandas as pd
    from PIL import Image
    from area_redistribution21 import catalogue
    from analyze_review21 import evenly_spread
    if not settings.get('finite',True):return dict(available=False,reason='Equal-area design controls were not selected for this case.')
    total=int(observed.area_px.sum());N=len(observed);K=settings.get('control_count') or N;cap_area=math.floor(.75*observed.area_px.max())
    areas=np.full(K,total//K,int);areas[:total%K]+=1
    if areas.min()<1 or areas.max()>cap_area:return dict(available=False,reason='The current control count cannot preserve integer-pixel total area while satisfying the 75% maximum-area cap. The center model remains available. Set a different count explicitly in a new case if needed.')
    domain=d['W']&~d['C'];cats=catalogue(domain,areas);B=settings['B'];cap=settings['rmax_um'];near=settings['near_um']
    emit('Generating independent equal-area reference and random layouts…')
    probe=np.minimum(cap,d['D'])
    ca,cv,calibration_sampling=finite_bank(domain,areas,cats,B,settings['seed']+1001,job,probe=probe,with_diagnostics=True)
    aa,vv,evaluation_sampling=finite_bank(domain,areas,cats,B,settings['seed']+1002,job,probe=probe,with_diagnostics=True)
    def distances(anchors,variants):
        idx=anchors.copy()
        for j,area in enumerate(areas):
            for k,v in enumerate(cats[int(area)]['variants']):
                shift=np.floor(v['offsets'].mean(axis=0)+.5).astype(int);rows=variants[:,j]==k
                idx[rows,j]+=int(shift[0])*d['C'].shape[1]+int(shift[1])
        return d['D'].ravel()[idx]
    cd=distances(ca,cv);sd=distances(aa,vv);grid=np.arange(1,round(cap/settings['step_um'])+1)*settings['step_um']
    bc=(cd[:,:,None]<=grid).sum(axis=1).sum(axis=0);counts=(sd[:,:,None]<=grid).sum(axis=1)
    oc=(observed.distance_um.to_numpy()[:,None]<=grid).sum(axis=0);obsnum=max(0,int((oc*K*B-bc*N).max()));nums=np.maximum(0,(counts*N*B-bc*N).max(axis=1));denom=N*K*B
    means=np.minimum(cap,sd).mean(axis=1);nears=(sd<=near).sum(axis=1)
    diag=[];mapping=pd.read_csv(out/'reviewed'/'tables'/'reviewed_label_mapping.csv').set_index('object_id')
    gray=np.array(Image.open(out/'reviewed'/'masks'/'1_inclusion_labels.tif'))
    for j,r in observed.iterrows():
        mask=observed_labels==j+1;qy,qx=int(r.grid_y_px),int(r.grid_x_px)
        fit={str(area):any(v['valid'][qy,qx] for v in cat['variants']) for area,cat in cats.items()}
        overlap=mask&d['C'];ids=mapping.index[(mapping.kind=='gray')&mapping.reviewed_native_label.isin(np.unique(gray[overlap]))].tolist()
        diag.append(dict(object_id=r.object_id,area_px=int(r.area_px),overlap_dark_px=int(overlap.sum()),dark_ids=' / '.join(ids),
                         outside_W_px=int((mask&~d['W']).sum()),fits_any_standard=any(fit.values())))
    diagnostic=pd.DataFrame(diag);diagnostic.to_csv(out/'tables'/'boundary_audit.csv',index=False,encoding='utf-8-sig')
    common=np.logical_and.reduce([v['valid'] for c in cats.values() for v in c['variants']]);uniform,method=evenly_spread(common,K);check_cancel(job)
    ua=uniform[:,0].astype(int)*d['C'].shape[1]+uniform[:,1].astype(int);uv=np.zeros(K,int)
    even_labels,even=finite_measure(ua,uv,areas,cats,d['D'],d['s'],cap,'U')
    random_labels,example=finite_measure(aa[0],vv[0],areas,cats,d['D'],d['s'],cap,'R')
    for name,lab in [('even',even_labels),('random',random_labels)]:
        if not domain[lab>0].all() or (lab>0).sum()!=total:raise UserError('Equal-area pixel constraints failed.')
        Image.fromarray(lab).save(out/'masks'/f'{name}_labels.tif',compression='tiff_deflate')
    even.to_csv(out/'tables'/'02_even_distances.csv',index=False,encoding='utf-8-sig');example.to_csv(out/'tables'/'03_random_distances.csv',index=False,encoding='utf-8-sig')
    critical=float(np.partition(nums,int(math.ceil(.95*(B+1)))-1)[int(math.ceil(.95*(B+1)))-1]/denom)
    curves=pd.DataFrame(dict(r_um=grid,observed=oc/N,baseline=bc/(K*B),upper=np.minimum(1,bc/(K*B)+critical),
         even=[(even.distance_um<=r).mean() for r in grid],random_example=[(example.distance_um<=r).mean() for r in grid]))
    curves.to_csv(out/'tables'/'area_curves.csv',index=False,encoding='utf-8-sig')
    same_count=K==N;approximate=calibration_sampling['approximate'] or evaluation_sampling['approximate']
    result=dict(available=True,N=K,observed_N=N,total_area_px=total,cap_area_px=cap_area,areas=areas.tolist(),
        observed_mean=float(observed.distance_capped_um.mean()),reference_mean=float(np.minimum(cap,cd).mean()),
        even_mean=float(even.distance_capped_um.mean()),random_example_mean=float(example.distance_capped_um.mean()),
        expected_near=float((cd<=near).sum(axis=1).mean()),incompatible_ids=diagnostic.loc[~diagnostic.fits_any_standard,'object_id'].tolist(),
        actual_overlap_ids=diagnostic.loc[diagnostic.overlap_dark_px>0,'object_id'].tolist(),
        curve_tail=float((1+(nums>=obsnum).sum())/(B+1)) if same_count and not approximate else None,
        mean_tail=float((1+(means<=observed.distance_capped_um.mean()).sum())/(B+1)) if same_count and not approximate else None,
        same_count=same_count,interpretation='Equal-area design comparison; physical assumptions and support require separate interpretation',
        random_seed=settings['seed']+1002,calibration_seed=settings['seed']+1001,approximate_sampling=approximate,
        sampling=dict(calibration=calibration_sampling,evaluation=evaluation_sampling))
    np.savez_compressed(out/'tables'/'area_simulations.npz',anchors=aa,variants=vv,areas=areas,counts=counts,mean=means,near=nears,statistic=nums/denom,reference_counts=bc)
    dump(out/'logs'/'footprints.json',{str(a):[v['offsets'].tolist() for v in c['variants']] for a,c in cats.items()})
    dump(out/'logs'/'area_summary.json',result);return result


def analyze(case,confirmed_revision,human_review=True):
    from acceleration import new_job
    new_job()
    import numpy as np
    import pandas as pd
    from PIL import Image
    from apply_review21 import replay
    case=Path(case).resolve();meta=load(case/'case.json');cfg=load(case/'config.json')
    if hashlib.sha256((case/'config.json').read_bytes()).hexdigest()!=meta['config_sha256']:raise UserError('The parameter file was edited after import. Reimport as a new case to keep scale, window and review consistent.')
    cfg['analysis'].setdefault('size_guard_um',1)
    from plot_settings import read_settings
    presentation=read_settings(case)
    review_path=case/'report'/'review_annotations'/'review_annotations.json';review=load(review_path)
    if int(confirmed_revision)!=review['revision']:raise UserError('The saved review revision changed. Check and confirm the latest revision before generating a report.')
    review['human_review_confirmed']=bool(human_review)
    with analysis_lock(case):
        job=tempdir(case/'_tmp','run');configure_temp(job/'_runtime')
        try:
            for name in ['inputs','reviewed/masks','reviewed/tables','reviewed/logs','masks','tables','figures','report','logs']:(job/name).mkdir(parents=True,exist_ok=True)
            dump(job/'inputs'/'review.json',review);dump(job/'inputs'/'case.json',meta);dump(job/'inputs'/'config.json',cfg)
            dump(job/'inputs'/'plot_settings.json',presentation)
            emit('Applying saved outlines and checking eligible objects…',job=str(job))
            try:d=replay(job/'inputs'/'review.json',job/'reviewed','1',project_root=case)
            except ValueError as e:raise UserError(str(e).replace('Overlapping bright objects require resolution:','Bright outlines overlap. Remove duplicates or redraw and save on the review page: ').replace('No usable objects','No eligible objects. Add and save bright / dark outlines on the review page first'))
            if d['table'].empty:raise UserError('No eligible objects. Add and save bright / dark outlines on the review page first.')
            b=d['table'].loc[(d['table'].kind=='bright')&d['table'].included]
            a=cfg['analysis'];observed=measure(b[['centroid_y_px','centroid_x_px']].to_numpy(),d['D'],d['s'],a['rmax_um'],b.area_px.to_numpy(),b.object_id.tolist())
            if not d['C'].any():observed[['distance_um','distance_capped_um']]=np.nan
            observed.to_csv(job/'tables'/'01_observed_distances.csv',index=False,encoding='utf-8-sig')
            labels=np.array(Image.open(job/'reviewed'/'masks'/'1_bright_labels.tif'));mapping=pd.read_csv(job/'reviewed'/'tables'/'reviewed_label_mapping.csv').set_index('object_id')
            obs_labels=np.zeros(labels.shape,np.int32)
            for j,oid in enumerate(observed.object_id):obs_labels[labels==int(mapping.loc[oid,'reviewed_native_label'])]=j+1
            Image.fromarray(obs_labels).save(job/'masks'/'observed_labels.tif',compression='tiff_deflate')
            for name in ['A','W','C']:Image.fromarray(d[name].astype(np.uint8)*255).save(job/'masks'/f'{name}.png')
            emit('Measuring complete grains inside the grain-size window…')
            from grain_size_analysis import measure_grains,build_grain_report
            grain=measure_grains(d,job);spatial_available=bool(len(b) and d['C'].any() and a.get('mode','full')=='full')
            if spatial_available:
                emit('Running center-position null-hypothesis tests (4999 simulations)…');point,curves=point_model(d,observed,a,job,job)
                check_cancel(job)
                try:area=finite_model(d,observed,a,job,job,obs_labels)
                except (UserError,ValueError) as e:area=dict(available=False,reason=str(e))
                check_cancel(job);dump(job/'logs'/'area_summary.json',area)
                emit('Exporting separate scientific figures, methods and reports…')
                from self_service_report import build_report
                build_report(case,job,d,observed,point,area,review)
            else:dump(job/'logs'/'spatial_status.json',dict(available=False,reason='Grain-size-only mode, or no bright objects / dark targets in W. Grain-size results are provided; no distance test was generated.'))
            build_grain_report(case,job,d,grain,review,spatial_available)
            from acceleration import report as acceleration_report
            dump(job/'logs'/'compute_backend.json',acceleration_report())
            if spatial_available:
                html_path=job/'report'/'Report.html';content=html_path.read_text(encoding='utf-8');content=content.replace('<h1>','<p><a href="Grain_Size_Report.html">Open gold / chalcopyrite grain-size report</a></p><h1>',1);html_path.write_text(content,encoding='utf-8')
            for filename in ['dense_layout.py','acceleration.py','app_runtime.py','responsive_ui.py','grain_size_analysis.py','plot_settings.py','exclusion_geometry.py','review_exclusions.js','self_service_engine.py','segmentation.py','bright_segmentation.py','apply_review21.py','self_service_report.py','review21_display.py','publication21_figures.py','audit_pdf_text.py','audit_figure_collisions.py','audit_panel_alignment.py']:
                (job/'code').mkdir(exist_ok=True);shutil.copyfile(ROOT/'code'/filename,job/'code'/filename)
            with __import__('zipfile').ZipFile(job/'Export.zip','w',__import__('zipfile').ZIP_DEFLATED) as bundle:
                for file in job.rglob('*'):
                    if file.is_file() and file.name!='Export.zip' and file.name!='.temporary-owner.json' and '_runtime' not in file.relative_to(job).parts:bundle.write(file,file.relative_to(job))
            check_cancel(job)
            stamp='r'+str(review['revision']).zfill(4)+'_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:4]
            dest=case/'results'/stamp
            safe_runtime=job/'_runtime'
            if safe_runtime.exists():_remove_owned_tree(within(safe_runtime,job))
            # A complete report is published only after verification; previous reports remain intact.
            job.rename(dest);(dest/'.temporary-owner.json').unlink()
            current=load(review_path);latest=dict(run=stamp,review_revision=review['revision'],current_saved_revision=current['revision'],report=str(dest/'report'/('Report.html' if spatial_available else 'Grain_Size_Report.html')),grain_report=str(dest/'report'/'Grain_Size_Report.html'),human_review_confirmed=bool(human_review),created=datetime.now().astimezone().isoformat())
            latest['plot_settings']=presentation
            dump(case/'latest_report.json',latest)
            for filename,target in [('打开最新报告.html',latest['report']),('粒径报告.html',latest['grain_report'])]:
                relative=Path(target).relative_to(case).as_posix();(case/filename).write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url='+relative+'"><a href="'+relative+'">Open report</a>',encoding='utf-8')
            emit('Report saved.' if current['revision']==review['revision'] else 'The report was generated, but a newer review was saved afterward. Generate again to include those changes.',event='complete',case=str(case),report=latest['report'],revision=review['revision'])
            return dest
        except Exception as error:
            if not isinstance(error,Cancelled) and job.exists():
                failure=case/'logs'/('failed_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:4]);failure.mkdir()
                dump(failure/'error.json',dict(error=str(error),review_revision=review['revision']))
                if (job/'inputs'/'review.json').exists():shutil.copyfile(job/'inputs'/'review.json',failure/'review.json')
                for folder in [job/'logs',job/'reviewed'/'logs']:
                    if folder.exists():
                        dest=failure/('figures' if folder==job/'logs' else 'application');dest.mkdir(exist_ok=True)
                        for file in folder.iterdir():
                            if file.is_file():shutil.copyfile(file,dest/file.name)
                overlap=job/'reviewed'/'tables'/'review_overlap_checks.csv'
                if overlap.exists():shutil.copyfile(overlap,failure/'overlaps.csv')
            raise
        finally:
            if job.exists() and (job/'.temporary-owner.json').exists():safe_remove(job,case/'_tmp')


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['import','analyze','analyze-batch','summarize','replot-summary','enhance-bright']);p.add_argument('--spec',type=Path);p.add_argument('--case',type=Path);p.add_argument('--selection',type=Path);p.add_argument('--cancel-file',type=Path)
    p.add_argument('--cases-root',type=Path,default=CASES);p.add_argument('--confirmed-revision',type=int,default=-1);p.add_argument('--candidate',action='store_true')
    args=p.parse_args()
    try:
        if args.action=='import':
            case=import_image(load(args.spec),args.cases_root);emit('Image imported. Open the review page, check candidates and save.',event='complete',case=str(case))
        elif args.action=='analyze':analyze(within(args.case,args.cases_root),args.confirmed_revision,not args.candidate)
        elif args.action=='analyze-batch':
            names=load(args.selection).get('cases',[])
            if not names:raise UserError('No cases available for analysis.')
            original_emit=emit
            def batch_emit(message,**extra):
                if extra.get('event')=='complete':extra['batch_item']=True
                original_emit(message,**extra)
            globals()['emit']=batch_emit;completed=[]
            try:
                for index,name in enumerate(names,1):
                    if args.cancel_file and args.cancel_file.exists():raise Cancelled('Remaining batch tasks stopped. Completed reports are retained.')
                    case=within(args.cases_root/name,args.cases_root);review=load(case/'report/review_annotations/review_annotations.json')
                    original_emit(f'Batch candidate analysis {index}/{len(names)}：'+load(case/'case.json')['name'])
                    completed.append(str(analyze(case,review['revision'],human_review=False)))
            finally:globals()['emit']=original_emit
            from acceleration import report as compute_report
            dump(ROOT/'logs/batch_analysis_last.json',dict(worker_pid=os.getpid(),results=completed,compute_process_reused=True,gpu_context_reused=len(completed)>1 and compute_report()['gpu_initializations']==1))
            emit(f'Completed {len(completed)} candidate cases in one shared compute process.',event='complete',case=str(case),batch_finished=True)
        elif args.action=='enhance-bright':
            from enhance_bright_case import enhance_case
            case=enhance_case(within(args.case,args.cases_root),load(args.spec) if args.spec else {},args.cases_root)
            emit('Enhanced bright-grain copy saved with manual edits retained. Review new candidates before generating a report.',event='complete',case=str(case),open_review=True)
        elif args.action=='summarize':
            from batch_summary import build_summary
            build_summary(load(args.selection),validate_output_root(args.cases_root))
        else:
            from batch_summary import build_summary
            root=validate_output_root(args.cases_root);frozen=within(Path(load(root/'汇总报告'/'latest_summary.json')['report']).parent,root)
            if not (frozen/'inputs'/'selection.json').exists():raise UserError('Latest summary folder moved or deleted. Select cases and export again; saved outlines are retained.')
            build_summary(load(frozen/'inputs'/'selection.json'),root,frozen_summary=frozen)
    except Exception as e:
        directory=args.case/'logs' if args.case else ROOT/'logs';directory.mkdir(parents=True,exist_ok=True)
        (directory/'self_service_last_error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        print(json.dumps(dict(event='error',message=error_message(e),log=str(directory/'self_service_last_error.txt')),ensure_ascii=False),flush=True)
        raise SystemExit(1)


if __name__=='__main__':main()
