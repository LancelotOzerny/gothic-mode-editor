"""Load static preview geometry and its textures off the UI thread."""
from dataclasses import dataclass
from pathlib import Path

from .mesh import PreviewMesh, read_3ds_bytes, read_mrm
from .textures import Texture, read_texture


@dataclass
class ModelPreview:
    mesh: PreviewMesh
    textures: dict[str, Texture]
    missing: list[str]


def texture_candidates(name):
    name = name.replace('\\', '/').rsplit('/', 1)[-1].lower()
    stem = Path(name).stem
    candidates = [name]
    if not stem.endswith('-c'):
        candidates.append(stem + '-c.tex')
    candidates.extend((stem + '.tex', stem + '.tga'))
    return list(dict.fromkeys(candidates))


def load_model_preview(source, project, game=None, item_assets=None, texture_entries=None):
    data = source.read_bytes()
    name = source.name
    mesh = read_3ds_bytes(data, preview=True) if Path(name).suffix.lower() == '.3ds' else read_mrm(data, preview=True)
    if not any(mesh.texture_names):
        return ModelPreview(mesh, {}, [])
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
                for path in sorted(directory.rglob('*')):
                    if path.is_file() and path.suffix.lower() in ('.tga', '.tex'):
                        index.setdefault(path.name.lower(), path)
        except OSError:
            pass  # An inaccessible texture folder must not hide valid geometry.
        indexes.append(index)
    textures, missing = {}, []
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
                break
            except (OSError, ValueError):
                continue
        else:
            missing.append(name)
    return ModelPreview(mesh, textures, missing)
