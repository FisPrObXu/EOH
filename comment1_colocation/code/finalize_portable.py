"""Document and archive an already validated portable build, without private cases."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile

from self_service_engine import ROOT, load, dump, within





def main():
    release = within(Path(load(ROOT/'logs/portable_build_inputs.json')['release']), ROOT.parent/'releases')
    pipeline = load(ROOT/'logs/portable_pipeline_validation.json')
    assert pipeline['status'] == 'passed' and Path(pipeline['release']) == release
    numerical = load(ROOT/'logs/upgrade_release_validation.json')
    assert numerical['status'] == 'passed'
    gui = load(ROOT/'logs/portable_final_gui_smoke.json')
    assert gui['ok'] and gui['gui'] and gui['frozen']
    english=load(ROOT/'logs/eoh_english_validation.json');assert english['status']=='passed'
    browser=load(ROOT/'logs/eoh_browser_validation.json');assert browser['status']=='passed'
    shutil.copyfile(ROOT.parent/'EOH_中文说明手册.html',release/'EOH_中文说明手册.html')
    (release/'README.txt').write_text('EOH — Eyes of heaven\nVersion 0.4.1 | Windows x64\n\nExtract the entire archive. Run EOH/EOH.exe and retain its _internal folder. The package includes the application runtime.\nThe interface and newly generated reports are in English. Open EOH_中文说明手册.html for the Chinese manual, or click Chinese manual in EOH.\nFor existing cases, use Output case folder > Browse to select your previous case folder.\n',encoding='utf-8')
    checks = dict(product='EOH',full_name='Eyes of heaven',version='0.4.1', verified_at=datetime.now().isoformat(),english_interface=english['checks'],browser_review=browser['checks'],
                  standalone=pipeline['checks'], numerical_and_ui=numerical['checks'],
                  packaged_gui_and_three_dialogs_without_python_path=True,
                  benchmark=dict(cpu_seconds=numerical['previous_cpu_full_report_seconds'],
                                 warm_gpu_seconds=numerical['gpu_full_report_seconds'],
                                 speedup=numerical['end_to_end_speedup'],
                                 hardware='NVIDIA GeForce RTX 4060 Laptop GPU',
                                 note='One measured case on the development computer.'),
                  no_private_images_reviews_or_reports=True)
    dump(release/'Validation_summary.json', checks)
    # Retain full ownership proof privately; do not ship the author's workstation path.
    provenance = load(release/'build_provenance.json')
    if 'workspace' in provenance:
        private = ROOT/'logs'/('release_provenance_'+release.name+'.json')
        dump(private, provenance)
        provenance.pop('workspace')
        dump(release/'build_provenance.json', provenance)
    source_code=release/'source/comment1_colocation/code'
    for name in ['build_portable.py','finalize_portable.py']:
        shutil.copyfile(ROOT/'code'/name, source_code/name)
    for name in ['verify_upgrade_release.py','verify_portable_pipeline.py','verify_batch_summary.py','verify_eoh_english.py','verify_eoh_browser.py']:
        shutil.copyfile(ROOT/'code'/name, source_code/name)
    archive = release.parent/(release.name+'.zip')
    assert not archive.exists(), 'Use a new release path instead of overwriting a previous distribution'
    io_root = Path('\\\\?\\'+str(release.resolve())) if os.name == 'nt' else release
    entries = sorted((p for p in io_root.rglob('*') if p.is_file()), key=str)
    forbidden = {'review_annotations.json','latest_report.json','case.json'}
    assert not any(p.name in forbidden or p.name.startswith('original.') for p in entries)
    assert not (release/'EOH/工作数据').exists(), 'Runtime data must not enter distribution'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=3, allowZip64=True) as z:
        for file in entries:
            rel=file.relative_to(io_root)
            z.write(file, 'EOH_0.4.1/'+rel.as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert 'EOH_0.4.1/EOH/EOH.exe' in z.namelist()
    digest=hashlib.sha256()
    with archive.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):digest.update(block)
    archive.with_suffix('.zip.sha256.txt').write_text(digest.hexdigest()+'  '+archive.name+'\n',encoding='utf-8')
    result=dict(release=str(release),archive=str(archive),bytes=archive.stat().st_size,
                files=len(entries),sha256=digest.hexdigest(),zip_crc_verified=True,checks=checks)
    dump(ROOT/'logs/portable_distribution.json',result)
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
