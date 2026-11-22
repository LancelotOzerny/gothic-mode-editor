"""Texture names in MRM's embedded ZenGin binary material archive.

Format reference: GothicKit/ZenKit ArchiveBinary.cc and Material.cc.
Unsupported/missing material data leaves the validated geometry viewable.
"""
import re
import struct


def mrm_textures(data, count):
    return [texture for _,texture in mrm_materials(data,count)]


def mrm_materials(data, count):
    result = [('', '')] * count
    if not data.startswith(b'ZenGin Archive'):
        return result
    header = re.search(rb'\bBINARY\r?\n.*?\r?\nEND\r?\nobjects [^\n]*\nEND\r?\n(?:\r?\n)?', data, re.S)
    if header is None:
        return result
    position = header.end()
    if position + 4 > len(data):
        return result
    declared = struct.unpack_from('<i', data, position)[0]
    if declared < 0 or declared > 65535:
        return result
    position += 4

    def string(limit):
        nonlocal position
        end = data.find(b'\0', position, limit)
        if end < 0:
            raise ValueError('Invalid material string')
        value = data[position:end].decode('cp1251')
        position = end + 1
        return value

    for index in range(min(count, declared)):
        try:
            string(len(data))  # external material name
            start = position
            size, _, _ = struct.unpack_from('<IHI', data, position)
            end = start + size
            if size < 12 or end > len(data):
                break
            position += 10
            string(end)  # object name
            if string(end) != 'zCMaterial':
                break
            name = string(end)
            position += 9  # group byte, BGRA colour, smooth angle
            if position > end:
                break
            result[index] = (name, string(end))
            position = end
        except (ValueError, struct.error):
            break
    return result
