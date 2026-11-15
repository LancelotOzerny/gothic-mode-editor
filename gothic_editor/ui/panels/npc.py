"""Only NPC names and appearance are editable; gameplay settings stay in scripts."""
import tkinter as tk

from gothic_editor.ui.widgets import label, MUTED
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea


class NpcPropertiesPanel(Panel):
    def __init__(self,parent,controller):
        super().__init__(parent)
        self.controller=controller
        self.fields={}
        self.reset_button=None
        label(self,'Свойства NPC',font=('Arial',10,'bold')).pack(fill='x',padx=14,pady=(14,4))
        self.status=label(self,'Выберите NPC',fg=MUTED,wraplength=280)
        self.status.pack(fill='x',padx=14,pady=(0,20))
        self.area=ScrollableArea(self)
        self.area.pack(fill='both',expand=True)

    def show(self,npc):
        for child in self.area.content.winfo_children():child.destroy()
        self.fields={}
        self.reset_button=None
        if npc is None:
            self.status.config(text='Выберите NPC')
            return
        self.status.config(text=npc.instance)
        main=self.add_group('Основное',parent=self.area.content)
        main.add_field('Код NPC',value=npc.instance,readonly=True)
        self.fields['name']=main.add_field('Имя',value=npc.title)
        appearance=self.add_group('Внешность',parent=self.area.content)
        index=self.controller.index
        for key,title,value in (('visual','Скелет и анимации',npc.visual),('body','Модель тела',npc.body),
                                ('head','Модель головы',npc.head),('armor','Броня',npc.armor)):
            options=index.options(key) if key!='armor' else [('Нет','-1')]+self.controller.armor_options()
            if value not in [option[1] for option in options]:options=[(value,value)]+options
            self.fields[key]=appearance.add_field(title,kind='choice',value=value,options=options,
                enabled=bool(npc.body_args),tooltip='Броня перекрывает модель тела.' if key=='armor' else '')
        for kind,title in (('body','Импорт модели тела (MDM)'),('head','Импорт модели головы (MMB)')):
            button=appearance.add_button(title,lambda field=kind:self.controller.import_model(field))
            if not npc.body_args:button.config(state='disabled')
        self.reset_button=appearance.add_button('Отменить изменения NPC',self.controller.reset)
        self.reset_button.config(state='normal' if npc.overridden else 'disabled')
        for key,field in self.fields.items():
            self.controller.watch(key,field)
