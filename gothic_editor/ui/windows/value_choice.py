"""A centered value picker; the field owns conversion and persistence."""
import tkinter as tk

from gothic_editor.core.localization import tr
from gothic_editor.ui.widgets import PANEL, make_entry
from gothic_editor.ui.widgets.buttons import PropertyButton
from gothic_editor.ui.widgets.theme import OPTION_BG
from gothic_editor.ui.widgets.panel import ScrollableArea
from .dialog import EditorDialog


class ValueChoiceWindow(EditorDialog):
    def __init__(self, owner, options, current, title, on_choose, on_cancel, searchable=False, multiple=False):
        super().__init__(owner, bg=PANEL)
        self.withdraw()
        self.options = options
        self.multiple = multiple
        self.chosen = set()
        self.current = current
        self.on_choose, self.on_cancel = on_choose, on_cancel
        self.title(title)
        self.transient(owner)
        self.resizable(False, False)
        owner.update_idletasks()
        x = owner.winfo_rootx() + (owner.winfo_width()-480)//2
        y = owner.winfo_rooty() + (owner.winfo_height()-320)//2
        self.geometry(f'480x320+{max(0,x)}+{max(0,y)}')
        self.protocol('WM_DELETE_WINDOW', on_cancel)
        footer = tk.Frame(self, bg=PANEL)
        footer.pack(side='bottom', fill='x', padx=12, pady=12)
        cancel = PropertyButton(footer, on_cancel, text=tr('settings.cancel'))
        cancel.configure(width=110)
        cancel.pack(side='right')
        self.choose_button = PropertyButton(footer, self.apply, text=tr('settings.choose'))
        self.choose_button.configure(width=110)
        self.choose_button.pack(side='right', padx=(0,8))
        if not options or multiple:self.choose_button.config(state='disabled')
        table = tk.Frame(self, bg=PANEL)
        table.pack(fill='both', expand=True, padx=12, pady=(12,0))
        self.scroll_area=ScrollableArea(table,bg=OPTION_BG)
        self.scroll_area.pack(fill='both',expand=True)
        self.canvas,body=self.scroll_area.canvas,self.scroll_area.content
        self.option_buttons = []
        self.searchable = searchable
        self.query = tk.StringVar(self)
        if searchable:
            search = make_entry(table, textvariable=self.query)
            self.search_entry=search
            search.pack(fill='x', pady=(0,8), before=self.scroll_area)
            self.query.trace_add('write', lambda *_:self.filter_options())
        for index,(name,_) in enumerate(options):
            button = PropertyButton(body, lambda i=index:self.focus_option(i, toggle=True), text=name,
                                    background=OPTION_BG, align='left')
            button.pack(fill='x')
            self.option_buttons.append(button)
            button.bind('<Down>', lambda _,i=index:self.focus_option(i+1))
            button.bind('<Up>', lambda _,i=index:self.focus_option(i-1))
        if searchable:
            search.bind('<Down>', lambda _:self.focus_option(self._first_visible()))
        self.bind('<Escape>', lambda _:on_cancel())
        self.bind('<Return>', lambda _:self.apply())

    def show(self):
        self.show_centered()
        self.lift()
        self.focus_option(max(0,self.current), toggle=False)
        if self.searchable:
            self.query.set('')
            self.search_entry.focus_set()

    def _first_visible(self):
        return next((i for i, button in enumerate(self.option_buttons) if button.winfo_manager()), 0)

    def filter_options(self):
        query=self.query.get().strip().casefold()
        for index,button in enumerate(self.option_buttons):
            if query in (self.options[index][0]+' '+str(self.options[index][1])).casefold():
                button.pack(fill='x')
            else:
                button.pack_forget()
        visible=[index for index,button in enumerate(self.option_buttons) if button.winfo_manager()]
        self.choose_button.config(state='normal' if visible else 'disabled')
        if visible:self.focus_option(visible[0], toggle=False)

    def focus_option(self, index, toggle=False):
        if not self.option_buttons:return
        index = max(0,min(index,len(self.option_buttons)-1))
        if not self.option_buttons[index].winfo_manager():
            index=self._first_visible()
        self.current = index
        if self.multiple and toggle:
            if self.current in self.chosen:self.chosen.remove(self.current)
            else:self.chosen.add(self.current)
        for i,button in enumerate(self.option_buttons):
            button.set_selected(i in self.chosen if self.multiple else i==self.current)
            if self.multiple:
                button.text=('☑ ' if i in self.chosen else '☐ ') + self.options[i][0]
                button.paint()
        if self.multiple:self.choose_button.config(state='normal' if self.chosen else 'disabled')
        self.option_buttons[self.current].focus_set()
        self.canvas.yview_moveto(self.current/max(1,len(self.option_buttons)))

    def apply(self, index=None):
        if self.multiple:
            if self.chosen:self.on_choose(tuple(sorted(self.chosen)))
        elif self.options and self.option_buttons and self.option_buttons[self.current].winfo_manager():
            self.on_choose(self.current if index is None else index)

    def scroll(self, event):
        return self.scroll_area.wheel(event)
