import tkinter as tk
from gothic_editor.core.property_lists import PropertyList, display_value, expression_value
from .theme import PANEL, MUTED
from .inputs import PropertyEntry
from .buttons import PropertyButton

class KeyValueList(tk.Frame):
    """Two schema-defined columns with stable array indices and responsive layout."""
    def __init__(self, parent, field, fields, editable=True, on_commit=lambda:None):
        super().__init__(parent, bg=PANEL)
        self.model = PropertyList(field, fields)
        self.editable = editable
        self.on_commit = on_commit
        self.rows = []
        self.column_header=tk.Frame(self,bg=PANEL)
        self.column_header.pack(fill='x')
        self.column_header.columnconfigure(0,weight=3,uniform='fields')
        self.column_header.columnconfigure(1,weight=1,uniform='fields')
        self.column_header.columnconfigure(2,minsize=44)
        self.column_labels=[tk.Label(self.column_header,text=column.label,bg=PANEL,fg=MUTED,anchor='w')
                            for column in field.columns]
        self.column_header.bind('<Configure>',self.layout_header)
        footer=tk.Frame(self,bg=PANEL)
        footer.pack(side='bottom',fill='x',pady=5)
        self.add_button = PropertyButton(footer, self.add_row, text='+',
                                         filename='create.png',caption='Добавить')
        self.add_button.pack(side='right')
        self.set_expression(self.model.rows)

    def layout_header(self,event):
        narrow=event.width<300
        self.column_labels[0].configure(text=' / '.join(c.label for c in self.model.field.columns)
                                       if narrow else self.model.field.columns[0].label)
        self.column_labels[0].grid(row=0,column=0,columnspan=2 if narrow else 1,sticky='ew',padx=(0,4))
        if narrow:self.column_labels[1].grid_remove()
        else:self.column_labels[1].grid(row=0,column=1,sticky='ew')

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
            entry = PropertyEntry(holder, width=1)
            initial = display_value(value, column.field_type)
            entry.insert(0, initial)
            entry.bind('<FocusOut>',lambda _:self.on_commit(),add='+')
            if not self.editable:entry.config(state='readonly')
            entry.pack(fill='x')
            holders.append(holder)
            cells.append((column, entry, initial, value))
        remove = PropertyButton(frame,lambda:self.remove_row(index),text='×',
                                filename='detele.png',caption='Удалить')
        if not self.editable:remove.config(state='disabled')
        remove.grid(row=0, column=2, sticky='s', padx=(4,0))
        frame.columnconfigure(0, weight=3, uniform='fields')
        frame.columnconfigure(1, weight=1, uniform='fields')

        def layout(event):
            narrow = event.width < 300
            holders[0].grid(row=0, column=0, columnspan=2 if narrow else 1, sticky='ew', padx=(0,4))
            holders[1].grid(row=1 if narrow else 0, column=0 if narrow else 1,
                            columnspan=2 if narrow else 1, sticky='ew')
            remove.grid(row=1 if narrow else 0,column=2,sticky='s')
        frame.bind('<Configure>', layout)
        self.rows.append((index, frame, cells))

    def remove_row(self, index):
        if not self.editable:return
        for row in list(self.rows):
            if row[0] == index:
                self.rows.remove(row)
                row[1].destroy()
        self._update_button()
        self.on_commit()

    def _update_button(self):
        self.add_button.config(state='normal' if self.editable and self.model.available_index(self.get()) is not None else 'disabled')

    def updates(self):
        return self.model.updates(self.get())

    def accept_saved(self, fields):
        self.model = PropertyList(self.model.field, fields)
        for row_index, _, cells in self.rows:
            for index, (column,entry,_,_) in enumerate(cells):
                value=entry.get()
                original=self.model.fields.get(self.model.key(column.key,row_index),'')
                cells[index]=(column,entry,value,original)
