"""Project-owned replacement media. Original Gothic files are never modified."""
from pathlib import Path
import re
from uuid import uuid4

from .asset_files import AssetFiles
from .textures import read_texture, write_ztex, Texture
from dataclasses import dataclass

KINDS = ('images', 'videos')
CATEGORIES = {'menu':'Главное меню', 'chapters':'Главы и загрузка',
              'images':'Прочие изображения', 'videos':'Видеоролики'}


def media_category(name, kind='images'):
    if kind=='videos':return 'videos'
    stem=Path(name).stem.casefold()
    if any(word in stem for word in ('chapter','kapitel','loading','loadscreen','intro_chapter')):
        return 'chapters'
    if any(word in stem for word in ('menu','startscreen','logo','title','background','startbild')):
        return 'menu'
    return 'images'


@dataclass(frozen=True)
class MediaResource:
    name: str
    kind: str
    source: object
    category: str
    overridden: bool = False

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

    def catalog(self, archive_models=None, game=None):
        """Enumerate original media without extracting archives to disk."""
        found = {}
        if archive_models is not None:
            for name, entry in archive_models.texture_entries.items():
                if Path(name).suffix.lower() in ('.tex','.tga'):
                    logical=self.target_name('images', name)
                    found[('images',logical.casefold())] = MediaResource(
                        logical,'images',entry,media_category(logical))
        if game:
            game=Path(game)
            for folder in (game/'_work'/'Data'/'Textures'/'_compiled',game/'_work'/'Data'/'Textures'):
                if folder.is_dir():
                    for path in folder.rglob('*'):
                        if path.is_file() and path.suffix.lower() in ('.tex','.tga'):
                            logical=self.target_name('images',path.name)
                            found[('images',logical.casefold())]=MediaResource(
                                logical,'images',path,media_category(logical))
            videos=game/'_work'/'Data'/'Video'
            if videos.is_dir():
                for path in videos.rglob('*.bik'):
                    if path.is_file():
                        found[('videos',path.name.casefold())]=MediaResource(
                            path.name,'videos',path,'videos')
        for kind in KINDS:
            for path in self.entries(kind):
                key=(kind,path.name.casefold())
                old=found.get(key)
                found[key]=MediaResource(path.name,kind,path,
                    old.category if old else media_category(path.name,kind),True)
        return sorted(found.values(),key=lambda row:(list(CATEGORIES).index(row.category),row.name.casefold()))

    def replace_image(self, name, source):
        """PNG/JPEG are decoded to RGBA then stored as native Gothic TEX."""
        source=Path(source)
        if source.suffix.lower() in ('.tga','.tex'):
            return self.import_file('images',name,source)
        if source.suffix.lower() not in ('.png','.jpg','.jpeg'):
            raise ValueError('Выберите PNG, JPEG, TGA или TEX')
        try:
            from PIL import Image
        except ImportError as exc:
            raise ValueError('Для конвертации PNG/JPEG необходим Pillow (pip install Pillow).') from exc
        with Image.open(source) as image:
            if image.width>8192 or image.height>8192 or image.width*image.height>16_777_216:
                raise ValueError('Изображение слишком большое')
            image=image.convert('RGBA')
            texture=Texture(image.width,image.height,image.tobytes())
        target=self.path('images',name)
        target.parent.mkdir(parents=True,exist_ok=True)
        temp=target.with_name('.media-'+uuid4().hex+'.tmp')
        try:
            temp.write_bytes(write_ztex(texture))
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
        return target

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
