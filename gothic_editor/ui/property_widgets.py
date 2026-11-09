"""Inspector controls that keep Daedalus expressions separate from captions."""
import tkinter as tk

from .widgets import INPUT, MUTED, PANEL, TXT, BORDER
from ..core.property_lists import PropertyList, display_value, expression_value
from .property_controls import PropertyEntry, PropertyButton, FIELD_HEIGHT, OPTION_BG
from .welcome_controls import WelcomeScrollbar
from ..core.localization import tr


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


class ExpressionCombobox(PropertyEntry):
    def __init__(self, parent, options, **kwargs):
        self.caption=kwargs.pop('caption',tr('settings.choose'))
        self.options = options
        self.variable=kwargs.pop('textvariable',None) or tk.StringVar(parent)
        self.popup=None
        self.owner=parent.winfo_toplevel()
        super().__init__(parent,right_padding=32,textvariable=self.variable,**kwargs)
        self.arrow=tk.Label(self.surface,text='…',bg=INPUT,fg=TXT,cursor='hand2')
        self._arrow_window=self.surface.create_window(0,FIELD_HEIGHT/2,window=self.arrow,anchor='e')
        for widget in (self,self.surface,self.arrow):
            widget.bind('<ButtonRelease-1>',self.open_popup)
            widget.configure(cursor='hand2')
        self.bind('<Down>',self.open_popup)
        self.bind('<Alt-Down>',self.open_popup)
        self.bind('<Destroy>',lambda _:self.close_popup(restore_focus=False),add='+')

    def set(self, caption):
        self.variable.set(caption)

    def current(self, index=None):
        if index is None:
            return next((i for i,(name,_) in enumerate(self.options) if name==self.variable.get()),-1)
        self.set(self.options[index][0])

    def open_popup(self, event=None):
        if self.cget('state')=='disabled':return 'break'
        if self.popup is not None:
            self.popup.lift()
            self.popup.focus_set()
            return 'break'
        self.focus_set()
        popup=self.popup=tk.Toplevel(self.owner,bg=PANEL)
        popup.withdraw()
        popup.title(self.caption)
        popup.transient(self.owner)
        popup.resizable(False,False)
        self.owner.update_idletasks()
        x=self.owner.winfo_rootx()+(self.owner.winfo_width()-480)//2
        y=self.owner.winfo_rooty()+(self.owner.winfo_height()-320)//2
        popup.geometry(f'480x320+{max(0,x)}+{max(0,y)}')
        popup.protocol('WM_DELETE_WINDOW',self.close_popup)
        footer=tk.Frame(popup,bg=PANEL)
        footer.pack(side='bottom',fill='x',padx=12,pady=12)
        cancel=PropertyButton(footer,self.close_popup,text=tr('settings.cancel'))
        cancel.configure(width=110)
        cancel.pack(side='right')
        self.choose_button=PropertyButton(footer,self.choose_selected,text=tr('settings.choose'))
        self.choose_button.configure(width=110)
        self.choose_button.pack(side='right',padx=(0,8))
        if not self.options:self.choose_button.config(state='disabled')
        table=tk.Frame(popup,bg=PANEL)
        table.pack(fill='both',expand=True,padx=12,pady=(12,0))
        canvas=tk.Canvas(table,bg=OPTION_BG,highlightthickness=0,bd=0)
        scroll=WelcomeScrollbar(table,canvas.yview)
        scroll.pack(side='right',fill='y',padx=(6,0))
        canvas.pack(fill='both',expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        body=tk.Frame(canvas,bg=OPTION_BG)
        window=canvas.create_window((0,0),window=body,anchor='nw')
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
        body.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
        self.option_buttons=[]
        for index,(name,_) in enumerate(self.options):
            button=PropertyButton(body,lambda i=index:self.focus_option(i),text=name,
                                  background=OPTION_BG,align='left')
            button.pack(fill='x')
            self.option_buttons.append(button)
            button.bind('<MouseWheel>',lambda e:(canvas.yview_scroll(-int(e.delta/120),'units'),'break')[-1])
            button.bind('<Down>',lambda _,i=index:self.focus_option(i+1))
            button.bind('<Up>',lambda _,i=index:self.focus_option(i-1))
        popup.bind('<Escape>',lambda _:self.close_popup())
        popup.bind('<Return>',lambda _:self.choose_selected())
        popup.bind('<Destroy>',self.dialog_destroyed,add='+')
        popup.deiconify()
        popup.update_idletasks()
        popup.lift()
        self.focus_option(max(0,self.current()))
        return 'break'

    def focus_option(self, index):
        if not self.option_buttons:return
        index=max(0,min(index,len(self.option_buttons)-1))
        self._selection=index
        for i,button in enumerate(self.option_buttons):button.set_selected(i==index)
        self.option_buttons[index].focus_set()
        self.option_buttons[index].master.master.yview_moveto(index/max(1,len(self.option_buttons)))

    def choose(self, index):
        self.current(index)
        self.close_popup()
        self.event_generate('<<ComboboxSelected>>')

    def choose_selected(self):
        if self.options:self.choose(self._selection)

    def dialog_destroyed(self,event):
        if event.widget is self.popup:self.popup=None

    def close_popup(self,restore_focus=True):
        popup=self.popup
        self.popup=None
        if popup is not None and popup.winfo_exists():
            popup.destroy()
            if self.winfo_exists():
                if restore_focus:
                    self.winfo_toplevel().focus_force()
                    self.focus_set()

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
            hint.place(x=0 if isinstance(widget,PropertyEntry) else 4, rely=.5, anchor='w', relwidth=.85)
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


class PropertySectionFrame(tk.Frame):
    def __init__(self, parent, title, closed=False, on_toggle=lambda _: None):
        super().__init__(parent, bg=PANEL)
        self.closed = closed
        self.on_toggle = on_toggle
        self.title = title
        heading=tk.Frame(self,bg=PANEL)
        heading.pack(fill='x',padx=10,pady=10)
        heading.columnconfigure(0,weight=1)
        heading.columnconfigure(2,weight=1)
        tk.Frame(heading,bg=BORDER,height=1).grid(row=0,column=0,sticky='ew',padx=(0,10))
        self.header = tk.Button(heading, bg=PANEL, fg=TXT, relief='flat', anchor='center',
                                cursor='hand2', command=self.toggle)
        self.header.grid(row=0,column=1)
        tk.Frame(heading,bg=BORDER,height=1).grid(row=0,column=2,sticky='ew',padx=(10,0))
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
