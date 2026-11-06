"""Uncompressed Gothic II VDFS writer and full-path verification reader.

Format: https://zk.gothickit.dev/engine/formats/vdf/
"""
from datetime import datetime, timezone
from pathlib import PurePosixPath
import struct

from .vdf import VdfArchive, VdfFormatError


def write_mod(path, files):
    tree = {}
    paths = set()
    for name, data in files.items():
        key = name.replace('\\', '/').casefold()
        if key in paths:raise ValueError('Конфликт пути MOD: ' + name)
        paths.add(key)
        parts = PurePosixPath(name.replace('\\', '/')).parts
        if not parts or any(part in ('..', '/', '.') for part in parts):
            raise ValueError('Недопустимый путь в MOD: ' + name)
        node = tree
        for part in parts[:-1]:node = node.setdefault(part, {})
        if parts[-1] in node:raise ValueError('Конфликт пути MOD: ' + name)
        node[parts[-1]] = data
    records = []

    def catalog(node):
        start = len(records)
        children = sorted(node.items(), key=lambda pair: pair[0].casefold())
        records.extend([None] * len(children))
        for index, (name, value) in enumerate(children):
            flags = 0x40000000 if index == len(children) - 1 else 0
            if isinstance(value, dict):
                records[start + index] = (name, catalog(value), b'', flags | 0x80000000)
            else:records[start + index] = (name, 0, value, flags)
        return start
    catalog(tree)
    offset = VdfArchive.HEADER.size + len(records) * VdfArchive.RECORD.size
    entries, payload = [], []
    for name, child, data, flags in records:
        encoded = name.encode('cp1251')
        if len(encoded) > 63:raise ValueError('Слишком длинное имя ресурса MOD: ' + name)
        directory = flags & 0x80000000
        entries.append(VdfArchive.RECORD.pack(encoded.ljust(64, b' '), child if directory else offset,
                                               len(data), flags, 0))
        if not directory:
            payload.append(data)
            offset += len(data)
    now = datetime.now(timezone.utc)
    timestamp = ((now.year - 1980) << 25 | now.month << 21 | now.day << 16 |
                 now.hour << 11 | now.minute << 5 | now.second // 2)
    header = VdfArchive.HEADER.pack(b'Gothic Editor'.ljust(256, b'\x1a'), VdfArchive.SIGNATURES[1],
        len(records), len(files), timestamp, offset, VdfArchive.HEADER.size, 0x50)
    path.write_bytes(header + b''.join(entries) + b''.join(payload))
    # Check directory links and actual packed bytes, not only the source list.
    actual = read_mod(path)
    expected = {name.replace('\\', '/').casefold(): data for name, data in files.items()}
    if actual != expected:raise VdfFormatError('Проверка содержимого MOD не пройдена')


def read_mod(path):
    data = path.read_bytes()
    if len(data) < VdfArchive.HEADER.size:raise VdfFormatError('Повреждён MOD')
    _, signature, count, file_count, _, size, offset, version = VdfArchive.HEADER.unpack_from(data)
    if (signature not in VdfArchive.SIGNATURES or version != 0x50 or size != len(data)
            or offset < VdfArchive.HEADER.size or offset + count * 80 > len(data)):
        raise VdfFormatError('Повреждён заголовок MOD')
    records = [VdfArchive.RECORD.unpack_from(data, offset + index * 80) for index in range(count)]
    visited, files = set(), {}

    def directory(index, prefix, depth=0):
        if depth > 32:raise VdfFormatError('Повреждён каталог MOD')
        while True:
            if index >= count or index in visited:raise VdfFormatError('Повреждён каталог MOD')
            visited.add(index)
            raw, position, length, flags, _ = records[index]
            name = raw.rstrip(b' \0\x1a').decode('cp1251')
            key = (prefix + name).casefold()
            if flags & 0x80000000:directory(position, prefix + name + '/', depth + 1)
            else:
                if position < offset + count * 80 or position + length > len(data) or key in files:
                    raise VdfFormatError('Повреждён ресурс MOD: ' + key)
                files[key] = data[position:position + length]
            if flags & 0x40000000:break
            index += 1
    if count:directory(0, '')
    if len(visited) != count or len(files) != file_count:raise VdfFormatError('Неполный каталог MOD')
    return files
