"""Merchant configuration window inside the existing NPC editor."""
import re
import tkinter as tk
from tkinter import ttk, messagebox

from gothic_editor.core.scripts import load_text, mask_comments
from gothic_editor.core.trading import TradingStore

class TradingWindow(tk.Toplevel):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        npc = controller.current
        self.npc = npc.instance
        self.store = TradingStore(controller.app.repo.root)
        saved = self.store.read().get(self.npc.casefold(), {})
        self.title('Торговля — ' + npc.title)
        self.geometry('740x620')
        self.minsize(630, 480)
        self.transient(parent)
        self.enabled = tk.BooleanVar(value=saved.get('enabled', bool(saved)))
        self.dialog = tk.BooleanVar(value=saved.get('dialog', False))
        self.replace = tk.BooleanVar(value=saved.get('replace_original', False))
        self.chapter = tk.StringVar(value=str(saved.get('min_chapter', 1)))
        self.hours = tk.StringVar(value=str(saved.get('refresh_hours', 0)))
        self.rows = [dict(row) for row in saved.get('stock', [])]
        self.item = tk.StringVar()
        self.quantity = tk.StringVar(value='1')
        self.item_chapter = tk.StringVar(value='1')
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Торговец: ' + npc.title + ' (' + self.npc + ')',
                  font=('Arial', 11, 'bold')).pack(anchor='w', pady=(0, 10))
        ttk.Checkbutton(frame, text='Включить торговлю', variable=self.enabled).pack(anchor='w')
        ttk.Checkbutton(frame, text='Создать торговый диалог для NPC', variable=self.dialog).pack(anchor='w')
        ttk.Checkbutton(frame, text='Заменить оригинальный ассортимент (вместо дополнения)',
                        variable=self.replace).pack(anchor='w')
        options = ttk.Frame(frame)
        options.pack(fill='x', pady=10)
        ttk.Label(options, text='Доступно с главы').pack(side='left')
        ttk.Combobox(options, textvariable=self.chapter, width=4, values=[str(x) for x in range(1,7)],
                     state='readonly').pack(side='left', padx=(8,25))
        ttk.Label(options, text='Пополнение каждые (игровых часов; 0 = выкл.)').pack(side='left')
        ttk.Entry(options, textvariable=self.hours, width=8).pack(side='left', padx=8)
        ttk.Label(frame, text='Ассортимент по главам').pack(anchor='w', pady=(4,5))
        columns = ('item','quantity','chapter')
        self.table = ttk.Treeview(frame, columns=columns, show='headings', height=12, selectmode='browse')
        for col, name, width in [('item','Предмет (ID)',350),('quantity','Количество',110),('chapter','Глава',80)]:
            self.table.heading(col, text=name)
            self.table.column(col, width=width, stretch=True)
        self.table.pack(fill='both', expand=True)
        self.table.bind('<<TreeviewSelect>>', self.select_row)
        edit = ttk.Frame(frame)
        edit.pack(fill='x', pady=10)
        ttk.Label(edit, text='Предмет').grid(row=0,column=0,sticky='w')
        self.items = ttk.Combobox(edit, textvariable=self.item, width=37,
                                   values=[value.instance for value in controller.app.repo.items])
        self.items.grid(row=1,column=0,sticky='ew',padx=(0,8))
        ttk.Label(edit, text='Кол-во').grid(row=0,column=1,sticky='w')
        ttk.Entry(edit, textvariable=self.quantity, width=8).grid(row=1,column=1,padx=8)
        ttk.Label(edit, text='Глава').grid(row=0,column=2,sticky='w')
        ttk.Combobox(edit,textvariable=self.item_chapter,state='readonly',width=6,
                     values=[str(x) for x in range(1,7)]).grid(row=1,column=2,padx=8)
        ttk.Button(edit,text='Добавить / изменить',command=self.add_row).grid(row=1,column=3,padx=8)
        edit.columnconfigure(0,weight=1)
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=(4,0))
        ttk.Button(buttons,text='Удалить выбранное',command=self.remove_row).pack(side='left')
        ttk.Button(buttons,text='Импорт из Gothic',command=self.import_stock).pack(side='left',padx=7)
        ttk.Button(buttons,text='Отмена',command=self.destroy).pack(side='right')
        ttk.Button(buttons,text='Сохранить',command=self.save).pack(side='right',padx=8)
        self.render()
        self.grab_set()

    def render(self):
        for node in self.table.get_children():
            self.table.delete(node)
        for i, row in enumerate(self.rows):
            self.table.insert('', 'end', iid=str(i),
                              values=(row['item'], row['quantity'], row['chapter']))

    def select_row(self, _event=None):
        selection = self.table.selection()
        if selection:
            row = self.rows[int(selection[0])]
            self.item.set(row['item'])
            self.quantity.set(str(row['quantity']))
            self.item_chapter.set(str(row['chapter']))

    def add_row(self):
        try:
            row = dict(item=self.item.get().strip(), quantity=int(self.quantity.get()),
                       chapter=int(self.item_chapter.get()))
            result = [old for old in self.rows
                      if (old['item'].casefold(),old['chapter']) != (row['item'].casefold(),row['chapter'])]
            result.append(row)
            TradingStore.validate(dict(stock=result))
            self.rows = sorted(result, key=lambda x:(x['chapter'],x['item'].casefold()))
            self.render()
        except (ValueError, TypeError) as exc:
            self.error(exc)

    def remove_row(self):
        selection=self.table.selection()
        if selection:
            self.rows.pop(int(selection[0]))
            self.render()

    def import_stock(self):
        """Read the selected vanilla B_GiveTradeInv_* function, not the NPC's carried inventory."""
        from gothic_editor.core.daedalus_merge import ScriptTree
        content=self.controller.app.repo.game
        if content is None:
            return self.error(ValueError('Не указан каталог Gothic.'))
        root=content/'_work/Data/Scripts/Content'
        if not root.is_dir():
            return self.error(ValueError('Не найдены исходные скрипты Gothic.'))
        try:
            tree=ScriptTree(root)
            found=[]
            for name, matches in tree.symbols.items():
                if name.startswith('b_givetradeinv_') and len(matches)==1 and matches[0][1].kind=='func':
                    found.append((matches[0][1].names[0], matches[0][0], matches[0][1]))
            if not found:
                raise ValueError('В исходных скриптах нет функций B_GiveTradeInv_*.')
            popup=tk.Toplevel(self)
            popup.title('Импорт ассортимента')
            popup.transient(self)
            popup.geometry('410x130')
            choice=tk.StringVar(value=found[0][0])
            ttk.Label(popup,text='Выберите функцию торговца:').pack(anchor='w',padx=12,pady=8)
            ttk.Combobox(popup,textvariable=choice,state='readonly',
                         values=[row[0] for row in found]).pack(fill='x',padx=12)
            def apply():
                match=next(row for row in found if row[0]==choice.get())
                source,_=load_text(match[1])
                block=mask_comments(source[match[2].start:match[2].end])
                chapter=1
                imported=[]
                for line in block.splitlines():
                    flag=re.search(r'Kapitel\s*>=\s*([1-6])',line,re.I)
                    if flag:chapter=int(flag[1])
                    for item, count in re.findall(r'CreateInvItems\s*\(\s*\w+\s*,\s*(\w+)\s*,\s*(\d+)\s*\)',line,re.I):
                        imported.append(dict(item=item,quantity=int(count),chapter=chapter))
                if not imported:
                    self.error(ValueError('Функция не содержит простых вызовов CreateInvItems.'))
                    return
                existing={(row['item'].casefold(),row['chapter']):row for row in self.rows}
                for row in imported:
                    existing[(row['item'].casefold(),row['chapter'])]=row
                self.rows=sorted(existing.values(),key=lambda row:(row['chapter'],row['item'].casefold()))
                self.render()
                popup.destroy()
            ttk.Button(popup,text='Импортировать',command=apply).pack(pady=10)
        except (OSError,ValueError) as exc:
            self.error(exc)

    def error(self, exc):
        self.controller.app.terminal.append('Торговля ' + self.npc + ': ' + str(exc))
        messagebox.showerror('Торговля', str(exc), parent=self)

    def save(self):
        try:
            config=dict(enabled=self.enabled.get(),dialog=self.dialog.get(),
                        replace_original=self.replace.get(),
                        min_chapter=int(self.chapter.get()),refresh_hours=int(self.hours.get()),
                        stock=self.rows)
            TradingStore.validate(config)
            known={item.instance.casefold() for item in self.controller.app.repo.items}
            for row in self.rows:
                if row['item'].casefold() not in known:
                    raise ValueError('Предмет не найден в проекте: ' + row['item'])
            saved=self.controller.app.history.capture((self.store.path,))
            self.store.save(self.npc,config)
            self.controller.app.history.record(saved)
            self.controller.app.terminal.append('Настройки торговли сохранены: ' + self.npc)
            self.destroy()
        except (OSError,ValueError) as exc:
            self.error(exc)
