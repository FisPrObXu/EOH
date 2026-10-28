"""CPU/CUDA numerical equivalence, real-report timing, and small-screen reachability."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from unittest.mock import patch
import numpy as np
from self_service_engine import ROOT,load,dump,configure_temp,analyze


def main():
    work=Path(load(ROOT/'logs/upgrade_release_work.json')['work']);configure_temp(work/'verification_runtime')
    result=dict(checks={});checks=result['checks'];log=ROOT/'logs/upgrade_release_validation.json'
    from analyze_review21 import evenly_spread,_evenly_spread_cpu
    from self_service_engine import finite_bank,_finite_bank_cpu
    from area_redistribution21 import catalogue
    from acceleration import report
    y,x=np.mgrid[:71,:91];domain=np.ones(y.shape,bool);domain[20:35,40:49]=False
    for N in [1,7,15]:
        a,_=_evenly_spread_cpu(domain,N);b,_=evenly_spread(domain,N);assert np.array_equal(a,b)
    checks['cuda_uniform_layouts_exact_with_cpu_including_ties']=True
    cats=catalogue(domain,[4,5,5,4]);a,v=_finite_bank_cpu(domain,[4,5,5,4],cats,4999,500,work)
    b,w=finite_bank(domain,[4,5,5,4],cats,4999,500,work);assert np.array_equal(a,b) and np.array_equal(v,w)
    checks['cuda_4999_placements_and_variants_exact_with_cpu']=True
    with patch.dict(os.environ,{'BSE_COMPUTE_BACKEND':'cpu'}):
        c,_=evenly_spread(domain,7);d,_=_evenly_spread_cpu(domain,7);assert np.array_equal(c,d)
    checks['cpu_selection_works']=True
    # Simulate a failed GPU kernel; the public wrapper must produce the original CPU result.
    import acceleration
    with patch.object(acceleration,'try_evenly_spread',return_value=None):
        c,_=evenly_spread(domain,7);assert np.array_equal(c,d)
    checks['missing_gpu_uses_cpu_path']=True
    from self_service_gui import App,ImportDialog,PlotSettingsDialog,BrightDetectionDialog
    source=ROOT.parent/'分析结果/5';original=next((source/'inputs').glob('original.*'))
    for scale in [1.,1.5,2.]:
        app=App(work/'ui_cases',hidden=True);app.tk.call('tk','scaling',scale);app.geometry('900x500+5000+5000');app.deiconify();app.update()
        assert app.scroll.canvas.winfo_height()>100
        for kind in ['import','plot','bright']:
            case=work/'ui_case';dump(case/'case.json',dict(name='QA'))
            form=ImportDialog(app,original,lambda value:None,hidden=True) if kind=='import' else PlotSettingsDialog(app,case,hidden=True) if kind=='plot' else BrightDetectionDialog(app,case,lambda value:None,hidden=True)
            form.geometry('760x500+5000+5000');form.deiconify();form.update()
            button=form.accept_button if kind=='import' else form.save_button if kind=='plot' else form.create_button
            assert button.winfo_ismapped(),(scale,kind)
            assert button.winfo_rooty()+button.winfo_height()<=form.winfo_rooty()+form.winfo_height(),(scale,kind,'button below window')
            assert button.winfo_rootx()+button.winfo_width()<=form.winfo_rootx()+form.winfo_width(),(scale,kind,'button beyond right edge')
            form.destroy()
        app.close();configure_temp(work/'verification_runtime')
    checks['900x500_and_three_font_scales_keep_dialog_buttons_reachable']=True
    dump(log,result)
    from verify_batch_summary import stage_case
    staged=work/'analysis_cases/5';stage_case(source,staged)
    if (source/'plot_settings.json').exists():shutil.copyfile(source/'plot_settings.json',staged/'plot_settings.json')
    before=Path(load(source/'latest_report.json')['report']).parent.parent
    revision=load(staged/'report/review_annotations/review_annotations.json')['revision']
    started=time.perf_counter();output=analyze(staged,revision,human_review=False);seconds=time.perf_counter()-started
    import pandas as pd
    from verify_portable_pipeline import english_phase_labels
    for name in ['01_observed_distances.csv','02_even_distances.csv','03_random_distances.csv','point_curves.csv','area_curves.csv','grain_sizes_all.csv']:
        expected=pd.read_csv(before/'tables'/name)
        if 'phase' in expected:expected['phase']=expected['phase'].map(english_phase_labels)
        pd.testing.assert_frame_equal(expected,pd.read_csv(output/'tables'/name))
    for name in ['point_simulations.npz','area_simulations.npz']:
        with np.load(before/'tables'/name) as a,np.load(output/'tables'/name) as b:
            for key in a.files:assert np.array_equal(a[key],b[key]),(name,key)
    for name in ['point_summary.json','area_summary.json','grain_size_summary.json']:
        assert english_phase_labels(load(before/'logs'/name))==load(output/'logs'/name),name
    checks['real_case_distances_curves_p_values_all_simulations_and_sizes_unchanged']=True
    device=load(output/'logs/compute_backend.json');assert any(e['backend']=='CUDA' for e in device['events'])
    assert not any('fallback' in e['backend'].lower() for e in device['events']),device
    checks['real_report_used_cuda_without_fallback']=True
    result.update(status='passed',case='5',revision=revision,gpu_full_report_seconds=seconds,previous_cpu_full_report_seconds=load(ROOT/'logs/gpu_feasibility.json')['cpu_complete_analysis']['total_seconds'],compute=device)
    result['end_to_end_speedup']=result['previous_cpu_full_report_seconds']/seconds
    dump(log,result);print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
