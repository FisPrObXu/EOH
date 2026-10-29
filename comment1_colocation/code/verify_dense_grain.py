"""Reproducible statistical checks for dense layouts and sample bootstrap."""
from pathlib import Path
import numpy as np
import pandas as pd
from area_redistribution21 import catalogue
from dense_layout import sample
from grain_size_analysis import sample_bootstrap


def main():
    # Exact enumeration on a small lattice checks the target distribution,
    # not merely the sampler's own implementation.
    domain=np.ones((4,4),bool);areas=np.array([2,2]);cats=catalogue(domain,areas)
    placements=[]
    for v,shape in enumerate(cats[2]['variants']):
        for anchor in shape['anchors']:placements.append((int(anchor),v,set((int(anchor)+shape['linear']).tolist())))
    exact=np.zeros(domain.size)
    for a,_,pa in placements:
        for _,_,pb in placements:
            if pa.isdisjoint(pb):exact[a]+=1
    exact/=exact.sum()
    anchors,variants,diag=sample(domain,areas,cats,8000,354,Path(__file__).parent,sweeps=12,batch_size=64)
    empirical=np.bincount(anchors[:,0],minlength=domain.size)/len(anchors)
    tv=float(abs(exact-empirical).sum()/2)
    assert tv<.07,(tv,diag)
    for aa,vv in zip(anchors,variants):
        pixels=[]
        for j in range(len(areas)):pixels.extend((int(aa[j])+cats[2]['variants'][int(vv[j])]['linear']).tolist())
        assert len(pixels)==len(set(pixels)) and domain.ravel()[pixels].all()
    assert diag['approximate'] and diag['count']==8000
    # Two images in one sample must be resampled as one cluster.
    frame=pd.DataFrame(dict(case_code=['A','A','B','C','D'],equivalent_circle_diameter_um=[1.,2.,1.,3.,4.],area_um2=[1.,4.,1.,9.,16.]))
    info=dict(case_samples=dict(A='s1',B='s1',C='s2',D='s3'),sample_ids=['s1','s2','s3'],bootstrap_replicates=2000)
    grid=np.array([0.,1.,2.,3.,4.]);seed=109
    for weighting in ['count','area']:
        result,n=sample_bootstrap(frame,grid,info,weighting,seed);rng=np.random.default_rng(seed)
        groups=[frame[frame.case_code.isin(codes)] for codes in [('A','B'),('C',),('D',)]];draws=[]
        for choice in rng.integers(0,3,size=(2000,3)):
            selected=pd.concat([groups[i] for i in choice]);weights=np.ones(len(selected)) if weighting=='count' else selected.area_um2.to_numpy()
            values=selected.equivalent_circle_diameter_um.to_numpy();draws.append([weights[values<=x].sum()/weights.sum() for x in grid])
        expected=np.quantile(draws,[.025,.975],axis=0)
        assert n==2000 and np.allclose(result,expected)
    print(f'PASS: small-lattice total variation {tv:.4f}; all layouts non-overlapping; clustered count and area bootstrap match an independent calculation')


if __name__=='__main__':main()
