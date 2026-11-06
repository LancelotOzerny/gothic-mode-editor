"""Inspector controls that keep Daedalus expressions separate from captions."""
import tkinter as tk
from tkinter import ttk

from .widgets import INPUT, MUTED, PANEL, TXT, entry_menu


class ExpressionCombobox(ttk.Combobox):
    def __init__(self, parent, options, **kwargs):
        self.options = options
        super().__init__(parent, values=[name for name, _ in options], **kwargs)
        entry_menu(self)

    def set_expression(self, expression):
        self.set(next((name for name, value in self.options if value == expression), expression))

    def get(self):
        caption = super().get()
        return next((value for name, value in self.options if name == caption), caption)


def add_placeholder(widget, variable, text):
    """Show a visual hint without ever inserting it into the actual value."""
    if not text:
        return
    hint = tk.Label(widget, text=text, bg=INPUT, fg=MUTED, anchor='w', cursor='xterm')

    def update(*_):
        if not variable.get() and widget.focus_get() is not widget:
            hint.place(x=4, rely=.5, anchor='w', relwidth=.85)
        else:
            hint.place_forget()

    trace = variable.trace_add('write', update)
    widget.bind('<FocusIn>', update, add='+')
    widget.bind('<FocusOut>', update, add='+')
    hint.bind('<Button-1>', lambda _: widget.focus_set())
    widget.bind('<Destroy>', lambda event: variable.trace_remove('write', trace)
                if event.widget is widget else None, add='+')
    widget.value_variable = variable
    widget.placeholder = hint
    update()


class PropertySectionFrame(tk.LabelFrame):
    def __init__(self, parent, title, closed=False, on_toggle=lambda _: None):
        super().__init__(parent, text=title, bg=PANEL, fg=MUTED, pady=6)
        self.closed = closed
        self.on_toggle = on_toggle
        self.title = title
        self.header = tk.Button(self, bg=PANEL, fg=TXT, relief='flat', anchor='w',
                                cursor='hand2', command=self.toggle)
        self.config(labelwidget=self.header)
        self.body = tk.Frame(self, bg=PANEL)
        self.update_state()

    def update_state(self):
        self.header.config(text=('▸ ' if self.closed else '▾ ') + self.title)
        if self.closed:
            self.body.pack_forget()
        else:
            self.body.pack(fill='x')

    def toggle(self):
        self.closed = not self.closed
        self.update_state()
        self.on_toggle(self.closed)
