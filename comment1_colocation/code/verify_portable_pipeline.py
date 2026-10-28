"""Run the EXE without Python/Conda PATH: import, browser API, CPU and CUDA reports."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
import uuid
import re
from urllib.request import urlopen,Request
import numpy as np

from self_service_engine import ROOT,load,dump,configure_temp


def english_phase_labels(value):
    if isinstance(value,dict):return {k:english_phase_labels(v) for k,v in value.items()}
    if isinstance(value,list):return [english_phase_labels(v) for v in value]
    if isinstance(value,str):return {'金颗粒':'Gold','黄铜矿':'Chalcopyrite'}.get(value,value)
    return value


def main():
    work=Path(load(ROOT/'logs/upgrade_release_work.json')['work']);configure_temp(work/'portable_driver')
    release=Path(load(ROOT/'logs/portable_build_inputs.json')['release']);exe=release/'EOH/EOH.exe'
    workspace=work/('p'+uuid.uuid4().hex[:2]);cases=workspace/'c';cases.mkdir(parents=True,exist_ok=False)
    env=dict(os.environ);env['PATH']=os.environ.get('SystemRoot','C:/Windows')+'/System32;'+os.environ.get('SystemRoot','C:/Windows')
    for key in ['PYTHONPATH','PYTHONHOME','PYTHONUTF8','PYTHONIOENCODING','CUDA_PATH']:env.pop(key,None)
    env.update(BSE_WORKSPACE=str(workspace),BSE_COMPUTE_BACKEND='auto')
    log=ROOT/'logs/portable_pipeline_validation.json';result=dict(checks={},release=str(release));checks=result['checks']
    def run(args,backend='auto'):
        local=dict(env,BSE_COMPUTE_BACKEND=backend)
        completed=subprocess.run([str(exe),'--engine',*map(str,args)],env=local,cwd=work,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        raw=completed.stdout
        # Keep both UTF-8 and native Windows error output inspectable.
        text=raw.decode('utf-8',errors='replace');(ROOT/'logs/portable_last_worker.txt').write_text(text,encoding='utf-8')
        if completed.returncode:raise RuntimeError(text)
        events=[]
        for line in text.splitlines():
            try:events.append(json.loads(line))
            except ValueError:pass
        return events
    source=ROOT.parent/'分析结果/3';meta=load(source/'case.json');original=next((source/'inputs').glob('original.*'))
    spec=work/'portable_import.json';dump(spec,dict(source=str(original),name='便携测试',crop=meta['crop_xyxy'],pixel_size_um=meta['pixel_size_um'],adaptive_segmentation=True,
              analysis=dict(rmax_um=1,step_um=.25,near_um=1,size_guard_um=1,mode='full',finite=False,exclusive_phases=True)))
    imported=run(['import','--spec',spec,'--cases-root',cases],backend='cpu')
    case=Path(next(e['case'] for e in imported if e.get('event')=='complete'))
    assert (case/'case.json').exists();checks['exe_import_and_unicode_worker_protocol']=True
    key=load(case/'case.json')['case_id'];sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    server_log=(work/'review_server.log').open('wb')
    proc=subprocess.Popen([str(exe),'--server','--port',str(port),'--cases-root',str(cases)],env=env,cwd=work,stdout=server_log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    base=f'http://127.0.0.1:{port}/case/{key}'
    try:
        for attempt in range(60):
            try:
                with urlopen(base+'/api/reviews',timeout=1) as response:review=json.load(response)
                break
            except Exception:
                if proc.poll() is not None:raise RuntimeError((work/'review_server.log').read_text('utf-8',errors='replace'))
                time.sleep(.2)
        else:raise RuntimeError('Portable review server did not start')
        with urlopen(base+'/review/',timeout=10) as response:page=response.read().decode('utf-8')
        assert 'Save all changes' in page and '<html lang="en">' in page
        review['base_revision']=review['revision'];review['actions'].append(dict(id='portable_point',image_id='1',object_id='EX0001',operation='add_exclusion',geometry=dict(kind='point',points=[[300,300]],radius_um=1)))
        review['active_ids'].append('portable_point')
        request=Request(base+'/api/reviews',data=json.dumps(review).encode('utf-8'),headers={'Content-Type':'application/json'},method='POST')
        with urlopen(request,timeout=10) as response:saved=json.load(response)
        assert saved['revision']==1 and load(case/'report/review_annotations/review_annotations.json')['revision']==1
        checks['exe_review_server_opens_and_saves_annotations']=True
    finally:proc.terminate();proc.wait(timeout=10);server_log.close()
    from verify_batch_summary import stage_case
    live=ROOT.parent/'分析结果/5';staged=cases/('v5_'+uuid.uuid4().hex[:3]);stage_case(live,staged)
    shutil.copyfile(live/'plot_settings.json',staged/'plot_settings.json')
    reference=Path(load(live/'latest_report.json')['report']).parent.parent
    batch_selection=work/'portable_batch.json';dump(batch_selection,dict(cases=[staged.name,case.name]))
    events=run(['analyze-batch','--selection',batch_selection,'--cases-root',cases])
    assert any(e.get('event')=='complete' for e in events)
    output=Path(load(staged/'latest_report.json')['report']).parent.parent
    for name in ['point_simulations.npz','area_simulations.npz']:
        with np.load(reference/'tables'/name) as a,np.load(output/'tables'/name) as b:
            for field in a.files:assert np.array_equal(a[field],b[field]),(name,field)
    for name in ['point_summary.json','area_summary.json','grain_size_summary.json']:assert english_phase_labels(load(reference/'logs'/name))==load(output/'logs'/name),name
    for name in ['Report.html','Grain_Size_Report.html']:
        document=(output/'report'/name).read_text('utf-8');assert not re.search('[\u3400-\u9fff]',document),name
    checks['new_spatial_and_grain_reports_are_english']=True
    compute=load(output/'logs/compute_backend.json');assert any(e.get('backend')=='CUDA' for e in compute['events'])
    assert not any('fallback' in e.get('backend','').lower() for e in compute['events']),compute
    checks['standalone_cuda_full_report_matches_cpu_reference']=True
    imported_gpu=Path(load(case/'latest_report.json')['report']).parent.parent
    imported_compute=load(imported_gpu/'logs/compute_backend.json')
    assert imported_compute['worker_pid']==compute['worker_pid'] and imported_compute['gpu_initializations']==compute['gpu_initializations']==1
    checks['batch_uses_one_process_and_one_gpu_context']=True
    events=run(['analyze','--case',case,'--cases-root',cases,'--confirmed-revision','1','--candidate'],backend='cpu')
    assert any(e.get('event')=='complete' for e in events)
    output_cpu=Path(load(case/'latest_report.json')['report']).parent.parent
    assert load(output_cpu/'logs/compute_backend.json')['device']=='CPU'
    assert load(output_cpu/'logs/point_summary.json')==load(imported_gpu/'logs/point_summary.json')
    assert (output_cpu/'report/Grain_Size_Report.pdf').exists() and (output_cpu/'report/Report.pdf').exists()
    checks['standalone_cpu_full_report_without_cuda']=True
    result.update(status='passed',compute=compute,private_test_data_only_in_task_temporary_directory=True)
    dump(log,result);print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
