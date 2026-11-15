"""Build and synchronize project scripts using an existing DaedalusCompiler."""
from __future__ import annotations

import fnmatch
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .localization import tr
from .scripts import load_text
from .daedalus_merge import merge_project_scripts,target_path
from .potion_build import apply_potions
from .item_layout import project_scripts
from .compiler_sources import prepare_compiler_sources
from .compiler_runner import run_compiler
from .mod_config import ModConfiguration
from .mod_package import ModPackageService, generate_ini, validate_build
from .artifact_transaction import publish_files


@dataclass(frozen=True)
class ToolResult:
    output: Path
    files: int = 0
    backup: Path | None = None
    warnings: int = 0
    archive: Path | None = None
    operation: str = 'compile'
    manual: bool = False


class ProjectTools:
    def __init__(self, project: Path, game: Path | None, compiler_path: str = ''):
        self.project = Path(project).resolve()
        if game is None:
            raise ValueError(tr('tools.game_required'))
        self.game = Path(game).resolve()
        if self.project == self.game or self.project in self.game.parents or self.game in self.project.parents:
            raise ValueError(tr('project.overlapping_roots'))
        self.source = project_scripts(self.project) / 'Content'
        self.target = self.game / '_work' / 'Data' / 'Scripts' / 'Content'
        self.dist_dir = self.project / 'dist'
        self.logs_dir = self.project / 'logs'
        self.build_dir = self.dist_dir  # Compatibility for callers preparing isolated source fixtures.
        self.compiler_path = compiler_path
        self.config = ModConfiguration.load(self.project)
        self._inside(self.source, self.project)
        self._inside(self.target, self.game)
        self._inside(self.dist_dir, self.project)
        self._inside(self.logs_dir, self.project)

    @staticmethod
    def _inside(path: Path, root: Path):
        resolved = path.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError(tr('tools.unsafe_path', path=str(path)))
        return path

    def _files(self, root):
        files = []
        for path in sorted(root.rglob('*')):
            self._inside(path, root.resolve())
            if path.is_file():
                files.append(path)
        return files

    def compiler_command(self):
        candidates = []
        if self.compiler_path.strip():
            configured = Path(self.compiler_path.strip()).expanduser()
            if not configured.is_absolute():
                configured = self.project / configured
            candidates.append(configured)
        else:
            for parent in dict.fromkeys((self.project.parent, self.game.parent)):
                root = parent / 'DaedalusCompiler'
                candidates.extend((root / 'DaedalusCompiler.exe', root / 'DaedalusCompiler.dll'))
                candidates.extend(sorted((root / 'src/DaedalusCompiler/bin/Release').glob('*/DaedalusCompiler.dll'), reverse=True))
        compiler = next((path.resolve() for path in candidates if path.is_file()), None)
        if compiler is None:
            raise ValueError(tr('tools.compiler_missing'))
        if compiler.suffix.lower() == '.dll':
            dotnet = shutil.which('dotnet')
            if dotnet is None:
                raise ValueError(tr('tools.dotnet_missing'))
            return [dotnet, str(compiler)]
        if compiler.suffix.lower() != '.exe':
            raise ValueError(tr('tools.compiler_missing'))
        return [str(compiler)]

    @staticmethod
    def _include_project_scripts(content: Path, project_files):
        manifest = target_path(content,Path('Gothic.src'))
        if not manifest.is_file():
            raise ValueError(tr('tools.missing', path=str(manifest)))
        text, codec = load_text(manifest)
        included = set()
        visited = set()

        def visit(path):
            path = path.resolve()
            ProjectTools._inside(path, content.resolve())
            if path in visited:
                return
            visited.add(path)
            source, _ = load_text(path)
            for raw in source.splitlines():
                pattern = raw.split('//', 1)[0].strip().replace('\\', '/')
                if not pattern:
                    continue
                # Match each path component separately: '*' cannot swallow directories.
                matches = [path.parent]
                for part in pattern.split('/'):
                    if part in ('.', ''):
                        continue
                    if part == '..':
                        matches = [match.parent for match in matches]
                    else:
                        matches = [child for match in matches if match.is_dir() for child in match.iterdir()
                                   if fnmatch.fnmatchcase(child.name.lower(), part.lower())]
                for match in matches:
                    ProjectTools._inside(match, content.resolve())
                    if match.suffix.lower() == '.src':
                        visit(match)
                    elif match.is_file():
                        included.add(match.relative_to(content).as_posix().lower())

        visit(manifest)
        missing = [path for path in project_files if path.suffix.lower() == '.d'
                   and path.as_posix().lower() not in included]
        if missing:
            lines = text.splitlines()
            # Insert each new script after the existing entries for its top-level section.
            for path in reversed(missing):
                section = path.parts[0].lower() if len(path.parts) > 1 else ''
                index = max((i + 1 for i, line in enumerate(lines)
                             if line.strip().replace('\\', '/').lower().startswith(section + '/')),
                            default=len(lines))
                lines.insert(index, str(path).replace('/', '\\'))
            manifest.write_text('\r\n'.join(lines) + '\r\n', encoding=codec, newline='')
        return manifest

    def _prepare(self, staging, report):
        if not self.target.is_dir():raise ValueError(tr('tools.missing', path=str(self.target)))
        if self.source.exists() and not self.source.is_dir():
            raise ValueError(tr('tools.missing', path=str(self.source)))
        content = staging / 'Content'
        content.mkdir()
        report(tr('tools.preparing'))
        for source in self._files(self.target):
            destination = content / source.relative_to(self.target)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        project_files = []
        if self.source.is_dir():
            self._files(self.source)  # Validate paths before reading overlay files.
            project_files = merge_project_scripts(content,self.source)
        for generated in apply_potions(self.project,content):
            if generated not in project_files:project_files.append(generated)
        from .npcs import apply_npc_overrides
        for changed in apply_npc_overrides(self.project,content):
            if changed not in project_files:project_files.append(changed)
        manifest = self._include_project_scripts(content, project_files)
        return content, manifest, project_files

    @staticmethod
    def _publish_artifacts(staging, pairs, commit=lambda:None):
        publish_files(pairs,commit)

    def compile(self, report=lambda _message: None):
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.logs_dir / 'compile.log'
        log_path.write_text('', encoding='utf-8')
        def emit(message):
            with log_path.open('a',encoding='utf-8') as stream:stream.write(message+'\n')
            report(message)
        try:
            command = self.compiler_command()
            package = ModPackageService(self.project,self.game,self.config)
            package.packer()  # Fail before compilation for an invalid explicitly configured tool.
            with tempfile.TemporaryDirectory(prefix='gothic-compile-') as temporary:
                staging=Path(temporary)
                content, manifest, _ = self._prepare(staging, emit)
                prepare_compiler_sources(content,emit)
                temporary_output = staging / 'Gothic.dat'
                command.extend((str(manifest), '--output-dat', str(temporary_output)))
                emit(tr('tools.compiling'))
                try:result = run_compiler(command, staging, staging/'compiler.log')
                finally:
                    for name in ('diagnostics.json','stdout.log','stderr.log'):
                        if (staging/name).is_file():shutil.copy2(staging/name,self.logs_dir/('compiler.'+name))
                    if (staging/'compiler.log').is_file():
                        with log_path.open('a',encoding='utf-8') as stream:
                            stream.write((staging/'compiler.log').read_text('utf-8'))
                if result.returncode != 0 or not temporary_output.is_file() or not temporary_output.stat().st_size:
                    raise ValueError(tr('tools.compile_failed', code=result.returncode, log=str(log_path)))
                emit(tr('pipeline.packaging'))
                assets=package.assets.collect()
                temporary_archive=package.package(staging,temporary_output,assets,emit)
                temporary_ini=staging/self.config.ini_name
                generate_ini(temporary_ini,self.config,self.dist_dir/self.config.ini_name)
                packed=validate_build(temporary_archive,temporary_ini,self.config)
                from .mod_package import DAT_PATH
                if packed[DAT_PATH]!=temporary_output.read_bytes():raise ValueError('MOD содержит устаревший Gothic.dat')
                archive=self.dist_dir/self.config.filename
                ini=self.dist_dir/self.config.ini_name
                pairs=[(temporary_archive,archive),(temporary_ini,ini)]
                pairs.append((temporary_output if self.config.keep_dat else None,self.dist_dir/'Gothic.dat'))
                def verify():
                    if validate_build(archive,ini,self.config)!=packed:raise ValueError('Опубликованный MOD не совпадает с проверенной сборкой')
                self._publish_artifacts(staging,pairs,commit=verify)
                emit(tr('item_assets.packaged', path=str(archive), count=len(assets)))
        except Exception as exc:
            emit(str(exc))
            raise
        warnings=len(re.findall(r'\bwarning\s+W\d+\s*:',log_path.read_text('utf-8',errors='replace'),flags=re.IGNORECASE))
        return ToolResult(archive,warnings=warnings,archive=archive)

    def synchronize(self, report=lambda _message: None):
        from .mod_install import ModInstallerService
        return ModInstallerService(self.project,self.game,self.config).install(report)

    def launch(self, report=lambda _message: None):
        from .mod_launch import ModLauncherService
        return ModLauncherService(self.project,self.game,self.config).launch(report)

    def build_and_run(self, report=lambda _message: None):
        from .build_pipeline import BuildPipeline
        return BuildPipeline(self).run(report)


# The existing preparation/compiler service remains the single implementation.
CompilationService = ProjectTools
