"""Optional CUDA layouts with exact CPU tie handling and fixed NumPy RNG draws."""
import os
import time
from pathlib import Path
import numpy as np

_cp=None
_checked=False
_events=[]
_device='CPU'
_initializations=0


def new_job():
    _events.clear()


def virtual_headers(compiler,root):
    """NVRTC virtual headers support Windows folders containing Chinese names."""
    root=Path(root);io_root=Path('\\\\?\\'+str(root.resolve())) if os.name=='nt' else root
    roots=[io_root,io_root/'cupy/_cccl/libcudacxx',io_root/'cupy/_cccl/thrust',io_root/'cupy/_cccl/cub',io_root/'cupy/_cuda']
    sources={}
    for file in io_root.rglob('*'):
        if not file.is_file():continue
        content=None
        for base in roots:
            if file.is_relative_to(base):
                if content is None:content=file.read_text(encoding='utf-8',errors='replace')
                sources[file.relative_to(base).as_posix()]=content
    original_init=compiler._NVRTCProgram.__init__
    def init(self,src,name='default_program',headers=(),include_names=(),name_expressions=None,method='ptx'):
        if not src.strip():return original_init(self,src,name,headers,include_names,name_expressions,method)
        combined=dict(sources);combined.update((n.decode() if isinstance(n,bytes) else n,h) for n,h in zip(include_names,headers))
        return original_init(self,src,name,tuple(v.encode('utf-8') if isinstance(v,str) else v for v in combined.values()),tuple(n.encode('utf-8') for n in combined),name_expressions,method)
    compiler._NVRTCProgram.__init__=init
    return len(sources)


def report():
    return dict(requested=os.environ.get('BSE_COMPUTE_BACKEND','auto'),device=_device,worker_pid=os.getpid(),gpu_initializations=_initializations,events=list(_events))


def gpu():
    global _cp,_checked,_device,_initializations
    if os.environ.get('BSE_COMPUTE_BACKEND','auto')=='cpu':return None
    if _checked:return _cp
    _checked=True
    try:
        os.environ.setdefault('CUPY_CACHE_IN_MEMORY','1')
        from app_runtime import ROOT
        os.environ.setdefault('CUDA_CACHE_PATH',str(ROOT/'_tmp'/'cuda_cache'))
        import cupy as cp
        if cp.cuda.runtime.getDeviceCount()<1:return None
        from cupy.cuda import compiler
        compile_nvrtc=compiler.compile_using_nvrtc
        # Float32/64 and integer kernels only: avoid incompatible optional half
        # headers in the installed CUDA/CCCL combination. No installed file changes.
        def compatible(source,options=(),*args,**kwargs):
            options=tuple(v for v in options if not v.startswith(('-std=','--std=')))+('--std=c++17','-DCCCL_DISABLE_FP16_SUPPORT','-DCCCL_DISABLE_BF16_SUPPORT')
            return compile_nvrtc(source,options,*args,**kwargs)
        compiler.compile_using_nvrtc=compatible
        headers=Path(cp.__file__).parent/'_core'/'include'
        if os.name=='nt' and not str(headers).isascii():
            count=virtual_headers(compiler,headers);_events.append(dict(operation='virtual_cuda_headers',backend='NVRTC',headers=count))
        cp.zeros(1,dtype=cp.int32);cp.cuda.Stream.null.synchronize()
        name=cp.cuda.runtime.getDeviceProperties(0)['name'];_device=name.decode() if isinstance(name,bytes) else str(name)
        _cp=cp
        _initializations+=1
    except Exception as error:_events.append(dict(operation='initialize',backend='CPU',reason=str(error)))
    return _cp


