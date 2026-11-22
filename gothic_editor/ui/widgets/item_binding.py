"""Reusable square binding tile for an item INSTANCE and quantity."""
import tkinter as tk
from tkinter import messagebox

from .theme import PANEL, INPUT, TXT, BORDER
from .buttons import RoundedIconButton
from .icons import IconImages


class ItemBindingTile(tk.Frame):
    SIZE = 224

    def __init__(self, parent, variable, count, on_choose, on_remove, on_change,
                 title='', close_size=40, name_position=.43):
        super().__init__(parent, bg=PANEL, width=self.SIZE, height=self.SIZE)
        self.variable, self.count = variable, count
        self.on_choose, self.on_remove, self.on_change = on_choose, on_remove, on_change
        self._title = title
        self.name_position = name_position
        self.pack_propagate(False)
        self.surface = tk.Frame(self, bg=INPUT, highlightthickness=1,
                                highlightbackground=BORDER, cursor='hand2')
        self.surface.pack(fill='both', expand=True)
        self.surface.bind('<Button-1>', lambda _: self.on_choose(self.variable))
        self.icons = IconImages.shared(self)
        self.close = RoundedIconButton(self.surface, self.icons, 'close.png', 'x',
                                       'Удалить привязку', self.remove, background=INPUT,
                                       size=close_size, padding=max(5, round(close_size * .275)))
        self.close.place(relx=1, x=-8, y=8, anchor='ne')
        self.name = tk.Label(self.surface, bg=INPUT, fg=TXT, justify='center',
                             wraplength=self.SIZE - 34, cursor='hand2')
        self.name.place(relx=.5, rely=self.name_position, anchor='center')
        self.name.bind('<Button-1>', lambda _: self.on_choose(self.variable))
        self.create_icon = RoundedIconButton(
            self.surface, self.icons, 'create.png', '+',
            'Выбрать предмет', lambda: self.on_choose(self.variable),
            background=INPUT, size=56, padding=14)
        self.create_icon.place(relx=.5, rely=.5, anchor='center')
        self.footer = tk.Frame(self.surface, bg=INPUT)
        self.footer.place(relx=.5, rely=1, y=-9, anchor='s')
        self.minus = RoundedIconButton(self.footer, self.icons, 'minus.png', '-',
                                       'Уменьшить количество', lambda: self.step(-1),
                                       background=INPUT, size=38, padding=11)
        self.minus.pack(side='left')
        self.quantity = tk.Label(self.footer, bg=INPUT, fg=TXT, width=4,
                                 font=('Arial', 12, 'bold'))
        self.quantity.pack(side='left', padx=10)
        self.plus = RoundedIconButton(self.footer, self.icons, 'plus.png', '+',
                                      'Увеличить количество', lambda: self.step(1),
                                      background=INPUT, size=38, padding=11)
        self.plus.pack(side='left')
        self._traces = [(variable, variable.trace_add('write', lambda *_: self.refresh())),
                        (count, count.trace_add('write', lambda *_: self.refresh()))]
        self.bind('<Destroy>', self._dispose, add='+')
        self.refresh()

    def _dispose(self, event):
        if event.widget is self:
            for variable, trace in self._traces:
                variable.trace_remove('write', trace)

    def refresh(self):
        instance = self.variable.get().strip()
        if instance:
            title = self._title(instance) if callable(self._title) else self._title
            self.name.config(text=(title or instance) + '\n[' + instance + ']',
                             font=('Arial', 15), fg=TXT)
            self.create_icon.place_forget()
            self.footer.place(relx=.5, rely=1, y=-9, anchor='s')
            self.close.paint(opacity=1)
        else:
            self.name.config(text='', font=('Arial', 11), fg=TXT)
            self.create_icon.place(relx=.5, rely=.5, anchor='center')
            self.footer.place_forget()
            self.close.paint(opacity=0)
        try: value = int(self.count.get())
        except (TypeError, ValueError): value = 1
        self.quantity.config(text=str(max(1, value)))

    def step(self, delta):
        try: value = int(self.count.get())
        except (TypeError, ValueError): value = 1
        value = max(1, min(2147483647, value + delta))
        self.count.set(str(value))
        self.on_change()

    def remove(self):
        if self.variable.get().strip() and not messagebox.askyesno(
                'Удалить ингредиент', 'Удалить выбранный ингредиент?', parent=self.winfo_toplevel()):
            return
        self.on_remove()

