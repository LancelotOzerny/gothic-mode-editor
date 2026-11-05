"""Compiler-specific text preparation, confined to the staging tree."""
from .daedalus_merge import normalize_compiler_whitespace
from .localization import tr
from .scripts import load_text


def prepare_compiler_sources(content, report):
    for path in sorted(content.rglob('*')):
        if not path.is_file() or path.suffix.casefold() not in ('.d', '.src'):
            continue
        raw = path.read_bytes()
        prepared = raw
        if path.suffix.casefold() == '.d' and b'\x0c' in raw:
            text, codec = load_text(path)
            normalized, count = normalize_compiler_whitespace(text)
            if count:
                if codec == 'utf-8-sig' and not raw.startswith(b'\xef\xbb\xbf'):
                    codec = 'utf-8'
                prepared = normalized.encode(codec)
                report(tr('tools.normalized_whitespace', path=str(path.relative_to(content)), count=count))
        # DaedalusCompiler 0.9.2 splits diagnostic lines by Environment.NewLine.
        # LF or mixed endings otherwise make its line-number lookup crash on Windows.
        # Work on bytes to preserve CP1251, BOMs and every non-newline character.
        prepared = prepared.replace(b'\r\n', b'\n').replace(b'\r', b'\n').replace(b'\n', b'\r\n')
        if prepared != raw:
            path.write_bytes(prepared)
