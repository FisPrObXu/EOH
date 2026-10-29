"""Publication layouts and model-matched controls for descriptive case summaries."""
from collections import defaultdict


def mean_distance_figures(records,out,settings):
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.ticker import MaxNLocator
    from publication21_figures import style,OBS
    from self_service_report import save
    from plot_settings import tag,register_legend
    style();figures=[];rows=[];groups=defaultdict(list)
    for record in records:
        if not record['point']:continue
        with np.load(out/record['copied_case']/'result'/'tables'/'point_simulations.npz') as bank:means=bank['mean']
        lo,hi=np.quantile(means,[.025,.975]);p=record['point']
        row=dict(case_code=record['code'],case_name=record['name'],N=p['N'],cap_um=record['distance_limit_um'],observed_mean_um=p['observed_mean'],
                 random_expected_mean_um=p['reference_mean'],random_mean_q025_um=float(lo),random_mean_q975_um=float(hi),simulations=len(means),mean_p=p['mean_p'])
        rows.append(row);groups[row['cap_um']].append(row)
    pd.DataFrame(rows).to_csv(out/'tables'/'mean_distance_reference.csv',index=False,encoding='utf-8-sig')
    for gi,(cap,group) in enumerate(groups.items(),1):
        for start in range(0,len(group),12):
            block=group[start:start+12];height=max(55,34+7*len(block));fig=plt.figure(figsize=(183/25.4,height/25.4))
            ax=fig.add_axes([.21,18/height,.53,(height-33)/height]);maximum=0
            for y,row in enumerate(block):
                lo,hi=row['random_mean_q025_um'],row['random_mean_q975_um'];expected=row['random_expected_mean_um'];actual=row['observed_mean_um']
                tag(ax.plot([lo,hi],[y,y],color='#8d969c',lw=1.6,solid_capstyle='butt',zorder=2)[0],'upper')
                tag(ax.plot([lo,hi],[y,y],'|',color='#8d969c',ms=4,mew=.8,zorder=2)[0],'upper')
                tag(ax.plot(expected,y,'D',color='#222222',ms=3.5,zorder=3)[0],'baseline')
                tag(ax.plot(actual,y,'o',color=OBS,ms=4,mec='white',mew=.45,zorder=4)[0],'observed')
                tag(ax.text(1.055,y,f'{actual:.3f} / {expected:.3f}',transform=ax.get_yaxis_transform(),va='center',fontsize=7),'mean_values')
                maximum=max(maximum,hi,expected,actual)
            ax.set_yticks(np.arange(len(block)),[f'{r["case_code"]}  (n = {r["N"]})' for r in block])
            ax.set_ylim(len(block)-.5,-.5);ax.set_xlim(0,max(maximum*1.10,.01));ax.xaxis.set_major_locator(MaxNLocator(5))
            ax.set_xlabel('Mean nearest-dark distance (μm)',labelpad=5)
            ax.set_title(f'Mean distance comparison | cap = {cap:g} μm',loc='left',fontsize=8,pad=15)
            tag(ax.text(1.055,1.10,'Observed / Random',transform=ax.transAxes,fontsize=6.5,va='bottom'),'mean_values')
            ax.grid(axis='y',color='#e5e8ea',lw=.4,ls=':',zorder=0);ax.tick_params(axis='y',length=0,pad=8)
            handles=[Line2D([],[],color=OBS,marker='o',ls='',ms=4,label='Observed mean'),Line2D([],[],color='#222222',marker='D',ls='',ms=3.5,label='Random expectation'),Line2D([],[],color='#8d969c',lw=1.6,label='95% random reference range')]
            fig._bse_mean_rows=block
            register_legend(fig,handles=handles,loc='lower left',bbox_to_anchor=(.10,1.2/height),ncol=3,fontsize=6.5,columnspacing=1.8,handlelength=1.7)
            suffix=(f'_G{gi:02d}' if len(groups)>1 else '')+(f'_{start//12+1:02d}' if len(group)>12 else '')
            save(fig,out,'01_Distance_Means'+suffix,figures,'Per-field capped mean distances: observed, random expectation and 95% random reference range')
    return figures


