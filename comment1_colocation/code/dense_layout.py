"""Approximate hard-core layouts via independent random-move chains.

Each move selects one region and proposes uniformly from its fixed catalogue.
Rejected moves retain the old state. Thus the uniform distribution over valid
labelled configurations is stationary; finite-run convergence is not assumed.
These layouts are descriptive controls, never exact Monte Carlo p-values.
"""
import time
import numpy as np


def sample(domain, areas, cats, count, seed, job, probe=None, sweeps=12, batch_size=64):
    from self_service_engine import check_cancel, UserError
    started=time.perf_counter();areas=np.asarray(areas,dtype=np.int32);n=len(areas)
    if n==0 or count<1 or sweeps<2:raise UserError('Invalid dense-layout sampling request.')
    rng=np.random.default_rng(seed);size=domain.size
    anchors=np.empty((count,n),np.int32);variants=np.empty((count,n),np.int8)
    half=np.empty(count,float);end=np.empty(count,float);accepts=attempts=initial_attempts=0
    # Proposal catalogue is identical to the existing whole-layout sampler.
    def proposal(area,k):
        cat=cats[int(area)];choice=rng.integers(int(cat['cumulative'][-1]),size=k)
        vv=np.searchsorted(cat['cumulative'],choice,side='right').astype(np.int8)
        aa=np.empty(k,np.int32);pixels=np.empty((k,int(area)),np.int32)
        for v,shape in enumerate(cat['variants']):
            sel=np.flatnonzero(vv==v)
            if not len(sel):continue
            prev=int(cat['cumulative'][v-1]) if v else 0
            aa[sel]=shape['anchors'][choice[sel]-prev]
            pixels[sel]=aa[sel,None]+shape['linear']
        return aa,vv,pixels
    def old_pixels(aa,vv,area):
        pixels=np.empty((len(aa),int(area)),np.int32)
        for v,shape in enumerate(cats[int(area)]['variants']):
            sel=np.flatnonzero(vv==v)
            if len(sel):pixels[sel]=aa[sel,None]+shape['linear']
        return pixels
    def metric(aa,vv):
        if probe is None:return aa.mean(axis=1)/size
        values=np.zeros(len(aa),float);flat=np.asarray(probe).ravel();w=domain.shape[1]
        for j,area in enumerate(areas):
            index=aa[:,j].copy()
            for v,shape in enumerate(cats[int(area)]['variants']):
                shift=np.floor(shape['offsets'].mean(axis=0)+.5).astype(int)
                index[vv[:,j]==v]+=int(shift[0])*w+int(shift[1])
            values+=flat[index]
        return values/n
    for start in range(0,count,batch_size):
        check_cancel(job);k=min(batch_size,count-start);rows=np.arange(k);occ=np.zeros((k,size),np.uint8)
        aa=np.empty((k,n),np.int32);vv=np.empty((k,n),np.int8)
        # Feasible starting layouts are generated sequentially, then equilibrated.
        for j in rng.permutation(n):
            pending=rows.copy();rounds=0
            while len(pending):
                rounds+=1;initial_attempts+=len(pending)
                if rounds%25==0:check_cancel(job)
                if rounds>10000:raise UserError('Dense-layout initialization could not find a non-overlapping placement; the equal-area model is unavailable.')
                a,v,p=proposal(areas[j],len(pending));good=~occ[pending[:,None],p].any(axis=1)
                selected=pending[good];occ[selected[:,None],p[good]]=1;aa[selected,j]=a[good];vv[selected,j]=v[good];pending=pending[~good]
        for sweep in range(sweeps):
            check_cancel(job)
            for j in rng.permutation(n):
                previous=old_pixels(aa[:,j],vv[:,j],areas[j]);occ[rows[:,None],previous]=0
                a,v,p=proposal(areas[j],k);good=~occ[rows[:,None],p].any(axis=1)
                occ[rows[:,None],previous]=1
                selected=rows[good]
                if len(selected):
                    occ[selected[:,None],previous[good]]=0;occ[selected[:,None],p[good]]=1
                    aa[selected,j]=a[good];vv[selected,j]=v[good]
                accepts+=int(good.sum());attempts+=k
            if sweep+1==sweeps//2:half[start:start+k]=metric(aa,vv)
        end[start:start+k]=metric(aa,vv);anchors[start:start+k]=aa;variants[start:start+k]=vv
    delta=end-half;se=float(delta.std(ddof=1)/np.sqrt(count)) if count>1 else None
    z=float(abs(delta.mean())/se) if se and se>0 else None
    info=dict(method='independent initialized hard-core random-move chains',approximate=True,
        target='uniform over non-overlapping labelled catalogue placements, conditional on admissibility',
        count=count,seed=seed if isinstance(seed,list) else int(seed),sweeps=sweeps,initial_proposals=int(initial_attempts),
        backend='CPU NumPy',move_acceptance=float(accepts/max(attempts,1)),half_vs_final_probe_mean_change=float(delta.mean()),
        half_vs_final_probe_standard_error=se,half_vs_final_probe_z=z,diagnostic_probe='mean capped distance' if probe is not None else 'mean flattened anchor index',
        diagnostic_note='Half-vs-final compares sampled capped-distance summaries; approximate layouts provide descriptive comparisons.',
        seconds=time.perf_counter()-started)
    return anchors,variants,info
