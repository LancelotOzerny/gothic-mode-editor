"""Run a compiler and retain reproducible, separate process diagnostics."""
import json
import os
import subprocess
from pathlib import Path


def run_compiler(command, staging: Path, log_path: Path):
    environment = os.environ.copy()
    environment['DOTNET_ROLL_FORWARD'] = 'Major'
    # Record compiler/runtime settings, not unrelated credentials in the environment.
    keys = ('PATH', 'DOTNET_ROLL_FORWARD', 'DOTNET_ROOT', 'DOTNET_ROOT_X64',
            'DOTNET_MULTILEVEL_LOOKUP', 'DOTNET_ROLL_FORWARD_TO_PRERELEASE',
            'DOTNET_ADDITIONAL_DEPS', 'DOTNET_SHARED_STORE')
    diagnostic = {
        'command': command, 'command_line': subprocess.list2cmdline(command),
        'cwd': str(staging), 'sources': str(staging / 'Content'),
        'environment': {key: environment[key] for key in keys if key in environment},
        'stdout': str(staging / 'stdout.log'), 'stderr': str(staging / 'stderr.log'),
    }
    metadata = staging / 'diagnostics.json'

    def save():
        metadata.write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding='utf-8')

    save()
    try:
        with (staging / 'stdout.log').open('w', encoding='utf-8') as stdout, \
                (staging / 'stderr.log').open('w', encoding='utf-8') as stderr:
            result = subprocess.run(command, cwd=staging, env=environment,
                                    stdout=stdout, stderr=stderr, creationflags=(
                                        subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
        diagnostic['returncode'] = result.returncode
        return result
    except Exception as exc:
        diagnostic['exception'] = repr(exc)
        raise
    finally:
        save()
        with log_path.open('w', encoding='utf-8') as log:
            log.write(diagnostic['command_line'] + '\n')
            log.write('Diagnostics: ' + str(metadata) + '\n')
            log.write('DOTNET_ROLL_FORWARD=Major\n')
            for channel in ('stdout', 'stderr'):
                log.write('\n--- ' + channel + ' ---\n')
                path = staging / (channel + '.log')
                if path.is_file():
                    log.write(path.read_text('utf-8', errors='replace'))
            if 'exception' in diagnostic:
                log.write('\n' + diagnostic['exception'] + '\n')