def joint_random_curves(members,model,grid,count,out,group_index):
    """Fresh independent native-domain layouts per field; original tests are untouched."""
    import numpy as np
    from PIL import Image
    from scipy import ndimage as ndi
    from self_service_engine import load,check_cancel,finite_bank,UserError
    from area_redistribution21 import catalogue
    weights=np.array([r['point']['N'] for r in members],float);combined=np.zeros((count,len(grid)),float);arrays={};metadata=[]
    streams=np.random.SeedSequence(20261027,spawn_key=(group_index,0 if model=='point' else 1)).spawn(len(members))
    for record,weight,stream in zip(members,weights,streams):
        check_cancel(out);root=out/record['copied_case']/'result';n=record['point']['N'] if model=='point' else record['area']['N']
        if len(members)==1:
            with np.load(root/'tables'/f'{model}_simulations.npz') as bank:counts=bank['counts'][:count].copy()
            if len(counts)!=count:raise UserError('Insufficient saved random curves.')
            seed=None;method='existing evaluation bank; single field';sampling=record['area'].get('sampling',{}).get('evaluation',{}) if model=='area' else {}
        else:
            seed=stream.generate_state(4).tolist();scale=record['pixel_size_um']
            C=np.array(Image.open(root/'masks'/'C.png'))>0;W=np.array(Image.open(root/'masks'/'W.png'))>0;domain=W&~C
            D=ndi.distance_transform_edt(~C,sampling=(scale,scale));counts=np.empty((count,len(grid)),np.int32)
            if model=='point':
                valid=np.flatnonzero(domain);rng=np.random.default_rng(seed);locations=np.empty((count,n),np.int32)
                for start in range(0,count,128):
                    check_cancel(out);idx=valid[rng.integers(len(valid),size=(min(128,count-start),n))];dd=D.ravel()[idx]
                    locations[start:start+len(idx)]=idx;counts[start:start+len(idx)]=(dd[:,:,None]<=grid).sum(axis=1)
                arrays[record['code']+'_locations_flat']=locations
            else:
                areas=np.asarray(record['area']['areas'],int);cats=catalogue(domain,areas);anchors,variants,sampling=finite_bank(domain,areas,cats,count,seed,out,probe=np.minimum(D,record['distance_limit_um']),with_diagnostics=True)
                if areas.sum()!=record['area']['total_area_px'] or areas.max()>record['area']['cap_area_px']:raise UserError('Pooled equal-area controls violate the original area constraints.')
                idx=anchors.copy()
                # Same native centroid rounding as self_service_engine.finite_model.
                for j,area in enumerate(areas):
                    for k,variant in enumerate(cats[int(area)]['variants']):
                        shift=np.floor(variant['offsets'].mean(axis=0)+.5).astype(int);which=variants[:,j]==k
                        idx[which,j]+=int(shift[0])*C.shape[1]+int(shift[1])
                if not domain.ravel()[idx].all():raise UserError('Pooled equal-area random centers fall outside the allowed domain.')
                for start in range(0,count,128):counts[start:start+128]=(D.ravel()[idx[start:start+128]][:,:,None]<=grid).sum(axis=1)
                arrays[record['code']+'_anchors']=anchors;arrays[record['code']+'_variants']=variants;arrays[record['code']+'_areas']=areas
            method='fresh native-domain layouts; independent SeedSequence child stream'
            if model=='point':sampling={}
        combined+=weight*(counts/n);arrays[record['code']+'_counts']=counts
        metadata.append(dict(case_code=record['code'],particles_per_layout=int(n),observed_weight=int(weight),seed=seed,method=method,sampling=sampling))
    combined/=weights.sum()
    if not np.isfinite(combined).all() or combined.min()<0 or combined.max()>1+1e-12 or (np.diff(combined,axis=1)<-1e-12).any():raise UserError('Pooled random cumulative-fraction validation failed.')
    arrays.update(combined_cdfs=combined,grid_um=np.asarray(grid));np.savez_compressed(out/'tables'/f'{model}_joint_random_G{group_index:02d}.npz',**arrays)
    return combined,metadata


