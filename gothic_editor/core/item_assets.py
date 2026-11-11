"""Import shared project models and back up changes to their textures."""
import shutil
import struct
import tempfile
from pathlib import Path
from uuid import uuid4

from .item_layout import ItemLayout
from .mesh import MeshFormatError, read_3ds_bytes
from .texture_names import texture_candidates
from .model_library import ModelLibrary
from .potion_components import PotionComponents


_TEXTURE_CONTAINERS = {0x4D4D, 0x3D3D, 0xAFFF, 0xA200, 0xA204, 0xA210, 0xA220,
                       0xA230, 0xA33A, 0xA33C, 0xA33D, 0xA33E, 0xA340, 0xA342, 0xA344, 0xA346, 0xA348}


def texture_references(data):
    """Read 3DS material map filenames, preserving their original spelling."""
    result = []

    def visit(start, end, depth=0):
        if depth > 32:raise MeshFormatError('Слишком глубокая структура 3DS')
        while start < end:
            if start + 6 > end:raise MeshFormatError('Повреждённый блок 3DS')
            kind, size = struct.unpack_from('<HI', data, start)
            stop = start + size
            if size < 6 or stop > end:raise MeshFormatError('Повреждённый блок 3DS')
            if kind in _TEXTURE_CONTAINERS:visit(start + 6, stop, depth + 1)
            elif kind == 0xA300:
                value = data[start + 6:stop].split(b'\0', 1)[0].decode('cp1251')
                if value:result.append(value)
            start = stop
    visit(0, len(data))
    return tuple(dict.fromkeys(result))


def replace_texture_references(data, replacements):
    """Change only material filename chunks, updating their enclosing chunk sizes."""
    if not replacements:return data

    def visit(start, end, depth=0):
        if depth > 32:raise MeshFormatError('Слишком глубокая структура 3DS')
        chunks = []
        while start < end:
            if start + 6 > end:raise MeshFormatError('Повреждённый блок 3DS')
            kind, size = struct.unpack_from('<HI', data, start)
            stop = start + size
            if size < 6 or stop > end:raise MeshFormatError('Повреждённый блок 3DS')
            payload = data[start + 6:stop]
            if kind in _TEXTURE_CONTAINERS:
                payload = visit(start + 6, stop, depth + 1)
            elif kind == 0xA300:
                value, separator, trailing = payload.partition(b'\0')
                replacement = replacements.get(value.decode('cp1251'))
                if replacement is not None:
                    payload = replacement.encode('cp1251') + (separator or b'\0') + trailing
            chunks.append(struct.pack('<HI', kind, len(payload) + 6) + payload)
            start = stop
        return b''.join(chunks)

    return visit(0, len(data))


class ItemAssetManager:
    def __init__(self, project):
        self.layout = ItemLayout(project)
        self.library = ModelLibrary(project)
        self.store = PotionComponents(project)

    def _folder(self, item):
        if item.origin != 'project' or not self.layout.owns(item.path):
            raise ValueError('Сначала скопируйте зелье в проект')
        return self.library.folder_for(item.visual)

    def _change(self, item, operation):
        assets = self._folder(item)
        for path in assets.rglob('*'):
            self.layout.checked(path)
        temporary = Path(tempfile.mkdtemp(prefix='.assets-', dir=self.layout.project))
        backup = None
        moved = False
        try:
            staged = temporary / 'assets'
            if assets.exists():shutil.copytree(assets, staged)
            else:staged.mkdir()
            operation(staged)
            if assets.exists():
                backup = self.layout.project / 'backups' / ('model-assets-' + uuid4().hex) / assets.name
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(assets, backup)
                assets.rename(temporary / 'previous')
                moved = True
            try:staged.rename(assets)
            except Exception:
                if moved:(temporary / 'previous').rename(assets)
                raise
        finally:
            shutil.rmtree(temporary)
        return backup

    def import_model(self, item, source):
        source = Path(source)
        if source.suffix.lower() != '.3ds':raise ValueError('Выберите модель .3ds')
        data = source.read_bytes()
        read_3ds_bytes(data)
        references = texture_references(data)

        existing=next((path for path in self.library.index().values()
                       if path.resolve()==source.resolve()),None)
        if existing is not None:
            self.store.edit(item,{'visual':'"'+self.library.name(existing)+'"'})
            return existing
        textures={path.name.casefold():path for path in source.parent.iterdir() if path.is_file()}
        selected=[]
        for reference in references:
            texture=next((textures[name] for name in texture_candidates(reference)
                          if name in textures and textures[name].suffix.lower() in ('.tga','.tex')),None)
            if texture is not None and texture not in selected:selected.append(texture)
        model=self.library.create(source.stem,data,selected)
        try:self.store.edit(item,{'visual':'"'+self.library.name(model)+'"'})
        except Exception:
            shutil.rmtree(model.parent)
            raise
        return model

    def import_textures(self, item, sources):
        sources = [Path(path) for path in sources]
        if any(path.suffix.lower() not in ('.tga', '.tex') for path in sources):
            raise ValueError('Поддерживаются текстуры .tga и .tex')
        def operation(folder):
            for source in sources:shutil.copy2(source, folder / source.name)
        return self._change(item, operation)

    def remove_model(self, item):
        # Detach this item; other items can still use the shared resource.
        return self.store.edit(item,{'visual':'""'})
