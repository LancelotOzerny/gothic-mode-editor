"""Read Gothic preview textures without graphics dependencies.

ZTEX layout follows GothicKit/ZenKit's Texture.cc. Pixels use top-left RGBA.
These readers never convert or write game resources.
"""
from dataclasses import dataclass
from functools import cached_property
import struct


@dataclass(frozen=True)
class Texture:
    width: int
    height: int
    pixels: bytes

    @cached_property
    def mipmaps(self):
        """Cached area averages for minification, preserving premultiplied alpha."""
        levels = [self]
        source = self
        while source.width > 1 or source.height > 1:
            width, height = max(1, source.width // 2), max(1, source.height // 2)
            output = bytearray(width * height * 4)
            for y in range(height):
                y0, y1 = y * source.height // height, (y + 1) * source.height // height
                for x in range(width):
                    x0, x1 = x * source.width // width, (x + 1) * source.width // width
                    red = green = blue = alpha = 0
                    for sy in range(y0, y1):
                        for sx in range(x0, x1):
                            offset = (sy * source.width + sx) * 4
                            a = source.pixels[offset + 3]
                            red += source.pixels[offset] * a
                            green += source.pixels[offset + 1] * a
                            blue += source.pixels[offset + 2] * a
                            alpha += a
                    offset = (y * width + x) * 4
                    if alpha:
                        output[offset:offset + 4] = bytes((round(red / alpha), round(green / alpha),
                            round(blue / alpha), round(alpha / ((x1-x0)*(y1-y0)))))
            source = Texture(width, height, bytes(output))
            levels.append(source)
        return tuple(levels)


def _dimensions(width, height):
    if not (0 < width <= 8192 and 0 < height <= 8192 and width * height <= 16_777_216):
        raise ValueError('Invalid texture dimensions')


def _color(value, bits):
    if bits == 16:
        n = int.from_bytes(value, 'little')
        return bytes((((n >> 10) & 31) * 255 // 31, ((n >> 5) & 31) * 255 // 31,
                      (n & 31) * 255 // 31, 255))
    if bits == 24:
        return bytes((value[2], value[1], value[0], 255))
    if bits == 32:
        return bytes((value[2], value[1], value[0], value[3]))
    raise ValueError('Unsupported TGA pixel format')


def read_tga(data):
    if len(data) < 18:
        raise ValueError('Truncated TGA')
    ident, mapped, kind, first, colors, color_bits, _, _, width, height, bits, flags = struct.unpack_from(
        '<BBBHHBHHHHBB', data)
    _dimensions(width, height)
    if kind not in (1, 2, 3, 9, 10, 11) or mapped not in (0, 1) or flags & 0xC0:
        raise ValueError('Unsupported TGA format')
    position = 18 + ident

    def take(size):
        nonlocal position
        if position + size > len(data):
            raise ValueError('Truncated TGA pixels')
        result = data[position:position + size]
        position += size
        return result

    palette = {}
    if mapped:
        for index in range(first, first + colors):
            palette[index] = _color(take((color_bits + 7) // 8), color_bits)
    base_kind = kind - 8 if kind >= 9 else kind
    if ((base_kind == 1 and (not mapped or bits not in (8, 16)))
            or (base_kind == 2 and bits not in (16, 24, 32))
            or (base_kind == 3 and bits not in (8, 16))):
        raise ValueError('Unsupported TGA pixel format')

    def pixel():
        value = take(bits // 8)
        if base_kind == 1:
            try:
                return palette[int.from_bytes(value, 'little')]
            except KeyError as exc:
                raise ValueError('Invalid TGA palette index') from exc
        if base_kind == 3:
            return bytes((value[0], value[0], value[0], value[1] if bits == 16 else 255))
        rgba = _color(value, bits)
        if bits == 32 and not flags & 15:
            rgba = rgba[:3] + b'\xff'
        if bits == 16 and flags & 15:
            rgba = rgba[:3] + bytes((255 if value[1] & 128 else 0,))
        return rgba

    count = width * height
    pixels = bytearray()
    while len(pixels) // 4 < count:
        packet = take(1)[0] if kind >= 9 else 0
        length = (packet & 127) + 1
        if len(pixels) // 4 + length > count:
            raise ValueError('Invalid TGA packet')
        if packet & 128:
            pixels.extend(pixel() * length)
        else:
            for _ in range(length):
                pixels.extend(pixel())
    output = bytearray(len(pixels))
    for y in range(height):
        for x in range(width):
            source_x = width - 1 - x if flags & 16 else x
            source_y = y if flags & 32 else height - 1 - y
            start = (source_y * width + source_x) * 4
            target = (y * width + x) * 4
            output[target:target + 4] = pixels[start:start + 4]
    return Texture(width, height, bytes(output))


def _rgb565(number):
    return ((number >> 11) * 255 // 31, ((number >> 5) & 63) * 255 // 63,
            (number & 31) * 255 // 31)


def _dxt(data, width, height, kind):
    output = bytearray(width * height * 4)
    position = 0
    for by in range(0, height, 4):
        for bx in range(0, width, 4):
            alpha = [255] * 16
            if kind in (11, 12):
                values = int.from_bytes(data[position:position + 8], 'little')
                alpha = [((values >> (4 * i)) & 15) * 17 for i in range(16)]
                position += 8
            elif kind in (13, 14):
                a, b = data[position:position + 2]
                table = [a, b]
                if a > b:
                    table += [((7 - i) * a + i * b) // 7 for i in range(1, 7)]
                else:
                    table += [((5 - i) * a + i * b) // 5 for i in range(1, 5)] + [0, 255]
                values = int.from_bytes(data[position + 2:position + 8], 'little')
                alpha = [table[(values >> (3 * i)) & 7] for i in range(16)]
                position += 8
            a, b, indices = struct.unpack_from('<HHI', data, position)
            position += 8
            colors = [(*_rgb565(a), 255), (*_rgb565(b), 255)]
            if a > b or kind != 10:
                colors += [tuple((2 * colors[0][c] + colors[1][c]) // 3 for c in range(3)) + (255,),
                           tuple((colors[0][c] + 2 * colors[1][c]) // 3 for c in range(3)) + (255,)]
            else:
                colors += [tuple((colors[0][c] + colors[1][c]) // 2 for c in range(3)) + (255,),
                           (0, 0, 0, 0)]
            for i in range(16):
                x, y = bx + i % 4, by + i // 4
                if x >= width or y >= height:
                    continue
                rgba = colors[(indices >> (2 * i)) & 3]
                opacity = min(rgba[3], alpha[i])
                rgb = rgba[:3]
                if kind in (11, 13) and opacity:
                    rgb = tuple(min(255, c * 255 // opacity) for c in rgb)
                offset = (y * width + x) * 4
                output[offset:offset + 4] = bytes((*rgb, opacity))
    return bytes(output)


def read_ztex(data):
    if len(data) < 36 or data[:4] != b'ZTEX':
        raise ValueError('Invalid ZTEX header')
    version, kind, width, height, levels, _, _, _ = struct.unpack_from('<8I', data, 4)
    _dimensions(width, height)
    levels = max(1, levels)
    if version != 0 or kind > 14 or not 1 <= levels <= max(width, height).bit_length():
        raise ValueError('Unsupported ZTEX format')
    bytes_per_pixel = (4, 4, 4, 4, 3, 3, 2, 2, 2, 1)

    def size(w, h):
        return w * h * bytes_per_pixel[kind] if kind < 10 else ((w + 3) // 4) * ((h + 3) // 4) * (8 if kind == 10 else 16)

    offset = 36 + (1024 if kind == 9 else 0)
    # ZenGin stores mipmaps from smallest to largest.
    offset += sum(size(max(1, width >> level), max(1, height >> level)) for level in range(levels - 1, 0, -1))
    if offset + size(width, height) > len(data):
        raise ValueError('Truncated ZTEX pixels')
    pixels = data[offset:offset + size(width, height)]
    if kind >= 10:
        return Texture(width, height, _dxt(pixels, width, height, kind))
    output = bytearray()
    stride = bytes_per_pixel[kind]
    for position in range(0, len(pixels), stride):
        value = pixels[position:position + stride]
        if kind == 0:
            rgba = (value[2], value[1], value[0], value[3])
        elif kind == 1:
            rgba = tuple(value)
        elif kind == 2:
            rgba = (value[3], value[2], value[1], value[0])
        elif kind == 3:
            rgba = (value[1], value[2], value[3], value[0])
        elif kind == 4:
            rgba = (value[2], value[1], value[0], 255)
        elif kind == 5:
            rgba = (*value, 255)
        elif kind == 6:
            n = int.from_bytes(value, 'little')
            rgba = (((n >> 8) & 15) * 17, ((n >> 4) & 15) * 17, (n & 15) * 17, (n >> 12) * 17)
        elif kind == 7:
            n = int.from_bytes(value, 'little')
            rgba = (((n >> 10) & 31) * 255 // 31, ((n >> 5) & 31) * 255 // 31,
                    (n & 31) * 255 // 31, 255 if n & 32768 else 0)
        elif kind == 8:
            rgba = (*_rgb565(int.from_bytes(value, 'little')), 255)
        else:
            start = 36 + value[0] * 4
            b, g, r, a = data[start:start + 4]
            rgba = (r, g, b, a)
        output.extend(rgba)
    return Texture(width, height, bytes(output))


def read_texture(data):
    return read_ztex(data) if data.startswith(b'ZTEX') else read_tga(data)


def _pack_rgb565(r, g, b):
    return ((r * 31 + 127) // 255 << 11 |
            (g * 63 + 127) // 255 << 5 |
            (b * 31 + 127) // 255)


def _encode_dxt_block(pixels, width, height, x, y, alpha):
    """Encode one padded 4x4 block as DXT1 or DXT3 (ZenGin-compatible)."""
    block = []
    for py in range(4):
        offset_y = min(height - 1, y + py)
        for px in range(4):
            offset_x = min(width - 1, x + px)
            i = (offset_y * width + offset_x) * 4
            block.append(pixels[i:i + 4])
    # Select RGB endpoints by intensity, then quantize to RGB565.
    colors = [p[:3] for p in block]
    intensity = lambda c: c[0] * 299 + c[1] * 587 + c[2] * 114
    lo = min(colors, key=intensity)
    hi = max(colors, key=intensity)
    c0 = _pack_rgb565(*hi)
    c1 = _pack_rgb565(*lo)
    if c0 < c1:
        c0, c1 = c1, c0
    if c0 == c1:
        if c0 < 65535:c0 += 1
        else:c1 -= 1
    hi = _rgb565(c0)
    lo = _rgb565(c1)
    palette = (hi, lo,
               tuple((2 * a + b) // 3 for a, b in zip(hi, lo)),
               tuple((a + 2 * b) // 3 for a, b in zip(hi, lo)))
    indices = 0
    for i, p in enumerate(block):
        index = min(range(4), key=lambda n:
                    sum((int(p[c]) - palette[n][c]) ** 2 for c in range(3)))
        indices |= index << (2 * i)
    encoded = struct.pack('<HHI', c0, c1, indices)
    if alpha:
        a = sum(((p[3] * 15 + 127) // 255) << (4 * i)
                for i, p in enumerate(block))
        return a.to_bytes(8, 'little') + encoded
    return encoded


def write_ztex(texture):
    """Write compressed DXT1/DXT3 ZTEX supported by unpatched Gothic II.

    Native 32-bit BGRA surfaces can crash unpatched ZenGin while loading the
    texture. DXT3 is chosen when the image contains any transparency.
    """
    _dimensions(texture.width, texture.height)
    if len(texture.pixels) != texture.width * texture.height * 4:
        raise ValueError('Некорректный размер данных изображения')
    alpha = any(value < 255 for value in texture.pixels[3::4])
    kind = 12 if alpha else 10
    levels = texture.mipmaps
    data = bytearray(b'ZTEX' + struct.pack(
        '<8I', 0, kind, texture.width, texture.height, len(levels),
        texture.width, texture.height, 0))
    for level in reversed(levels):
        for y in range(0, level.height, 4):
            for x in range(0, level.width, 4):
                data.extend(_encode_dxt_block(
                    level.pixels, level.width, level.height, x, y, alpha))
    return bytes(data)

