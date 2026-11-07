"""Inspector controls that keep Daedalus expressions separate from captions."""
import tkinter as tk
from tkinter import ttk

from .widgets import INPUT, MUTED, PANEL, TXT, entry_menu, make_entry
from ..core.property_lists import PropertyList, display_value, expression_value


class KeyValueList(tk.Frame):
    """Two schema-defined columns with stable array indices and responsive layout."""
    def __init__(self, parent, field, fields, editable=True):
        super().__init__(parent, bg=PANEL)
        self.model = PropertyList(field, fields)
        self.editable = editable
        self.rows = []
        self.add_button = ttk.Button(self, text='Добавить', command=self.add_row)
        self.add_button.pack(side='bottom', anchor='w', pady=5)
        self.set_expression(self.model.rows)

    def get(self):
        result = []
        for index, _, cells in self.rows:
            values = tuple(original if entry.get() == initial else expression_value(entry.get(), column.field_type)
                           for column, entry, initial, original in cells)
            result.append((index, values))
        return result

    def set_expression(self, rows):
        for _, frame, _ in self.rows:
            frame.destroy()
        self.rows = []
        for index, values in rows:
            self._append(index, values)
        self._update_button()

    def add_row(self):
        index = self.model.available_index(self.get())
        if self.editable and index is not None:
            self._append(index, ('', '') )
            self._update_button()

    def _append(self, index, values):
        frame = tk.Frame(self, bg=PANEL)
        frame.pack(fill='x', pady=4)
        cells, holders = [], []
        for column, value in zip(self.model.field.columns, values):
            holder = tk.Frame(frame, bg=PANEL)
            tk.Label(holder, text=column.label, bg=PANEL, fg=MUTED, anchor='w').pack(fill='x')
            entry = make_entry(holder, width=1)
            initial = display_value(value, column.field_type)
            entry.insert(0, initial)
            if not self.editable:entry.config(state='readonly')
            entry.pack(fill='x', ipady=4)
            holders.append(holder)
            cells.append((column, entry, initial, value))
        remove = ttk.Button(frame, text='×', width=2, command=lambda:self.remove_row(index))
        if not self.editable:remove.config(state='disabled')
        remove.grid(row=0, column=2, sticky='ne', padx=(4,0))
        frame.columnconfigure(0, weight=3, uniform='fields')
        frame.columnconfigure(1, weight=1, uniform='fields')

        def layout(event):
            narrow = event.width < 300
            holders[0].grid(row=0, column=0, columnspan=2 if narrow else 1, sticky='ew', padx=(0,4))
            holders[1].grid(row=1 if narrow else 0, column=0 if narrow else 1,
                            columnspan=2 if narrow else 1, sticky='ew')
        frame.bind('<Configure>', layout)
        self.rows.append((index, frame, cells))

    def remove_row(self, index):
        if not self.editable:return
        for row in list(self.rows):
            if row[0] == index:
                row[1].destroy()
                self.rows.remove(row)
        self._update_button()

    def _update_button(self):
        self.add_button.config(state='normal' if self.editable and self.model.available_index(self.get()) is not None else 'disabled')

    def updates(self):
        return self.model.updates(self.get())


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
