"""Explicit project membership for lazily copied world/NPC resources."""
import json
from pathlib import Path
from uuid import uuid4
from .asset_files import AssetFiles


class ProjectSelection:
    def __init__(self,project,section):
        if section not in ('Worlds','NPC'):raise ValueError('Unknown project section')
        self.path=AssetFiles(project).checked(Path(project)/'Assets'/section/'catalog.json')

    def read(self):
        if not self.path.exists():return set()
        data=json.loads(self.path.read_text('utf-8'))
        if not isinstance(data,list) or any(not isinstance(value,str) for value in data):
            raise ValueError('Некорректный список проекта: '+str(self.path))
        return {value.casefold() for value in data}

    def add(self,name):
        values=self.read()|{name.casefold()}
        self._save(values)

    def remove(self,name):
        self._save(self.read()-{name.casefold()})

    def _save(self,values):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_name('.catalog-'+uuid4().hex+'.tmp')
        try:
            temporary.write_text(json.dumps(sorted(values),ensure_ascii=False,indent=2),encoding='utf-8')
            temporary.replace(self.path)
        finally:temporary.unlink(missing_ok=True)
