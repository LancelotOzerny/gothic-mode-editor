"""Install only the current mod, recording ownership in the existing project config."""
import hashlib
import json
from pathlib import Path
import tempfile

from .artifact_transaction import publish_files
from .mod_package import validate_build
from .localization import tr
from .mesh_cache import MeshCache


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ModInstallerService:
    def __init__(self, project, game, config):
        self.project, self.game, self.config = project, game, config

    def paths(self):
        if not self.game.is_dir():raise ValueError(tr('tools.game_required'))
        archive=self.game/'Data/ModVDF'/self.config.filename
        ini=self.game/'System'/self.config.ini_name
        for path in (archive,ini):
            if self.game.resolve() not in path.resolve().parents:raise ValueError('Путь установки выходит за пределы Gothic II')
        return archive,ini

    def install(self, report=lambda _:None):
        from .project_tools import ToolResult
        logs=self.project/'logs'
        logs.mkdir(parents=True,exist_ok=True)
        log_path=logs/'sync.log'
        log_path.write_text('',encoding='utf-8')
        def log(message):
            with log_path.open('a',encoding='utf-8') as stream:stream.write(message+'\n')
            report(message)
        try:
            source_mod=self.project/'dist'/self.config.filename
            source_ini=self.project/'dist'/self.config.ini_name
            files=validate_build(source_mod,source_ini,self.config)
            archive,ini=self.paths()
            cfg=self.project/'project.json'
            data=json.loads(cfg.read_text('utf-8'))
            key=str(self.game.resolve()).casefold()+'|'+self.config.filename.casefold()
            receipts=data.setdefault('mod_installations',{})
            receipt=receipts.get(key,{})
            owned=receipt.get('project')==str(self.project.resolve())
            for target in (archive,ini):
                relative=target.relative_to(self.game).as_posix()
                if target.exists() and (not owned or receipt.get('files',{}).get(relative)!=digest(target)):
                    raise ValueError(tr('pipeline.install_conflict',path=str(target)))
            pairs=[(source_mod,archive),(source_ini,ini)]
            changes=[pair for pair in pairs if not pair[1].is_file() or digest(pair[0])!=digest(pair[1])]
            cache_pairs=MeshCache(self.project,self.game).plan(files)
            receipts[key]={'project':str(self.project.resolve()),'files':{
                target.relative_to(self.game).as_posix():digest(source) for source,target in pairs}}
            # Receipt update participates in the same rollback as the two installed files.
            with tempfile.TemporaryDirectory(prefix='gothic-install-') as temporary:
                updated=Path(temporary)/'project.json'
                updated.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                def verify():
                    validate_build(archive,ini,self.config)
                    if any(digest(source)!=digest(target) for source,target in pairs):
                        raise ValueError('Установленные файлы не совпадают со сборкой')
                publish_files(changes+cache_pairs+[(updated,cfg)],commit=verify)
            MeshCache.report(cache_pairs,log)
            log(tr('tools.sync_success',path=str(archive),count=len(changes)))
            return ToolResult(archive,files=len(changes),archive=archive,operation='sync')
        except Exception as exc:
            log(str(exc))
            raise
