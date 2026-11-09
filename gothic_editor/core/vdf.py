"""Read standard Gothic VDF/MOD catalogs without unpacking entire archives.

Format reference: https://zk.gothickit.dev/engine/formats/vdf/
Only uncompressed volumes (0x50) are supported.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from .localization import tr


class VdfFormatError(ValueError):
    pass


@dataclass(frozen=True)
class VdfEntry:
    archive: Path
    name: str
    offset: int
    size: int

    def read_bytes(self) -> bytes:
        with self.archive.open('rb') as stream:
            stream.seek(self.offset)
            data = stream.read(self.size)
        if len(data) != self.size:
            raise VdfFormatError(tr('viewer.invalid_vdf'))
        return data


class VdfArchive:
    HEADER = struct.Struct('<256s16s6I')
    RECORD = struct.Struct('<64s4I')
    SIGNATURES = (b'PSVDSC_V2.00\r\n\r\n', b'PSVDSC_V2.00\n\r\n\r',
                  b'PSVDSC_V2.00\x1a\x1a\x1a\x1a')
    MAX_MODEL_BYTES = 64 * 1024 * 1024

    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries = {}
        with self.path.open('rb') as stream:
            length = stream.seek(0, 2)
            stream.seek(0)
            header = stream.read(self.HEADER.size)
            if len(header) != self.HEADER.size:
                raise VdfFormatError(tr('viewer.invalid_vdf'))
            _, signature, count, _, self.timestamp, _, catalog, version = self.HEADER.unpack(header)
            if signature not in self.SIGNATURES:
                raise VdfFormatError(tr('viewer.invalid_vdf'))
            if version not in (0x50, 0xA0):
                raise VdfFormatError(tr('viewer.unsupported_vdf', version=hex(version)))
            if (catalog < self.HEADER.size or count > 1_000_000
                    or catalog + count * self.RECORD.size > length):
                raise VdfFormatError(tr('viewer.invalid_vdf'))
            stream.seek(catalog)
            # Catalog entries contain basenames; Gothic visuals resolve by basename.
            for _ in range(count):
                raw_name, offset, size, flags, _ = self.RECORD.unpack(stream.read(self.RECORD.size))
                if flags & 0x80000000:
                    continue
                name = raw_name.split(b'\0', 1)[0].rstrip(b' \x1a').decode('cp1251')
                if Path(name).suffix.lower() not in ('.mrm', '.3ds', '.tex', '.tga'):
                    continue
                if version != 0x50:
                    raise VdfFormatError(tr('viewer.unsupported_vdf', version=hex(version)))
                if offset < self.HEADER.size or offset + size > length or size > self.MAX_MODEL_BYTES:
                    raise VdfFormatError(tr('viewer.invalid_vdf'))
                self.entries.setdefault(name.replace('\\', '/').rsplit('/', 1)[-1].lower(),
                                        VdfEntry(self.path, name, offset, size))
