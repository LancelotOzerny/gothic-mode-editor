"""Version-aware GothicStarter launch; never builds or installs implicitly."""
import ctypes
import os
from pathlib import Path
import subprocess

from .mod_install import ModInstallerService
from .mod_package import validate_build
from .localization import tr
from .mesh_cache import MeshCache


def starter_supports_direct(path):
    """Recognize the documented Gothic II PlayerKit 2.6f Starter, not arbitrary wrappers."""
    if os.name!='nt':return False
    version=ctypes.WinDLL('version',use_last_error=True)
    size=version.GetFileVersionInfoSizeW(str(path),None)
    if not size:return False
    buffer=ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path),0,size,buffer):return False
    pointer=ctypes.c_void_p()
    length=ctypes.c_uint()
    if not version.VerQueryValueW(buffer,'\\',ctypes.byref(pointer),ctypes.byref(length)):return False
    if length.value<52:return False
    fixed=ctypes.cast(pointer,ctypes.POINTER(ctypes.c_uint32*13)).contents
    major,minor=fixed[2]>>16,fixed[2]&0xFFFF
    patch,revision=fixed[3]>>16,fixed[3]&0xFFFF
    return fixed[0]==0xFEEF04BD and (major,minor,patch,revision)==(2,6,6,0)


class ModLauncherService:
    def __init__(self, project, game, config):
        self.project,self.game,self.config=project,game,config

    def launch(self,report=lambda _:None):
        from .project_tools import ToolResult
        logs=self.project/'logs'
        logs.mkdir(parents=True,exist_ok=True)
        log_path=logs/'launch.log'
        log_path.write_text('',encoding='utf-8')
        def log(message):
            with log_path.open('a',encoding='utf-8') as stream:stream.write(message+'\n')
            report(message)
        try:
            archive,ini=ModInstallerService(self.project,self.game,self.config).paths()
            files=validate_build(archive,ini,self.config)
            starter=Path(self.config.starter_path).expanduser() if self.config.starter_path.strip() else self.game/'System/GothicStarter.exe'
            if not starter.is_absolute():starter=self.project/starter
            if not starter.is_file():raise ValueError(tr('pipeline.starter_missing',path=str(starter)))
            MeshCache(self.project,self.game).invalidate(files,log)
            direct=starter_supports_direct(starter)
            command=[str(starter.resolve())]
            if direct:command+=['-start','-game:'+ini.name]
            else:log(tr('pipeline.manual_launch',name=ini.name))
            log(subprocess.list2cmdline(command))
            with log_path.open('a',encoding='utf-8') as output:
                process=subprocess.Popen(command,cwd=ini.parent,stdout=output,stderr=subprocess.STDOUT)
            log(tr('pipeline.launched',pid=process.pid))
            return ToolResult(ini,archive=archive,operation='launch',manual=not direct)
        except Exception as exc:
            log(str(exc))
            raise
