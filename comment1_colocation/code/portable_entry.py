"""Portable EXE entry: GUI, analysis worker and local reviewer in one distribution."""
import json
import os
from pathlib import Path
import sys
import traceback


def main():
    for stream in [sys.stdout,sys.stderr]:
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='backslashreplace')
    from app_runtime import ROOT,initialize,FROZEN
    initialize()
    for key in ['TEMP','TMP','TMPDIR']:os.environ[key]=str(ROOT/'_tmp')
    (ROOT/'_tmp').mkdir(exist_ok=True);os.environ['MPLCONFIGDIR']=str(ROOT/'cache'/'matplotlib');os.environ['PYTHONDONTWRITEBYTECODE']='1'
    if '--engine' in sys.argv:
        sys.argv.remove('--engine');from self_service_engine import main as run;run();return
    if '--server' in sys.argv:
        sys.argv.remove('--server');from self_service_server import main as run;run();return
    if '--check' in sys.argv:
        target=Path(sys.argv[sys.argv.index('--check')+1])
        import numpy as np
        import scipy,skimage,pandas,matplotlib,cv2,fitz
        from PIL import Image
        from self_service_gui import App,ImportDialog,PlotSettingsDialog,BrightDetectionDialog
        from self_service_engine import tempdir,safe_remove,configure_temp,dump
        from acceleration import gpu,report
        work=tempdir(ROOT/'_tmp','portable_check');configure_temp(work/'runtime');app=None
        try:
            image=work/'test.png';Image.fromarray(np.full((128,160),150,np.uint8)).save(image)
            app=App(work/'cases',hidden=True);app.update_idletasks();window_title=app.title()
            assert window_title=='EOH — Eyes of heaven | 0.4.1'
            form=ImportDialog(app,image,lambda spec:None,hidden=True);form.update_idletasks();assert form.accept_button.winfo_reqheight()>1;form.destroy()
            form=PlotSettingsDialog(app,work,hidden=True);form.update_idletasks();assert len(form.book.tabs())==3;form.destroy()
            dump(work/'case.json',dict(name='UI check'));form=BrightDetectionDialog(app,work,lambda value:None,hidden=True);form.destroy()
            app.close();app=None;configure_temp(work/'runtime')
            cp=gpu();cuda_sum=None
            if cp is not None:cuda_sum=int(cp.arange(10).sum().get())
            result=dict(ok=True,product='EOH',full_name='Eyes of heaven',version='0.4.1',window_title=window_title,frozen=FROZEN,python=sys.version,numpy=np.__version__,scipy=scipy.__version__,workspace=str(ROOT),gui=True,gpu=report(),cuda_sum=cuda_sum)
        finally:
            if app is not None:app.close()
            configure_temp(ROOT/'_tmp');safe_remove(work,ROOT/'_tmp')
        target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return
    if FROZEN:
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(),0)
    log=(ROOT/'logs'/'desktop_startup.log');log.parent.mkdir(exist_ok=True)
    sys.stdout=sys.stderr=log.open('a',encoding='utf-8',buffering=1)
    from self_service_gui import App
    App().mainloop()


if __name__=='__main__':
    worker_mode=any(value in sys.argv for value in ['--engine','--server'])
    try:main()
    except Exception:
        from app_runtime import ROOT
        error=traceback.format_exc();(ROOT/'logs').mkdir(parents=True,exist_ok=True);(ROOT/'logs'/'startup_error.txt').write_text(error,encoding='utf-8')
        if worker_mode:raise
        if any(v in sys.argv for v in ['--check']):raise
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,'EOH could not start. See:\n'+str(ROOT/'logs'/'startup_error.txt'),'EOH — Eyes of heaven',16)
        raise SystemExit(1)
