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
        if path.suffix.casefold() == '.d':
            text, codec = load_text(path)
            normalized, count = normalize_compiler_whitespace(text) if '\f' in text else (text,0)
            if codec=='utf-8-sig':
                try:prepared=normalized.encode('cp1251')
                except UnicodeEncodeError as exc:
                    raise ValueError(f'{path}: текст не представим в Windows-1251 для Gothic.') from exc
                if prepared!=raw and (raw.startswith(b'\xef\xbb\xbf') or any(byte>=128 for byte in raw)):
                    report(tr('tools.normalized_encoding',path=str(path.relative_to(content))))
            elif count:prepared=normalized.encode(codec)
            if count:
                report(tr('tools.normalized_whitespace', path=str(path.relative_to(content)), count=count))
        # DaedalusCompiler 0.9.2 splits diagnostic lines by Environment.NewLine.
        # LF or mixed endings otherwise make its line-number lookup crash on Windows.
        # Preserve existing ANSI bytes; UTF-8 scripts above are converted only in staging.
        prepared = prepared.replace(b'\r\n', b'\n').replace(b'\r', b'\n').replace(b'\n', b'\r\n')
        if prepared != raw:
            path.write_bytes(prepared)
