"""Read-only, asynchronous resolution of original Gothic world textures.

Decoding runs outside Tk/OpenGL. All graphics operations remain with the view.
"""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .texture_names import texture_candidates
from .textures import Texture, read_texture


class WorldTextures:
    def __init__(self, sources, *, loose_roots=(), max_ready_bytes=96 * 1024 * 1024):
        self.sources = {Path(name.replace('\\', '/')).name.casefold(): source
                        for name, source in sources.items()}
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._index_future = self._executor.submit(self._index_loose, tuple(loose_roots)) if loose_roots else None
        self._pending = {}
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
        image = read_texture(source.read_bytes())
        # Gothic's UV space uses a top-left image origin (Direct3D);
        # OpenGL expects bottom-left pixel rows. Flip off the UI thread.
        stride = image.width * 4
        rows = (image.pixels[y * stride:(y + 1) * stride]
                for y in range(image.height - 1, -1, -1))
        return Texture(image.width, image.height, b''.join(rows))

    def request(self, name):
        """Nonblocking request. Returns a decoded Texture if available."""
        if not name:
            return None
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
        future = self._pending.get(candidate)
        if future is None:
            if candidate not in self._missing and len(self._pending) < 4:
                self._pending[candidate] = self._executor.submit(self._decode, source)
            return None
        if not future.done():
            return None
        del self._pending[candidate]
        try:
            texture = future.result()
        except Exception as exc:
            # Isolate malformed textures and decoder failures from world loading.
            self._missing.add(candidate)
            self._errors.append(f'[ZEN] Текстура {candidate}: {exc}')
            return None
        self._ready[candidate] = texture
        self._bytes += len(texture.pixels)
        while self._bytes > self._max_ready_bytes and len(self._ready) > 1:
            _, discarded = self._ready.popitem(last=False)
            self._bytes -= len(discarded.pixels)
        return texture

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
