"""GothicStarter INI generation and verified native/GothicVDFS packaging."""
import configparser
import os
from pathlib import Path
import re
import subprocess

from .build_assets import BuildAssetService
from .mod_archive import read_mod, write_mod
from .scripts import load_text

DAT_PATH = '_work/data/scripts/_compiled/gothic.dat'


def read_ini(path):
    text, _ = load_text(path)
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read_string(text)
    return parser


def generate_ini(path, config, previous=None):
    text, codec = load_text(previous) if previous is not None and previous.is_file() else ('', 'cp1251')
    # Keep custom keys, comments and launch parameters verbatim.
    def set_value(section, key, value, required=False):
        nonlocal text
        blocks = list(re.finditer(r'^[ \t]*\[([^]\r\n]+)\][^\r\n]*\r?$', text, re.M))
        block = next((match for match in blocks if match.group(1).casefold() == section.casefold()), None)
        if block is None:
            text = text.rstrip() + f'\r\n\r\n[{section}]\r\n{key}={value}\r\n'
            return
        end = next((match.start() for match in blocks if match.start() > block.start()), len(text))
        contents = text[block.end():end]
        match = re.search(r'^([ \t]*' + re.escape(key) + r'[ \t]*=[ \t]*)([^\r\n]*)', contents, re.M | re.I)
        if match:
            if required:
                start = block.end() + match.start(2)
                stop = block.end() + match.end(2)
                text = text[:start] + value + text[stop:]
        else:text = text[:end].rstrip() + f'\r\n{key}={value}\r\n' + text[end:]
    set_value('INFO', 'Title', config.title)
    set_value('INFO', 'Version', '1.0')
    set_value('FILES', 'VDF', config.filename, required=True)
    for key, value in {'Game':r'Content\Gothic', 'FightAI':r'Content\Fight', 'Menu':r'System\Menu',
                       'Camera':r'System\Camera', 'Music':r'System\Music', 'SoundEffects':r'System\SFX',
                       'ParticleEffects':r'System\ParticleFX', 'VisualEffects':r'System\VisualFX',
                       'OutputUnits':'OU'}.items():
        set_value('FILES', key, value, required=key == 'Game')
    set_value('SETTINGS', 'Player', 'PC_HERO')
    set_value('SETTINGS', 'World', r'NewWorld\NewWorld.zen')
    path.write_bytes(text.lstrip('\r\n').encode(codec))


def validate_build(archive, ini, config):
    if not archive.is_file() or not ini.is_file():raise ValueError('Нет готовой сборки MOD/INI. Сначала скомпилируйте проект.')
    files = read_mod(archive)
    if not files.get(DAT_PATH):raise ValueError('В MOD отсутствует Gothic.dat по пути _work/data/Scripts/_compiled/Gothic.dat')
    parser = read_ini(ini)
    if parser.get('FILES', 'VDF', fallback='').strip().casefold() != config.filename.casefold():
        raise ValueError('INI ссылается на другой MOD')
    if parser.get('FILES', 'Game', fallback='').replace('/', '\\').casefold() != r'content\gothic':
        raise ValueError('INI содержит неверный путь FILES.Game')
    if not parser.get('SETTINGS', 'World', fallback='').strip():raise ValueError('INI не задаёт стартовый мир')
    return files


class ModPackageService:
    def __init__(self, project, game, config):
        self.project, self.game, self.config = project, game, config
        self.assets = BuildAssetService(project)

    def packer(self):
        raw = self.config.packer_path.strip()
        if raw:
            path = Path(raw).expanduser()
            if not path.is_absolute():path = self.project / path
            if not path.is_file() or path.suffix.casefold() != '.exe':raise ValueError('Не найден упаковщик GothicVDFS: ' + str(path))
            return path.resolve()
        candidate = self.game / '_work/tools/VDFS/GothicVDFS.exe'
        return candidate if candidate.is_file() else None

    def package(self, staging, compiled, files, log):
        contents = dict(files)
        contents[DAT_PATH] = compiled.read_bytes()
        output = staging / self.config.filename
        tool = self.packer()
        if tool is None:
            log('Упаковка встроенным совместимым VDFS-упаковщиком (Gothic II, 0x50).')
            write_mod(output, contents)
        else:
            root = staging / 'volume'
            for name, data in contents.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            script = staging / 'package.vm'
            # Relative paths avoid legacy GothicVDFS limitations on long/quoted paths.
            script.write_text('[BEGINVDF]\nComment=Gothic Editor\nBaseDir=volume\nVDFName=' + output.name +
                              '\n[FILES]\n' + '\n'.join(name.replace('/', '\\') for name in contents) +
                              '\n[ENDVDF]\n', encoding='cp1251', newline='\r\n')
            command = [str(tool), '/B', str(script.resolve())]
            log(subprocess.list2cmdline(command))
            try:
                startup=None
                if os.name=='nt':
                    startup=subprocess.STARTUPINFO()
                    startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
                    startup.wShowWindow=0
                result = subprocess.run(command, cwd=staging, capture_output=True,startupinfo=startup,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, timeout=60)
            except subprocess.TimeoutExpired:
                raise ValueError('Упаковщик не завершил автоматическую сборку. Нужна версия GothicVDFS с поддержкой /B script.vm.') from None
            log(result.stdout.decode('cp1251', errors='replace'))
            log(result.stderr.decode('cp1251', errors='replace'))
            if result.returncode != 0 or not output.is_file():raise ValueError('GothicVDFS не создал MOD. См. logs/compile.log')
        actual = read_mod(output)
        if actual != {name.casefold():data for name,data in contents.items()}:
            raise ValueError('Содержимое MOD не совпадает с текущей сборкой')
        return output
