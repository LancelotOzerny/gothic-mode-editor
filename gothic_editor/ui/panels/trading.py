"""Embedded merchant workspace using the editor's existing controls and item tiles."""
import tkinter as tk
from tkinter import messagebox

from gothic_editor.core.trading import TradingStore
from gothic_editor.ui.widgets import label, PANEL, INPUT, MUTED
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea
from gothic_editor.ui.widgets.form import create_field
from gothic_editor.ui.widgets.buttons import PropertyButton
from gothic_editor.ui.widgets.item_binding import ItemBindingTile
from gothic_editor.ui.windows.value_choice import ValueChoiceWindow
from gothic_editor.ui.windows.trading_import import TradingGoodsDialog


class TradingPanel(Panel):
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.controller = controller
        self.npc = None
        self.rows = []
        self._dirty = False
        header = tk.Frame(self, bg=PANEL)
        header.pack(fill='x', padx=14, pady=12)
        self.heading = label(header, 'Торговля', font=('Arial', 13, 'bold'))
        self.heading.pack(side='left')
        PropertyButton(header, self.save, text='Сохранить').pack(side='right')
        self.status = label(self, '', fg=MUTED)
        self.status.pack(fill='x', padx=14)
        self.area = ScrollableArea(self)
        self.area.pack(fill='both', expand=True)

    def show(self, npc):
        if self.npc == npc.instance and self._dirty:
            return
        self.npc = npc.instance
        self.heading.config(text='Торговля — ' + npc.title)
        self._dirty = False
        saved = TradingStore(self.controller.app.repo.root).read().get(npc.instance.casefold(), {})
        self.enabled = tk.BooleanVar(self, value=saved.get('enabled', bool(saved)))
        self.dialog = tk.BooleanVar(self, value=saved.get('dialog', False))
        self.replace = tk.BooleanVar(self, value=saved.get('replace_original', False))
        self.chapter = tk.StringVar(self, value=str(saved.get('min_chapter', 1)))
        self.hours = tk.StringVar(self, value=str(saved.get('refresh_hours', 0)))
        self.dialog_text = tk.StringVar(self, value=saved.get('dialog_text', 'Покажи товары'))
        self.rows = []
        for child in self.area.content.winfo_children():
            child.destroy()
        general = self.add_group('Настройки торговца', parent=self.area.content, compact=True)
        self._control(general, 'Включить торговлю', 'boolean', self.enabled)
        self._control(general, 'Добавить торговый диалог', 'boolean', self.dialog)
        self.dialog_container = tk.Frame(general.body, bg=general.body.cget('bg'))
        self.dialog_container.pack(fill='x')
        self.dialog_label = label(self.dialog_container, 'Фраза торгового диалога')
        self.dialog_label.pack(fill='x', padx=8)
        self.dialog_entry = create_field(self.dialog_container, variable=self.dialog_text)
        self.dialog_entry.pack(fill='x', padx=8, pady=(0,8))
        self._control(general, 'Заменить оригинальный ассортимент', 'boolean', self.replace)
        self._control(general, 'Доступно с главы', 'choice', self.chapter,
                      options=[(str(n), str(n)) for n in range(1,7)])
        self._control(general, 'Пополнение каждые N игровых часов (0 — отключено)', 'number',
                      self.hours, minimum=0, maximum=100000)
        self.dialog.trace_add('write', lambda *_:self._dialog_state())
        self._dialog_state()
        stock = self.add_group('Товары', parent=self.area.content)
        stock.add_button('Импортировать товары из Gothic', self.import_goods)
        self.tiles_frame = tk.Frame(stock.body, bg=stock.body.cget('bg'))
        self.tiles_frame.pack(fill='x', padx=8, pady=8)
        self.tiles_frame.bind('<Configure>', lambda _:self.reflow(), add='+')
        self.item_titles = {item.instance.casefold():item.title for item in self.controller.app.repo.items}
        for row in saved.get('stock', []):
            self.add_row(row, notify=False)
        self.add_row(None, notify=False)
        self.status.config(text='Настройки загружены')

    def _control(self, group, title, kind, variable, **kwargs):
        label(group.body, title).pack(fill='x', padx=8, pady=(5,2))
        field = create_field(group.body, kind, variable=variable, **kwargs)
        field.pack(fill='x', padx=8)
        variable.trace_add('write', lambda *_:self.changed())
        return field

    def _dialog_state(self):
        enabled = self.dialog.get()
        if enabled:
            self.dialog_label.pack(fill='x', padx=8)
            self.dialog_entry.pack(fill='x', padx=8, pady=(0,8))
        else:
            self.dialog_label.pack_forget()
            self.dialog_entry.pack_forget()

    def changed(self):
        self._dirty = True
        self.status.config(text='Есть несохранённые изменения')

    def add_row(self, row=None, notify=True):
        instance = tk.StringVar(self, value=row['item'] if row else '')
        count = tk.StringVar(self, value=str(row['quantity']) if row else '1')
        chapter = tk.StringVar(self, value=str(row['chapter']) if row else '1')
        container = tk.Frame(self.tiles_frame, bg=PANEL, width=ItemBindingTile.SIZE)
        container.grid_propagate(False)
        container.configure(height=ItemBindingTile.SIZE)
        record = dict(frame=container, item=instance, count=count, chapter=chapter)
        if row is not None and self.rows and not self.rows[-1]['item'].get().strip():
            self.rows.insert(len(self.rows)-1, record)
        else:
            self.rows.append(record)
        tile = ItemBindingTile(container, instance, count, self.choose_item,
                               lambda r=record:self.remove_row(r), self.changed,
                               lambda item:self.item_titles.get(item.casefold(), item))
        tile.pack(fill='x', side='top')
        line = tk.Frame(tile.surface, bg=INPUT)
        line.place(relx=.5, y=42, anchor='n', width=180, height=32)
        label(line, 'Глава').pack(side='left', padx=(4,8))
        selector = create_field(line,'choice',variable=chapter,
                                options=[(str(n),str(n)) for n in range(1,7)],height=32)
        selector.pack(side='left', fill='x', expand=True)
        record['chapter_line'] = line
        if row is None:
            line.place_forget()
        chapter.trace_add('write', lambda *_:self.changed())
        instance.trace_add('write', lambda *_:self.changed())
        count.trace_add('write', lambda *_:self.changed())
        self.reflow()
        if notify:self.changed()

    def choose_item(self, variable):
        options=sorted(((item.title+' / '+item.instance,item.instance)
                        for item in self.controller.app.repo.items),key=lambda r:r[0].casefold())
        if not options:
            return self.error(ValueError('В проекте нет доступных предметов.'))
        def choose(index):
            value=options[index][1]
            variable.set(value)
            window.destroy()
            # Convert the empty '+' square into an editable item and create the next square.
            if variable is self.rows[-1]['item']:
                row=self.rows[-1]
                row['chapter_line'].place(relx=.5, y=42, anchor='n', width=180, height=32)
                self.add_row(None)
            self.changed()
        window=ValueChoiceWindow(self.controller.app,options,-1,'Выбрать товар',choose,
                                 lambda:window.destroy(),searchable=True)
        window.show()

    def remove_row(self, record):
        if record not in self.rows:return
        record['frame'].destroy()
        self.rows.remove(record)
        if not self.rows or self.rows[-1]['item'].get():
            self.add_row(None,notify=False)
        self.reflow()
        self.changed()

    def reflow(self):
        if not hasattr(self,'tiles_frame') or not self.tiles_frame.winfo_exists():return
        size=ItemBindingTile.SIZE
        columns=max(1,(max(size,self.tiles_frame.winfo_width())+12)//(size+12))
        for i, row in enumerate(self.rows):
            row['frame'].grid(row=i//columns,column=i%columns,padx=6,pady=8,sticky='n')

    def import_goods(self):
        root=self.controller.app.repo.game
        if root is None:return self.error(ValueError('Не задан путь к Gothic.'))
        try:
            from gothic_editor.core.trading_import import game_trade_goods
            goods=game_trade_goods(root/'_work/Data/Scripts/Content')
            if not goods:
                raise ValueError('Не найдены товары в торговых скриптах Gothic.')
            def apply(selected):
                existing={(r['item'].get().casefold(),r['chapter'].get()) for r in self.rows if r['item'].get()}
                for good in selected:
                    key=(good['item'].casefold(),str(good['chapter']))
                    if key not in existing:
                        self.add_row(good)
                        existing.add(key)
            TradingGoodsDialog(self.controller.app,goods,apply).show_centered(modal=True)
        except (OSError,ValueError) as exc:self.error(exc)

    def save(self):
        if not self.npc or not self._dirty:return True
        try:
            stock = [dict(item=row['item'].get().strip(), quantity=int(row['count'].get()),
                          chapter=int(row['chapter'].get())) for row in self.rows if row['item'].get().strip()]
            config = dict(enabled=self.enabled.get(),dialog=self.dialog.get(),
                          dialog_text=self.dialog_text.get(),replace_original=self.replace.get(),
                          min_chapter=int(self.chapter.get()),refresh_hours=int(self.hours.get()),stock=stock)
            TradingStore.validate(config)
            available={item.instance.casefold() for item in self.controller.app.repo.items}
            for row in stock:
                if row['item'].casefold() not in available:
                    raise ValueError('Неизвестный предмет: '+row['item'])
            store=TradingStore(self.controller.app.repo.root)
            saved=self.controller.app.history.capture((store.path,))
            store.save(self.npc,config)
            self.controller.app.history.record(saved)
            self._dirty=False
            self.status.config(text='Сохранено')
            return True
        except (ValueError,OSError) as exc:
            self.error(exc)
            return False

    def error(self, exc):
        self.controller.app.terminal.append('Торговля '+str(self.npc)+': '+str(exc))
        self.status.config(text=str(exc))
