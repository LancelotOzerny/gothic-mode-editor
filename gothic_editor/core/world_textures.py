"""Read-only, asynchronous resolution of original Gothic world textures.

Decoding runs outside Tk/OpenGL. All graphics operations remain with the view.
"""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .texture_names import texture_candidates
from .textures import read_texture


class WorldTextures:
    def __init__(self, sources, *, max_ready_bytes=96 * 1024 * 1024):
        self.sources = {Path(name.replace('\\', '/')).name.casefold(): source
                        for name, source in sources.items()}
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._pending = {}
        self._ready = OrderedDict()
        self._missing = set()
        self._errors = []
        self._max_ready_bytes = max_ready_bytes
        self._bytes = 0

    def _source(self, name):
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
        return read_texture(source.read_bytes())

    def request(self, name):
        """Nonblocking request. Returns a decoded Texture if available."""
        if not name:
            return None
        candidate, source = self._source(name)
        if source is None:
            self._missing.add(name.casefold())
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
        except (OSError, ValueError, IndexError) as exc:
            self._missing.add(candidate)
            self._errors.append(f'[ZEN] Текстура {candidate}: {exc}')
            return None
        self._ready[candidate] = texture
        self._bytes += len(texture.pixels)
        while self._bytes > self._max_ready_bytes and len(self._ready) > 1:
            _, discarded = self._ready.popitem(last=False)
            self._bytes -= len(discarded.pixels)
        return texture

    def get_errors(self):
        errors, self._errors = self._errors, []
        return errors

    def close(self):
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._pending.clear()
        self._ready.clear()
