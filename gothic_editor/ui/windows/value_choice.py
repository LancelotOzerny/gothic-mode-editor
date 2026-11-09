"""A centered value picker; the field owns conversion and persistence."""
import tkinter as tk

from gothic_editor.core.localization import tr
from gothic_editor.ui.widgets import PANEL
from gothic_editor.ui.widgets.buttons import PropertyButton
from gothic_editor.ui.widgets.theme import OPTION_BG
from gothic_editor.ui.widgets.scrollbar import RoundedScrollbar


class ValueChoiceWindow(tk.Toplevel):
    def __init__(self, owner, options, current, title, on_choose, on_cancel):
        super().__init__(owner, bg=PANEL)
        self.withdraw()
        self.options = options
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
        if not options:self.choose_button.config(state='disabled')
        table = tk.Frame(self, bg=PANEL)
        table.pack(fill='both', expand=True, padx=12, pady=(12,0))
        self.canvas = tk.Canvas(table, bg=OPTION_BG, highlightthickness=0, bd=0)
        scroll = RoundedScrollbar(table, self.canvas.yview)
        scroll.pack(side='right', fill='y', padx=(6,0))
        self.canvas.pack(fill='both', expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        body = tk.Frame(self.canvas, bg=OPTION_BG)
        window = self.canvas.create_window((0,0), window=body, anchor='nw')
        self.canvas.bind('<Configure>', lambda e:self.canvas.itemconfigure(window,width=e.width))
        body.bind('<Configure>', lambda _:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.option_buttons = []
        for index,(name,_) in enumerate(options):
            button = PropertyButton(body, lambda i=index:self.focus_option(i), text=name,
                                    background=OPTION_BG, align='left')
            button.pack(fill='x')
            self.option_buttons.append(button)
            button.bind('<MouseWheel>', self.scroll)
            button.bind('<Down>', lambda _,i=index:self.focus_option(i+1))
            button.bind('<Up>', lambda _,i=index:self.focus_option(i-1))
        self.bind('<Escape>', lambda _:on_cancel())
        self.bind('<Return>', lambda _:self.apply())

    def show(self):
        self.deiconify()
        self.update_idletasks()
        self.lift()
        self.focus_option(max(0,self.current))

    def focus_option(self, index):
        if not self.option_buttons:return
        self.current = max(0,min(index,len(self.option_buttons)-1))
        for i,button in enumerate(self.option_buttons):button.set_selected(i==self.current)
        self.option_buttons[self.current].focus_set()
        self.canvas.yview_moveto(self.current/max(1,len(self.option_buttons)))

    def apply(self, index=None):
        if self.options:self.on_choose(self.current if index is None else index)

    def scroll(self, event):
        self.canvas.yview_scroll(-int(event.delta/120),'units')
        return 'break'
