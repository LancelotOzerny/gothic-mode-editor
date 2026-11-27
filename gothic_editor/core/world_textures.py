"""Read-only, asynchronous resolution of original Gothic world textures.

Decoding runs outside Tk/OpenGL. All graphics operations remain with the view.
"""
from __future__ import annotations

from array import array
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import struct
from .world_streaming import WorldDiskCache, source_stamp

from .texture_names import texture_candidates
from .textures import Texture, read_texture


class WorldTextures:
    def __init__(self, sources, *, loose_roots=(), max_ready_bytes=512 * 1024 * 1024,
                 workers=4, cache=None):
        self.sources = {Path(name.replace('\\', '/')).name.casefold(): source
                        for name, source in sources.items()}
        self._executor = ThreadPoolExecutor(max_workers=workers)
        self.cache = cache
        self._cache_hits = 0
        self._cache_misses = 0
        self._index_future = self._executor.submit(self._index_loose, tuple(loose_roots)) if loose_roots else None
        self._pending = {}
        self._alpha = {}
        self._max_pending = max(8, workers * 4)
        self._ready = OrderedDict()
        self._missing = set()
        self._errors = []
        self._max_ready_bytes = max_ready_bytes
        self._bytes = 0

    @staticmethod
    def _index_loose(roots):
        result = {}
        for root in roots:
            root = Path(root)
            if not root.is_dir():
                continue
            for path in root.rglob('*'):
                if path.is_file() and path.suffix.casefold() in ('.tex', '.tga'):
                    result.setdefault(path.name.casefold(), path)
        return result

    def _source(self, name):
        if self._index_future is not None and self._index_future.done():
            try:
                for filename, path in self._index_future.result().items():
                    self.sources.setdefault(filename, path)
            except OSError as exc:
                self._errors.append(f'[ZEN] Поиск исходных текстур: {exc}')
            self._index_future = None

        for candidate in texture_candidates(name):
            source = self.sources.get(candidate)
            if source is not None:
                return candidate, source
        return None, None

    @staticmethod
    def _decode(source):
        size = source.size if hasattr(source, 'size') else source.stat().st_size
        if size > 64 * 1024 * 1024:
            raise ValueError('Текстура превышает 64 МБ.')
        image = read_texture(source.read_bytes(), max_dimension=512)
        # Uncompiled TGA and TEX without mip levels still need a bounded GPU
        # preview. Downsample with C-level array slicing on a worker thread.
        if max(image.width, image.height) > 512:
            step = max(1, (max(image.width, image.height) + 511) // 512)
            new_width = (image.width + step - 1) // step
            new_height = (image.height + step - 1) // step
            pixels = array('I')
            pixels.frombytes(image.pixels)
            compact = array('I')
            for y in range(0, image.height, step):
                start = y * image.width
                compact.extend(pixels[start:start + image.width:step])
            image = Texture(new_width, new_height, compact.tobytes())
        # Gothic's UV space uses a top-left image origin (Direct3D);
        # OpenGL expects bottom-left pixel rows. Flip off the UI thread.
        stride = image.width * 4
        rows = (image.pixels[y * stride:(y + 1) * stride]
                for y in range(image.height - 1, -1, -1))
        flipped = Texture(image.width, image.height, b''.join(rows))
        # Detect cutout alpha away from the UI thread. Opaque terrain must
        # never be rendered with the expensive fixed-function GL_ALPHA_TEST.
        has_alpha = flipped.pixels[3::4].count(255) != flipped.width * flipped.height
        return flipped, has_alpha

    def _decode_cached(self, source):
        if self.cache is None:
            return self._decode(source)
        try:
            key = self.cache.key('texture-512', source_stamp(source))
        except (OSError, TypeError, ValueError):
            return self._decode(source)
        raw = self.cache.read(key)
        if raw is not None and len(raw) >= 9:
            width, height, alpha = struct.unpack_from('<IIB', raw)
            if 0 < width <= 512 and 0 < height <= 512 and len(raw) == 9 + width * height * 4:
                return Texture(width, height, raw[9:]), bool(alpha), True
        texture, alpha = self._decode(source)
        self.cache.write(key, struct.pack('<IIB', texture.width, texture.height, alpha) + texture.pixels)
        return texture, alpha, False

    def stats(self):
        return len(self._pending), len(self._ready), self._bytes, self._cache_hits, self._cache_misses

    def prioritize(self, names):
        """Cancel queued (not running) obsolete requests, reserving slots for current view."""
        self._collect_ready()
        wanted = {candidate for name in names for candidate, _ in (self._source(name),) if candidate}
        for candidate, future in tuple(self._pending.items()):
            if candidate not in wanted and future.cancel():
                del self._pending[candidate]

    def _collect_ready(self):
        """Collect every finished task, even for textures no longer on screen.

        Previously only requests for the same material collected their futures:
        four completed off-screen jobs could permanently occupy all slots.
        """
        for candidate, future in tuple(self._pending.items()):
            if not future.done():
                continue
            del self._pending[candidate]
            try:
                texture = future.result()
            except Exception as exc:
                self._missing.add(candidate)
                self._errors.append(f'[ZEN] Текстура {candidate}: {exc}')
                continue
            if isinstance(texture, tuple) and len(texture) == 3:
                texture, has_alpha, hit = texture
                self._cache_hits += int(hit)
                self._cache_misses += int(not hit)
            elif isinstance(texture, tuple):
                texture, has_alpha = texture
            else:
                # Tolerate legacy/mocked decoders returning Texture directly.
                has_alpha = texture.pixels[3::4].count(255) != texture.width * texture.height
            self._alpha[candidate] = has_alpha
            self._ready[candidate] = texture
            self._bytes += len(texture.pixels)
        while self._bytes > self._max_ready_bytes and len(self._ready) > 1:
            _, discarded = self._ready.popitem(last=False)
            self._bytes -= len(discarded.pixels)

    def prefetch(self, names):
        """Nonblocking bulk scheduling, with callers supplying visible first."""
        self._collect_ready()
        for name in dict.fromkeys(names):
            if not name:
                continue
            candidate, source = self._source(name)
            if source is None:
                # Do not mark names missing until optional loose-file indexing ends.
                continue
            if (candidate in self._ready or candidate in self._pending
                    or candidate in self._missing):
                continue
            if len(self._pending) >= self._max_pending:
                break
            self._pending[candidate] = self._executor.submit(self._decode_cached, source)

    def request(self, name):
        """Nonblocking lookup; calling it never performs disk I/O or decoding."""
        if not name:
            return None
        self._collect_ready()
        candidate, source = self._source(name)
        if source is None:
            if self._index_future is None and name.casefold() not in self._missing:
                self._missing.add(name.casefold())
                if len(self._missing) <= 20:
                    self._errors.append(f'[ZEN] Не найдена текстура: {name}')
            return None
        if candidate in self._ready:
            self._ready.move_to_end(candidate)
            return self._ready[candidate]
        if (candidate not in self._missing and candidate not in self._pending
                and len(self._pending) < self._max_pending):
            self._pending[candidate] = self._executor.submit(self._decode_cached, source)
        return None

    def has_alpha(self, name):
        candidate, _source = self._source(name)
        return self._alpha.get(candidate, False)

    def report_error(self, name, error):
        candidate, _source = self._source(name)
        key = candidate or name.casefold()
        if key not in self._missing:
            self._missing.add(key)
            self._errors.append(f'[ZEN] Текстура {name}: {error}')

    def get_errors(self):
        errors, self._errors = self._errors, []
        return errors

    def close(self):
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._pending.clear()
        self._ready.clear()
        self._alpha.clear()