def combined_distance_figures(records,out,settings):
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.ticker import PercentFormatter,MaxNLocator
    from publication21_figures import style,OBS,EVEN,RANDOM
    from self_service_report import save,random_curve_cloud
    from self_service_engine import dump,load,UserError
    from plot_settings import draw_cdf,register_legend,tag
    style();figures=[];groups=defaultdict(list);metadata=[]
    for record in records:
        if record['point']:groups[(record['distance_limit_um'],record['distance_step_um'],record['near_um'])].append(record)
    for gi,(key,members) in enumerate(groups.items(),1):
        for model,title,stem in [('point','Center-location model','03_Combined_Point'),('area','Equal-area design model','04_Combined_Area')]:
            eligible=members if model=='point' else [r for r in members if r['area'].get('available')]
            if not eligible:continue
            frames=[pd.read_csv(out/r['copied_case']/'result'/'tables'/f'{model}_curves.csv') for r in eligible]
            grid=frames[0].r_um.to_numpy();weights=np.array([r['point']['N'] for r in eligible],float)
            if any(len(f)!=len(grid) or not np.allclose(f.r_um,grid) for f in frames):raise UserError('Pooled curves have inconsistent distance grids.')
            combined=pd.DataFrame(dict(r_um=grid,observed=np.average([f.observed for f in frames],axis=0,weights=weights),baseline=np.average([f.baseline for f in frames],axis=0,weights=weights)))
            for column,filename in [('even','point_evenly_spread.csv' if model=='point' else '02_even_distances.csv'),('random_example','point_random_example.csv' if model=='point' else '03_random_distances.csv')]:
                values=[]
                for record in eligible:
                    distances=pd.read_csv(out/record['copied_case']/'result'/'tables'/filename).distance_um.to_numpy()
                    values.append((distances[:,None]<=grid).mean(axis=0))
                combined[column]=np.average(values,axis=0,weights=weights)
            count=settings['random_curve_count'];random_curves,streams=joint_random_curves(eligible,model,grid,count,out,gi)
            approximate=any(s.get('sampling',{}).get('approximate',False) for s in streams) or (model=='area' and any(r['area'].get('approximate_sampling',False) for r in eligible))
            combined['display_random_mean']=random_curves.mean(axis=0)
            combined.to_csv(out/'tables'/f'{model}_combined_G{gi:02d}.csv',index=False,encoding='utf-8-sig')
            table=pd.DataFrame(random_curves,columns=[f'r_{r:.10g}_um' for r in grid]);table.insert(0,'layout_index',np.arange(1,count+1))
            table.to_csv(out/'tables'/f'{model}_combined_random_G{gi:02d}.csv',index=False,encoding='utf-8-sig')
            if settings['legend_position']=='below':
                fig=plt.figure(figsize=(135/25.4,120/25.4));ax=fig.add_axes([.15,.30,.81,.59])
            else:
                fig=plt.figure(figsize=(183/25.4,88/25.4));ax=fig.add_axes([.10,.20,.56,.62])
            cloud_handle=random_curve_cloud(ax,grid,random_curves,settings)
            individual=tag(Line2D([],[],color='#a5a9ad',lw=.7,label='Individual observed'),'individual')
            for frame in frames:draw_cdf(ax,grid,frame.observed,settings,color='#a5a9ad',lw=.65,alpha=.8,zorder=2,role='individual')
            roles=[('observed',OBS,'-','Combined observed',1.5),('even',EVEN,'-.','Evenly spread',1.15),('random_example',RANDOM,':','First saved random',1.15),('baseline','#222222','--','Random expectation',1.1)]
            handles=[]
            for column,color,ls,label,width in roles:handles.append(draw_cdf(ax,grid,combined[column],settings,color=color,ls=ls,lw=width,label=label,zorder=4)[0])
            handles.extend([cloud_handle,individual])
            ax.set(xlim=(grid[0],grid[-1]),ylim=(0,1.02),xlabel='Distance to dark region (μm)',ylabel='Cumulative fraction')
            display_title=title+' (approximate)' if approximate else title
            info=load(out/'inputs'/'sample_identity.json') if (out/'inputs'/'sample_identity.json').exists() else {}
            overlap=bool(info.get('overlap_conflicts'))
            ax.set_title(f'{display_title} | G{gi:02d}\n{len(eligible)} fields; {int(weights.sum())} detections'+(' | overlap' if overlap else ''),loc='left',fontsize=8,pad=10,linespacing=1.45)
            ax.yaxis.set_major_formatter(PercentFormatter(1));ax.set_yticks([0,.25,.5,.75,1]);ax.xaxis.set_major_locator(MaxNLocator(settings['x_tick_count']))
            ax.grid(axis='y',color='#edf0f2',lw=.4,zorder=0)
            register_legend(ax,handles=handles,loc='upper left',bbox_to_anchor=(1.08,1.0),borderaxespad=0,fontsize=7,labelspacing=1.25,handlelength=2.2)
            caption=f'Parameter group G{gi:02d}：'+('Center distances' if model=='point' else 'Equal-area design')+'Pooled cumulative curves (observed, uniform and random controls)'
            save(fig,out,f'{stem}_G{gi:02d}',figures,caption)
            metadata.append(dict(group=f'G{gi:02d}',model=model,case_codes=[r['code'] for r in eligible],N=int(weights.sum()),distance_limit_um=key[0],step_um=key[1],near_um=key[2],random_curves=count,streams=streams,
                                 weighting='observed particle counts',combined_p=None,approximate_sampling=approximate,legend_location='configured',random_range_is_measurement_ci=False))
    dump(out/'logs'/'comparison_groups.json',metadata)
    return figures
