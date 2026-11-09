import tkinter as tk
from tkinter import ttk
from gothic_editor.core.localization import tr
from gothic_editor.ui.widgets import BG, PANEL, INPUT, TXT, label

class TerminalPanel(tk.Frame):
    def __init__(self, parent, on_hide):
        super().__init__(parent, bg=BG)
        header = tk.Frame(self, bg=PANEL)
        header.pack(fill='x')
        label(header, tr('terminal.title')).pack(side='left', padx=10, pady=4)
        ttk.Button(header, text='×', width=3, command=on_hide).pack(side='right')
        ttk.Button(header, text=tr('terminal.clear'), command=self.clear).pack(side='right', padx=6)
        scroll = ttk.Scrollbar(self)
        scroll.pack(side='right', fill='y')
        self.log = tk.Text(self, bg=INPUT, fg=TXT, insertbackground=TXT, wrap='word',
                           font=('Consolas', 10), state='disabled', relief='flat',
                           yscrollcommand=scroll.set, height=1)
        self.log.pack(fill='both', expand=True)
        scroll.config(command=self.log.yview)
        self.log.bind('<Button-1>',lambda _:self.log.focus_set(),add='+')
        self.log.bind('<Control-KeyPress>',self._copy_shortcut)
        self.log.bind('<<Copy>>',self.copy_selection)

    def _copy_shortcut(self,event):
        if (event.keysym.lower() in ('c','cyrillic_es') or
                (event.keycode==67 and self.tk.call('tk','windowingsystem')=='win32')):
            return self.copy_selection()

    def copy_selection(self,_event=None):
        if self.log.tag_ranges('sel'):
            text=self.log.get('sel.first','sel.last')
            self.log.clipboard_clear()
            self.log.clipboard_append(text)
        return 'break'

    def append(self, message):
        self.log.config(state='normal')
        self.log.insert('end', message + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > 5000:
            self.log.delete('1.0', '1001.0')
        self.log.see('end')
        self.log.config(state='disabled')

    def clear(self):
        self.log.config(state='normal')
        self.log.delete('1.0', 'end')
        self.log.config(state='disabled')
