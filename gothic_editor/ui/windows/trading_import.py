"""Search and import actual item rows from Gothic trading scripts."""
import tkinter as tk
from tkinter import ttk

from gothic_editor.ui.widgets import PANEL, INPUT, TXT, make_entry, label
from gothic_editor.ui.widgets.panel import attach_scrollbar
from gothic_editor.ui.windows.dialog import EditorDialog


class TradingGoodsDialog(EditorDialog):
    def __init__(self, owner, goods, on_import):
        super().__init__(owner, bg=PANEL)
        self.title('Импорт товаров Gothic')
        self.geometry('800x490')
        self.goods, self.on_import = goods, on_import
        self.query = tk.StringVar(self)
        label(self,'Поиск товара или исходной торговой функции').pack(anchor='w', padx=14,pady=(12,4))
        make_entry(self,textvariable=self.query).pack(fill='x',padx=14)
        label(self,'Выберите один или несколько товаров (Ctrl/Shift).').pack(anchor='w',padx=14,pady=8)
        body=tk.Frame(self,bg=PANEL)
        body.pack(fill='both',expand=True,padx=14)
        style=ttk.Style(self)
        style.configure('TradingGoods.Treeview',background=INPUT,fieldbackground=INPUT,foreground=TXT,
                        rowheight=28,borderwidth=0)
        style.map('TradingGoods.Treeview',background=[('selected','#304a65')],foreground=[('selected',TXT)])
        self.tree=ttk.Treeview(body,columns=('item','quantity','chapter','source'),
                               show='headings',selectmode='extended',style='TradingGoods.Treeview')
        for key,title,width in [('item','Предмет',240),('quantity','Кол-во',80),
                                ('chapter','Глава',60),('source','Скрипт торговца',310)]:
            self.tree.heading(key,text=title)
            self.tree.column(key,width=width)
        attach_scrollbar(body,self.tree)
        self.tree.pack(fill='both',expand=True)
        footer=tk.Frame(self,bg=PANEL)
        footer.pack(fill='x',padx=14,pady=12)
        self.add_button(footer,'Отмена',self.destroy).pack(side='right')
        self.add_button(footer,'Импортировать выбранные',self.apply).pack(side='right',padx=8)
        self.query.trace_add('write',lambda *_:self.render())
        self.tree.bind('<Double-Button-1>',lambda _:self.apply())
        self.bind('<Escape>',lambda _:self.destroy())
        self.render()

    def render(self):
        self.tree.delete(*self.tree.get_children())
        self.filtered=[]
        query=self.query.get().strip().casefold()
        for row in self.goods:
            if query and query not in (row['item']+' '+row['source']).casefold():continue
            index=len(self.filtered)
            self.filtered.append(row)
            self.tree.insert('','end',iid=str(index),
                             values=(row['item'],row['quantity'],row['chapter'],row['source']))

    def apply(self):
        selected=[self.filtered[int(index)] for index in self.tree.selection()]
        if not selected:return
        self.on_import(selected)
        self.destroy()