def try_evenly_spread(W,N):
    cp=gpu()
    if cp is None:return None
    started=time.perf_counter()
    try:
        from scipy.spatial import cKDTree
        pixels=np.column_stack(np.where(W)).astype(float)
        coords=cp.asarray(pixels,dtype=cp.int32);mean=pixels.mean(axis=0)
        first=int(np.argmin(((pixels-mean)**2).sum(axis=1)))
        selected=[pixels[first]];nearest=((coords-cp.asarray(selected[0],dtype=cp.int32))**2).sum(axis=1)
        for _ in range(1,N):
            selected.append(pixels[int(cp.argmax(nearest).get())])
            nearest=cp.minimum(nearest,((coords-cp.asarray(selected[-1],dtype=cp.int32))**2).sum(axis=1))
        centers=np.array(selected);tree=cKDTree(pixels);iterations=0
        kernel=cp.RawKernel(r'''
        extern "C" __global__ void nearest_center(const int* xy,const int* c,int P,int N,int* group,unsigned char* tied){
          int p=blockDim.x*blockIdx.x+threadIdx.x;if(p>=P)return;
          int y=xy[2*p],x=xy[2*p+1],best=2147483647,which=0;unsigned char tie=0;
          for(int j=0;j<N;j++){int dy=y-c[2*j],dx=x-c[2*j+1],d=dy*dy+dx*dx;
            if(d<best){best=d;which=j;tie=0;}else if(d==best){tie=1;}}
          group[p]=which;tied[p]=tie;
        }''','nearest_center')
        groups=cp.empty(len(pixels),dtype=cp.int32);ties=cp.empty(len(pixels),dtype=cp.uint8)
        for k in range(80):
            kernel(((len(pixels)+255)//256,),(256,),(coords,cp.asarray(centers,dtype=cp.int32),np.int32(len(pixels)),np.int32(N),groups,ties))
            tied=cp.flatnonzero(ties).get()
            # cKDTree's equal-distance choice is implementation-specific. Resolve
            # just those pixels with the original CPU tree for identical layouts.
            if len(tied):groups[cp.asarray(tied)]=cp.asarray(cKDTree(centers).query(pixels[tied])[1],dtype=cp.int32)
            count=cp.bincount(groups,minlength=N).get();new=centers.copy();nonempty=count>0
            for axis in range(2):
                sums=cp.bincount(groups,weights=coords[:,axis].astype(cp.float64),minlength=N).get()
                new[nonempty,axis]=sums[nonempty]/count[nonempty]
            _,near=tree.query(new,k=min(N,len(pixels)));near=np.asarray(near).reshape(N,-1)
            used=set();projected=[]
            for options in near:
                index=next(int(x) for x in options if int(x) not in used);used.add(index);projected.append(pixels[index])
            projected=np.array(projected);iterations=k+1
            if np.array_equal(projected,centers):break
            centers=projected
        cp.cuda.Stream.null.synchronize()
        _events.append(dict(operation='evenly_spread',backend='CUDA',seconds=time.perf_counter()-started,particles=N,pixels=len(pixels)))
        return centers,dict(iterations=iterations,method='Deterministic centroidal coverage (farthest-point start, Voronoi centroid relaxation, projection into W)',
                            target_regions_used_for_placement=False,interpretation='Illustrative evenly spread arrangement; not a sample from the independent uniform null',compute_backend='CUDA; CPU cKDTree tie handling')
    except Exception as error:
        _events.append(dict(operation='evenly_spread',backend='CPU fallback',reason=str(error)));return None


def try_finite_bank(domain,areas,cats,B,seed,job):
    cp=gpu()
    if cp is None:return None
    started=time.perf_counter()
    from self_service_engine import check_cancel,Cancelled,UserError
    try:
        areas=np.asarray(areas,dtype=np.int32);N=len(areas);total=int(areas.sum());batch=max(1,min(128,2_000_000//total))
        keys=sorted(cats);object_type=np.array([keys.index(int(a)) for a in areas],np.int32)
        anchor_base=[];anchor_data=[];cumulative=[];variant_start=[];variant_count=[];linear_base=[];linear_data=[];anchor_size=linear_size=0
        for key in keys:
            cat=cats[key];anchor_base.append(anchor_size);variant_start.append(len(cumulative));variant_count.append(len(cat['variants']))
            cumulative.extend(cat['cumulative'].tolist())
            for variant in cat['variants']:
                anchor_data.append(variant['anchors']);anchor_size+=len(variant['anchors']);linear_base.append(linear_size);linear_data.append(variant['linear']);linear_size+=len(variant['linear'])
        packed=[cp.asarray(v,dtype=cp.int32) for v in [object_type,areas,np.r_[0,np.cumsum(areas)[:-1]],anchor_base,np.concatenate(anchor_data),variant_start,variant_count,cumulative,linear_base,np.concatenate(linear_data)]]
        kernel=cp.RawKernel(r'''
        extern "C" __global__ void proposals(const long long* choice,const int* type,const int* area,const int* offset,
          const int* abase,const int* anchors,const int* vstart,const int* vcount,const int* cumulative,const int* lbase,const int* linear,
          int batch,int N,int total,int* aa,signed char* vv,int* flat){
          int pos=blockDim.x*blockIdx.x+threadIdx.x;if(pos>=batch*N)return;
          int row=pos/N,j=pos%N,t=type[j],vs=vstart[t],v=0;long long pick=choice[pos];
          while(v+1<vcount[t] && pick>=cumulative[vs+v])v++;
          int anchor=anchors[abase[t]+pick];aa[pos]=anchor;vv[pos]=(signed char)v;
          for(int p=0;p<area[j];p++)flat[row*total+offset[j]+p]=anchor+linear[lbase[vs+v]+p];
        }''','proposals')
        rng=np.random.default_rng(seed);aa=np.empty((B,N),np.int32);vv=np.empty((B,N),np.int8)
        accepted=proposed=0
        while accepted<B:
            check_cancel(job)
            choices=np.empty((batch,N),np.int64)
            for j,area in enumerate(areas):choices[:,j]=rng.integers(cats[int(area)]['cumulative'][-1],size=batch)
            ga=cp.empty((batch,N),cp.int32);gv=cp.empty((batch,N),cp.int8);flat=cp.empty((batch,total),cp.int32)
            kernel(((batch*N+255)//256,),(256,),(cp.asarray(choices),*packed,np.int32(batch),np.int32(N),np.int32(total),ga,gv,flat))
            good=cp.flatnonzero((cp.diff(cp.sort(flat,axis=1),axis=1)>0).all(axis=1))[:B-accepted]
            host_a=ga[good].get();host_v=gv[good].get();n=len(host_a)
            aa[accepted:accepted+n]=host_a;vv[accepted:accepted+n]=host_v;accepted+=n;proposed+=batch
            if (proposed>=1024 and accepted==0) or proposed>B*200:raise UserError('Whole-layout rejection sampling is inefficient at this density. Center-model results are retained; equal-area controls were not generated.')
        _events.append(dict(operation='finite_bank',backend='CUDA',seconds=time.perf_counter()-started,particles=N,simulations=B,proposals=proposed))
        return aa,vv
    except (Cancelled,UserError):raise
    except Exception as error:
        _events.append(dict(operation='finite_bank',backend='CPU fallback',reason=str(error)));return None
