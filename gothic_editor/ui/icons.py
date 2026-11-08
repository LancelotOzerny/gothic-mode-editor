"""Small themed PNG icons and cached clockwise rotation frames using Tk only."""
import math
import tkinter as tk
from pathlib import Path


class IconImages:
    def __init__(self, master):
        self.master = master
        self.directory = Path(__file__).resolve().parents[2] / 'assets' / 'icons'
        self.cache = {}
        self.sources = {}

    def frames(self, filename, size, foreground, background, steps=1):
        key = (filename, size, foreground, background, steps)
        if key in self.cache:
            return self.cache[key]
        path = self.directory / filename
        if path not in self.sources:
            source = tk.PhotoImage(master=self.master, file=str(path))
            width, height = source.width(), source.height()
            # White/black composites recover PNG alpha, including antialiased edges.
            composites = []
            for color in ('black', 'white'):
                composite = tk.PhotoImage(master=self.master, width=width, height=height)
                composite.put(color, to=(0, 0, width, height))
                composite.tk.call(str(composite), 'copy', str(source), '-compositingrule', 'overlay')
                composites.append(composite)
            alpha = [[1 - (composites[1].get(x, y)[0] - composites[0].get(x, y)[0]) / 255
                      for x in range(width)] for y in range(height)]
            self.sources[path] = width, height, alpha
        width, height, alpha = self.sources[path]
        fg = tuple(int(foreground[i:i + 2], 16) for i in (1, 3, 5))
        bg = tuple(int(background[i:i + 2], 16) for i in (1, 3, 5))

        def sample(x, y):
            x0, y0 = math.floor(x), math.floor(y)
            value = 0
            for dx, wx in ((0, 1 - (x - x0)), (1, x - x0)):
                for dy, wy in ((0, 1 - (y - y0)), (1, y - y0)):
                    if 0 <= x0 + dx < width and 0 <= y0 + dy < height:
                        value += alpha[y0 + dy][x0 + dx] * wx * wy
            return value

        frames = []
        scale = max(width, height) / size
        for index in range(steps):
            angle = math.pi / 2 * index / (steps - 1) if steps > 1 else 0
            cosine, sine = math.cos(angle), math.sin(angle)
            rows = []
            for y in range(size):
                row = []
                for x in range(size):
                    u, v = (x - (size - 1) / 2) * scale, (y - (size - 1) / 2) * scale
                    opacity = sample(cosine * u + sine * v + (width - 1) / 2,
                                     -sine * u + cosine * v + (height - 1) / 2)
                    rgb = [round(b + (f - b) * opacity) for f, b in zip(fg, bg)]
                    row.append('#%02x%02x%02x' % tuple(rgb))
                rows.append('{' + ' '.join(row) + '}')
            frame = tk.PhotoImage(master=self.master, width=size, height=size)
            frame.put(' '.join(rows))
            frames.append(frame)
        self.cache[key] = frames
        return frames
