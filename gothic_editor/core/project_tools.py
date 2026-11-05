"""Build and synchronize project scripts using an existing DaedalusCompiler."""
from __future__ import annotations

import fnmatch
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .localization import tr
from .scripts import load_text
from .daedalus_merge import merge_project_scripts,target_path
from .potion_build import apply_potions
from .compiler_sources import prepare_compiler_sources
from .compiler_runner import run_compiler


@dataclass(frozen=True)
class ToolResult:
    output: Path
    files: int = 0
    backup: Path | None = None
    warnings: int = 0


class ProjectTools:
    def __init__(self, project: Path, game: Path | None, compiler_path: str = ''):
        self.project = Path(project).resolve()
        if game is None:
            raise ValueError(tr('tools.game_required'))
        self.game = Path(game).resolve()
        if self.project == self.game or self.project in self.game.parents or self.game in self.project.parents:
            raise ValueError(tr('project.overlapping_roots'))
        self.source = self.project / 'Scripts' / 'Content'
        self.target = self.game / '_work' / 'Data' / 'Scripts' / 'Content'
        self.build_dir = self.project / 'build'
        self.compiler_path = compiler_path
        for path in (self.source, self.target):
            if not path.is_dir():
                raise ValueError(tr('tools.missing', path=str(path)))
        self._inside(self.source, self.project)
        self._inside(self.target, self.game)
        self._inside(self.build_dir, self.project)

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
        content = staging / 'Content'
        content.mkdir()
        report(tr('tools.preparing'))
        for source in self._files(self.target):
            destination = content / source.relative_to(self.target)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        self._files(self.source)  # Validate project paths before reading overlay files.
        project_files = merge_project_scripts(content,self.source)
        for generated in apply_potions(self.project,content):
            if generated not in project_files:project_files.append(generated)
        manifest = self._include_project_scripts(content, project_files)
        return content, manifest, project_files

    def compile(self, report=lambda _message: None):
        command = self.compiler_command()  # Validate dependencies before preparing a build.
        self.build_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.build_dir / 'compile.log'
        output = self.build_dir / 'Gothic.dat'
        log_path.write_text('', encoding='utf-8')
        staging = self._inside(Path(tempfile.mkdtemp(prefix='compile-', dir=self.build_dir)), self.build_dir.resolve())
        try:
            content, manifest, _ = self._prepare(staging, report)
            prepare_compiler_sources(content,report)
            temporary_output = staging / 'Gothic.dat'
            command.extend((str(manifest), '--output-dat', str(temporary_output)))
            report(tr('tools.compiling'))
            result = run_compiler(command, staging, log_path)
            if result.returncode != 0 or not temporary_output.is_file() or not temporary_output.stat().st_size:
                raise ValueError(tr('tools.compile_failed', code=result.returncode, log=str(log_path)))
            temporary_output.replace(output)
        except Exception:
            report(tr('tools.failed_sources', path=str(staging)))
            raise
        else:
            # Successful process diagnostics remain next to compile.log; large
            # source copies are retained only when a build needs investigation.
            for name in ('diagnostics.json', 'stdout.log', 'stderr.log'):
                shutil.copy2(staging / name, self.build_dir / name)
            shutil.rmtree(staging)
        warnings=len(re.findall(r'\bwarning\s+W\d+\s*:',log_path.read_text('utf-8',errors='replace'),flags=re.IGNORECASE))
        return ToolResult(output,warnings=warnings)

    def synchronize(self, report=lambda _message: None):
        self.build_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='sync-', dir=self.build_dir) as temporary:
            staging = self._inside(Path(temporary), self.build_dir.resolve())
            content, _, project_files = self._prepare(staging, report)
            paths = list(dict.fromkeys([*project_files, Path('Gothic.src')]))
            changes = []
            for relative in paths:
                source, target = content / relative, self.target / relative
                self._inside(target, self.game)
                if not target.is_file() or source.read_bytes() != target.read_bytes():
                    changes.append((source, target, relative))
            backup = self.project / 'backups' / ('sync-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8])
            self._inside(backup, self.project)
            # Back up every overwritten file before writing the first change.
            for _, target, relative in changes:
                if target.is_file():
                    destination = backup / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, destination)
            report(tr('tools.syncing', count=len(changes)))
            written = []
            try:
                for source, target, relative in changes:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    written.append((target, relative))
                    shutil.copy2(source, target)
            except OSError:
                for target, relative in reversed(written):
                    original = backup / relative
                    if original.is_file():
                        shutil.copy2(original, target)
                    elif target.is_file():
                        target.unlink()
                raise
            return ToolResult(self.target, len(changes), backup if backup.is_dir() else None)
