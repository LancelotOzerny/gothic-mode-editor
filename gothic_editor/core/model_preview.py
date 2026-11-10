"""Load static preview geometry and its textures off the UI thread."""
from dataclasses import dataclass, field
from collections import OrderedDict
from threading import Lock
import os
from pathlib import Path

from .mesh import PreviewMesh, read_3ds_bytes, read_mrm
from .textures import Texture, read_texture
from .texture_names import texture_candidates


@dataclass
class ModelPreview:
    mesh: PreviewMesh
    textures: dict[str, Texture]
    missing: list[str]
    textures_loaded: bool = True
    texture_sources: dict = field(default_factory=dict)
    render_token: object = field(default_factory=object,repr=False,compare=False)


def load_model_preview(source, project, game=None, item_assets=None, texture_entries=None, with_textures=True):
    data = source.read_bytes()
    name = source.name
    mesh = read_3ds_bytes(data, preview=True) if Path(name).suffix.lower() == '.3ds' else read_mrm(data, preview=True)
    if not any(mesh.texture_names):
        return ModelPreview(mesh, {}, [])
    if not with_textures:return ModelPreview(mesh,{},[],False)
    # Basenames follow Gothic's resource lookup; embedded absolute paths are ignored.
    directories = []
    if item_assets is not None:
        directories.append(Path(item_assets))
    if isinstance(source, Path):
        directories.append(source.parent)
    directories.append(Path(project) / 'Assets')
    if game is not None:
        directories.append(Path(game) / '_work/data/Textures')
    indexes = []
    for directory in dict.fromkeys(directories):
        index = {}
        try:
            if directory.is_dir():
                wanted={candidate for name in mesh.texture_names for candidate in texture_candidates(name) if name}
                for parent,folders,files in os.walk(directory):
                    folders.sort()
                    for filename in sorted(files):
                        if filename.lower() in wanted:index.setdefault(filename.lower(),Path(parent)/filename)
        except OSError:
            pass  # An inaccessible texture folder must not hide valid geometry.
        indexes.append(index)
    textures, missing, resolved = {}, [], {}
    for name in dict.fromkeys(mesh.texture_names):
        if not name:
            continue
        candidates = texture_candidates(name)
        sources = [index[candidate] for index in indexes for candidate in candidates if candidate in index]
        sources += [(texture_entries or {})[candidate] for candidate in candidates if candidate in (texture_entries or {})]
        for texture_source in sources:
            try:
                # Match the archive resource limit for loose files as well.
                if isinstance(texture_source, Path) and texture_source.stat().st_size > 64 * 1024 * 1024:
                    continue
                textures[name] = read_texture(texture_source.read_bytes())
                # Prepare minification levels here, on the model loader thread.
                textures[name].mipmaps
                resolved[name]=texture_source
                break
            except (OSError, ValueError):
                continue
        else:
            missing.append(name)
    return ModelPreview(mesh, textures, missing,True,resolved)


class ModelPreviewCache:
    """Bounded cache; repository resource refreshes invalidate changed assets."""
    def __init__(self,limit=8):
        self.limit=limit
        self.entries=OrderedDict()
        self.lock=Lock()

    @staticmethod
    def key(source,revision,textured,item_assets=None):
        path=source if isinstance(source,Path) else source.archive
        stat=path.stat()
        return (source,stat.st_mtime_ns,stat.st_size,revision,textured,item_assets if textured else None)

    def get(self,key):
        with self.lock:
            preview=self.entries.get(key)
            if preview is not None:self.entries.move_to_end(key)
            return preview

    def load(self,key,*args,**kwargs):
        cached=self.get(key)
        if cached is not None:return cached
        preview=load_model_preview(*args,**kwargs)
        with self.lock:
            self.entries[key]=preview
            self.entries.move_to_end(key)
            while len(self.entries)>self.limit:self.entries.popitem(last=False)
        return preview
