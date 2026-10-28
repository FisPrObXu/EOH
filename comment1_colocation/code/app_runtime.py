"""Writable portable workspace, packaged resources and child-process routing."""
from pathlib import Path
import os
import sys
import shutil


def error_message(error):
    """Keep application-owned error dialogs English on non-English Windows."""
    if not isinstance(error,OSError):return str(error)
    code=getattr(error,'winerror',None)
    if code is not None and os.name=='nt':
        import ctypes
        buffer=ctypes.create_unicode_buffer(2048)
        if ctypes.windll.kernel32.FormatMessageW(0x1000|0x200,None,code,0x0409,buffer,len(buffer),None):
            message=f'[WinError {code}] '+buffer.value.strip()
        else:message=f'Windows file-system error {code}'
    else:
        import errno
        message=f'{type(error).__name__}: '+errno.errorcode.get(error.errno,'File-system error')
    if error.filename:message+=': '+str(error.filename)
    if getattr(error,'filename2',None):message+=' -> '+str(error.filename2)
    return message

FROZEN=bool(getattr(sys,'frozen',False))
SOURCE_ROOT=Path(__file__).resolve().parents[1]
ROOT=Path(os.environ.get('BSE_WORKSPACE',str(Path(sys.executable).parent/'工作数据' if FROZEN else SOURCE_ROOT))).resolve()


def initialize():
    ROOT.mkdir(parents=True,exist_ok=True)
    if FROZEN:
        resources=Path(sys._MEIPASS)/'resources'
        for folder in ['code','logs','_tmp']:(ROOT/folder).mkdir(exist_ok=True)
        for source in (resources/'code').iterdir():
            target=ROOT/'code'/source.name
            if source.is_file() and (not target.exists() or target.read_bytes()!=source.read_bytes()):shutil.copyfile(source,target)
        if not (ROOT/'config.json').exists():shutil.copyfile(resources/'config.json',ROOT/'config.json')
        if (resources/'操作说明.html').exists():shutil.copyfile(resources/'操作说明.html',ROOT/'操作说明.html')


def command(kind,*args):
    if FROZEN:return [sys.executable,'--'+kind,*map(str,args)]
    script='self_service_engine.py' if kind=='engine' else 'self_service_server.py'
    return [sys.executable,'-B',str(ROOT/'code'/script),*map(str,args)]
