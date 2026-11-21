"""Project-owned replacement media. Original Gothic files are never modified."""
from pathlib import Path
import re
from uuid import uuid4

from .asset_files import AssetFiles
from .textures import read_texture, write_ztex

KINDS = ('images', 'videos')
MAX_IMAGE = 32 * 1024 * 1024
MAX_VIDEO = 512 * 1024 * 1024


class GameMedia:
    def __init__(self, project):
        self.project = Path(project).resolve()
        self.files = AssetFiles(self.project)
        self.root = self.files.root / 'Media'

    @staticmethod
    def target_name(kind, name):
        if kind not in KINDS:
            raise ValueError('Неизвестный тип медиа')
        name = AssetFiles.name(name)
        if kind == 'images':
            stem = Path(name).stem if Path(name).suffix.lower() in ('.tga', '.tex') else name
            if name != stem and Path(name).suffix.lower() not in ('.tga', '.tex'):
                raise ValueError('Название изображения должно быть TGA или TEX')
            if stem.casefold().endswith('-c'):
                stem = stem[:-2]
            if not stem or not re.fullmatch(r'[\w -]+', stem, re.ASCII):
                raise ValueError('Некорректное имя игровой текстуры')
            return stem + '-C.TEX'
        if Path(name).suffix.lower() != '.bik':
            name += '.bik' if '.' not in name else ''
        if Path(name).suffix.lower() != '.bik':
            raise ValueError('Видео Gothic должно иметь расширение .bik')
        if not re.fullmatch(r'[\w -]+\.bik', name, re.I | re.ASCII):
            raise ValueError('Некорректное имя видеоролика')
        return name

    def path(self, kind, name):
        name = self.target_name(kind, name)
        folder = self.root / kind
        target = self.files.checked(folder / name)
        return target

    def entries(self, kind):
        if kind not in KINDS:raise ValueError('Неизвестный тип медиа')
        folder = self.root / kind
        if not folder.is_dir():return []
        self.files.checked(folder)
        return sorted((path for path in folder.iterdir()
                       if path.is_file() and not path.is_symlink()
                       and path.suffix.casefold()==('.tex' if kind=='images' else '.bik')),
                      key=lambda p:p.name.casefold())

    def import_file(self, kind, name, source):
        target = self.path(kind, name)
        source = Path(source).resolve()
        if not source.is_file():raise FileNotFoundError(source)
        limit = MAX_IMAGE if kind=='images' else MAX_VIDEO
        if source.stat().st_size > limit:
            raise ValueError('Файл слишком большой для редактора медиа')
        if kind == 'images':
            if source.suffix.casefold() not in ('.tga','.tex'):
                raise ValueError('Поддерживаются изображения TGA и TEX')
            texture=read_texture(source.read_bytes())
            data=write_ztex(texture)
        else:
            with source.open('rb') as stream:
                header=stream.read(3)
            if source.suffix.casefold()!='.bik' or header!=b'BIK':
                raise ValueError('Требуется видеоролик Gothic в формате BIK')
            data=None
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary=target.with_name('.media-'+uuid4().hex+'.tmp')
        try:
            if data is not None:temporary.write_bytes(data)
            else:
                from shutil import copyfile
                copyfile(source,temporary)
            temporary.replace(target)
        finally:temporary.unlink(missing_ok=True)
        return target

    def delete(self, kind, name):
        path=self.path(kind,name)
        path.unlink()

    def collect_images(self):
        return {'_work/data/Textures/_compiled/'+path.name:path.read_bytes()
                for path in self.entries('images')}

    def videos(self):
        """BIK files are distributed separately; ZenGin reads them as loose files."""
        return self.entries('videos')
