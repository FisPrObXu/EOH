"""Build a self-contained Windows folder; no project images/reviews are bundled."""
import ast
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime

from self_service_engine import ROOT,load,dump,configure_temp,tempdir,within


def main():
    pointer=ROOT/'logs/upgrade_release_work.json'
    work=Path(load(pointer)['work']) if pointer.exists() else tempdir(ROOT/'_tmp','portable_build');configure_temp(work/'build_runtime')
    os.environ['PYINSTALLER_CONFIG_DIR']=str(work/'pyinstaller_cache')
    resources=work/'resources';(resources/'code').mkdir(parents=True,exist_ok=True)
    modules=set();pending=['portable_entry','self_service_engine','self_service_gui','self_service_server','batch_summary','enhance_bright_case','revise_summary_figures']
    # Include local modules used both by imports and by exported source snapshots.
    for file in (ROOT/'code').glob('*.py'):
        if file.name in ['analysis.py','analyze_review21.py','area_redistribution21.py','publication21_figures.py','review_editor.py','segmentation.py','apply_review21.py','audit_pdf_text.py','audit_figure_collisions.py','audit_panel_alignment.py']:pending.append(file.stem)
    while pending:
        name=pending.pop()
        if name in modules:continue
        file=ROOT/'code'/(name+'.py')
        if not file.exists():continue
        modules.add(name);tree=ast.parse(file.read_text('utf-8'))
        for node in ast.walk(tree):
            names=[alias.name.split('.')[0] for alias in node.names] if isinstance(node,ast.Import) else [node.module.split('.')[0]] if isinstance(node,ast.ImportFrom) and node.module else []
            pending.extend(n for n in names if (ROOT/'code'/(n+'.py')).exists())
    for name in modules:shutil.copyfile(ROOT/'code'/(name+'.py'),resources/'code'/(name+'.py'))
    for name in ['review_editor.html','review_exclusions.js']:shutil.copyfile(ROOT/'code'/name,resources/'code'/name)
    cfg=load(ROOT/'config.json');cfg['images']={};dump(resources/'config.json',cfg)
    shutil.copyfile(ROOT.parent/'EOH_中文说明手册.html',resources/'操作说明.html')
    release=ROOT.parent/'releases'/'EOH_0.4.1_win64'
    if release.exists():release=release.with_name(release.name+'_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
    release.mkdir(parents=True,exist_ok=False)
    dump(release/'build_provenance.json',dict(created_by='build_portable.py',created=datetime.now().isoformat(),product='EOH',full_name='Eyes of heaven',version='0.4.1',workspace=str(work),new_directory=True))
    source_root=release/'source';source_code=source_root/'comment1_colocation'/'code';source_code.mkdir(parents=True)
    for file in (resources/'code').iterdir():shutil.copyfile(file,source_code/file.name)
    shutil.copyfile(Path(__file__),source_code/'build_portable.py')
    shutil.copyfile(ROOT/'code/windows_version_info.txt',source_code/'windows_version_info.txt')
    shutil.copyfile(resources/'config.json',source_code.parent/'config.json')
    shutil.copyfile(resources/'操作说明.html',source_root/'EOH_中文说明手册.html')
    shutil.copyfile(resources/'操作说明.html',release/'EOH_中文说明手册.html')
    for target in [release,source_root]:
        shutil.copyfile(ROOT.parent/'README.md',target/'README.md')
        shutil.copytree(ROOT.parent/'docs'/'images',target/'docs'/'images')
    (source_root/'构建说明.txt').write_text('EOH 0.4.1: see BUILDING.md and SOURCE.md for Windows build steps and corresponding source. EOH is licensed under AGPL-3.0-only; third-party components retain their own terms.',encoding='utf-8')
    for name in ['LICENSE','BUILDING.md','SOURCE.md','THIRD_PARTY_NOTICES.md']:
        shutil.copyfile(ROOT.parent/name,release/name)
        shutil.copyfile(ROOT.parent/name,source_root/name)
    notices=[];licenses=release/'licenses';licenses.mkdir(exist_ok=True)
    shutil.copytree(ROOT.parent/'licenses'/'nature-figure',licenses/'nature-figure')
    for package in ['numpy','scipy','pandas','matplotlib','fonttools','fastrlock','Pillow','scikit-image','opencv-python','PyMuPDF','cupy','cupy-cuda12x','PyInstaller','nvidia-cuda-nvrtc-cu12','nvidia-cuda-runtime-cu12']:
        try:dist=metadata.distribution(package)
        except metadata.PackageNotFoundError:continue
        notices.append(dict(name=dist.metadata['Name'],version=dist.version,license=dist.metadata.get('License-Expression') or dist.metadata.get('License'),homepage=dist.metadata.get('Home-page')))
        folder=licenses/package;folder.mkdir(exist_ok=True)
        for f in dist.files or []:
            if any(part.lower() in ['licenses','license','copying'] for part in f.parts) or f.name.upper().startswith(('LICENSE','COPYING','NOTICE')):
                original=Path(dist.locate_file(f))
                if original.is_file():shutil.copyfile(original,folder/('_'.join(f.parts[-3:])))
    dump(release/'third_party_versions.json',notices)
    (release/'Release_and_license_notes.txt').write_text('EOH — Eyes of heaven\nVersion 0.4.1 | Windows x64 portable release\n\nExtract the whole archive and run EOH/EOH.exe with the accompanying _internal folder. The package includes the application runtime.\nChoose an NVIDIA GPU or CPU in the application. The interface and reports use English; the Chinese manual explains each step. README.md presents an illustrated sample.\n\nEOH is licensed under AGPL-3.0-only. Third-party components retain their own terms. See LICENSE, THIRD_PARTY_NOTICES.md, SOURCE.md, and licenses/.\n',encoding='utf-8')
    # CUDA header trees are deep; explicit Windows long paths keep the build
    # inside the user's project without relying on a machine-wide registry change.
    dist_path='\\\\?\\'+str(release.resolve()) if os.name=='nt' else str(release)
    args=[sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--console','--noupx','--python-option','X utf8','--name','EOH',
          '--version-file',str(ROOT/'code/windows_version_info.txt'),
          '--workpath',str(work/'build'),'--specpath',str(work),'--distpath',dist_path,
          '--paths',str(ROOT/'code'),'--add-data',str(resources)+os.pathsep+'resources',
          '--collect-all','cupy','--collect-all','cupy_backends','--collect-all','fastrlock','--collect-data','matplotlib','--collect-data','setuptools',
          '--collect-submodules','scipy._lib.array_api_compat','--collect-submodules','scipy._lib.array_api_extra',
          '--hidden-import','scipy._cyutility',
          '--hidden-import','matplotlib.backends.backend_pdf','--hidden-import','matplotlib.backends.backend_svg',
          '--hidden-import','matplotlib.backends.backend_mixed','--collect-submodules','fontTools',
          '--exclude-module','torch','--exclude-module','tensorflow','--exclude-module','PyQt5','--exclude-module','PyQt6',
          '--exclude-module','PySide2','--exclude-module','PySide6','--exclude-module','IPython','--exclude-module','notebook']
    for name in ['numba','sklearn','dask','distributed','pytest','sympy','sphinx','aiohttp','bokeh','plotly','jupyter','pyarrow','tables','sqlalchemy']:
        args+=['--exclude-module',name]
    # CuPy loads CUDA DLLs dynamically; include the installed redistributable runtime.
    libraries=[Path(sys.prefix)/'Library'/'bin',Path(sys.prefix)/'Lib'/'site-packages'/'nvidia'/'cuda_nvrtc'/'bin',Path(sys.prefix)/'Lib'/'site-packages'/'nvidia'/'cuda_runtime'/'bin']
    selected=set()
    for library in libraries:
        for pattern in ['cudart64*.dll','nvrtc64_120_0.dll','nvrtc-builtins*.dll']:
            for dll in library.glob(pattern):
                if dll.name.lower() not in selected:args+=['--add-binary',str(dll)+os.pathsep+'.'];selected.add(dll.name.lower())
    for name in sorted(modules):args+=['--hidden-import',name]
    args.append(str(ROOT/'code'/'portable_entry.py'))
    dump(ROOT/'logs'/'portable_build_inputs.json',dict(modules=sorted(modules),command=args,release=str(release)))
    with (ROOT/'logs'/'portable_build.log').open('w',encoding='utf-8') as log:
        subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,check=True)
    output=within(release/'EOH',release);omitted=tempdir(work,'unused_cuda_build')
    headers=output/'_internal/cupy/_core/include'
    for name in ['cuda_fp16.h','cuda_fp16.hpp']:
        shutil.copyfile(headers/'cupy/_cuda/cuda-12'/name,headers/name)
    for name in ['cublasLt64_12.dll','cublas64_12.dll','cusparse64_12.dll','cufft64_11.dll','cusolver64_11.dll','curand64_10.dll','nvJitLink_120_0.dll']:
        file=within(output/'_internal'/name,output);target=within(omitted/name,omitted)
        if file.exists():shutil.move(file,target)
    binaries={p.name.lower() for p in (output/'_internal').glob('*.dll')};native=[]
    for meta_file in (Path(sys.prefix)/'conda-meta').glob('*.json'):
        data=load(meta_file)
        if not any(Path(f).name.lower() in binaries for f in data.get('files',[])):continue
        native.append({k:data.get(k) for k in ['name','version','build','license','url']})
        cached=Path(data.get('link',{}).get('source',''))/'info/licenses'
        if cached.is_dir():
            destination=licenses/('native_'+data['name']);destination.mkdir(exist_ok=True)
            for file in cached.rglob('*'):
                if file.is_file():shutil.copyfile(file,destination/('_'.join(file.relative_to(cached).parts)))
    dump(release/'native_library_versions.json',native)
    print(str(release),flush=True)


if __name__=='__main__':main()
