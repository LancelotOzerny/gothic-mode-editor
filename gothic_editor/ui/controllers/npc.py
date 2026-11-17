"""Debounced NPC metadata saves and asynchronous neutral-pose previews."""
import tkinter as tk
from tkinter import filedialog, messagebox

from gothic_editor.core.npcs import NpcCatalog,NpcStore
from gothic_editor.core.npc_models import NpcModelIndex,load_npc_preview
from gothic_editor.core.project_selection import ProjectSelection
from gothic_editor.ui.windows.value_choice import ValueChoiceWindow


class NpcController:
    def __init__(self,app):
        self.app=app
        self.current=None
        self.catalog=None
        self.items=[]
        self.index=None
        self.stamp=None
        self.pending=None
        self.traces=[]
        self.initial={}

    @property
    def store(self):return NpcStore(self.app.repo.root)

    def refresh(self):
        repo=self.app.repo
        stamp=(repo.root,repo.game,repo.resource_revision)
        if stamp!=self.stamp:
            self.catalog=NpcCatalog(repo.root,repo.game)
            self.items=self.catalog.load()
            self.index=NpcModelIndex(repo)
            self.stamp=stamp

    def armor_options(self):
        return [(item.title,item.instance) for item in self.app.repo.items if item.instance.casefold() in self.index.armors]

    def show_list(self):
        self.refresh()
        selected=ProjectSelection(self.app.repo.root,'NPC').read()
        self.app.world_panel.set_resources([], [value for value in self.items if value.overridden
            or value.instance.casefold() in selected or self.app.repo.root in value.path.parents])

    def add(self):
        self.refresh()
        options=self.items
        def choose(index):
            npc=options[index]
            ProjectSelection(self.app.repo.root,'NPC').add(npc.instance)
            window.destroy()
            self.show_list()
            self.select(npc)
        window=ValueChoiceWindow(self.app,[(value.title+' / '+value.instance,value.instance) for value in options],-1,
                                 'Добавить NPC из Gothic',choose,lambda:window.destroy())
        window.show()

    def deselect(self):
        if self.pending is not None:
            self.app.after_cancel(self.pending)
            self.pending=None
        for variable,trace in self.traces:variable.trace_remove('write',trace)
        self.traces=[]
        self.current=None

    def remove(self):
        npc=self.current
        if npc is None:return
        if not messagebox.askyesno('Удалить из проекта',
                'Удалить NPC из списка проекта и отменить изменения его свойств?',parent=self.app):return
        try:
            self.store.save(npc.instance,{})
            ProjectSelection(self.app.repo.root,'NPC').remove(npc.instance)
            self.deselect()
            self.stamp=None
            self.app._cancel_model_load()
            self.app.npc_properties.show(None)
            self.show_list()
            self.app.viewer.set_mesh(caption='Выберите NPC')
        except (OSError,ValueError) as exc:messagebox.showerror('NPC',str(exc),parent=self.app)

    def values(self,npc):
        return dict(name=npc.title,visual=npc.visual,body=npc.body,head=npc.head,armor=npc.armor)

    def select(self,npc):
        if not self.app._save_editors():return
        self.deselect()
        self.app._cancel_model_load()
        self.app.current=None
        self.app.world.current=None
        self.app.properties.show(None)
        self.current=self.store.apply(self.catalog.base[npc.instance.casefold()],self.store.read().get(npc.instance.casefold(),{}))
        self.initial=self.values(self.current)
        self.app.npc_properties.show(self.current)
        self.app._show_resource_panels('npc')
        self.preview()

    def watch(self,key,field):
        variable=getattr(field,'variable',None)
        if variable is None:
            variable=tk.StringVar(field,value=field.get())
            field.configure(textvariable=variable)
        trace=variable.trace_add('write',lambda *_:self.changed())
        self.traces.append((variable,trace))

    def changed(self):
        if self.pending is not None:self.app.after_cancel(self.pending)
        self.app.npc_properties.status.config(text='Есть несохранённые изменения')
        self.pending=self.app.after(1000,self.save)

    def save(self):
        if self.pending is not None:
            self.app.after_cancel(self.pending)
            self.pending=None
        if self.current is None:return True
        fields=self.app.npc_properties.fields
        values={key:field.get() for key,field in fields.items()}
        if values==self.initial:return True
        try:
            baseline=self.catalog.base[self.current.instance.casefold()]
            defaults=self.values(baseline)
            updates={key:value for key,value in values.items() if value!=defaults[key]}
            self.store.save(self.current.instance,updates)
            changed_model=any(values[key]!=self.initial[key] for key in ('visual','body','head','armor'))
            self.current=self.store.apply(baseline,updates)
            self.items=[self.current if value.instance==self.current.instance else value for value in self.items]
            self.initial=values
            self.app.world_panel.update_npc(self.current)
            self.app.npc_properties.status.config(text='Сохранено')
            self.app.npc_properties.reset_button.config(state='normal' if updates else 'disabled')
            if changed_model:self.preview((self.app.viewer.angle_x,self.app.viewer.angle_y,self.app.viewer.zoom))
            else:
                self.app.viewer.caption=self.current.title
                self.app.viewer.request_draw()
            return True
        except (OSError,ValueError) as exc:
            self.app.npc_properties.status.config(text=str(exc))
            return False

    def reset(self):
        if self.current is None:return
        try:
            npc=self.current
            self.store.save(npc.instance,{})
            # Reset fields without saving the previous draft back over the reset.
            self.deselect()
            self.items=[self.catalog.base[npc.instance.casefold()] if value.instance==npc.instance else value for value in self.items]
            self.select(self.catalog.base[npc.instance.casefold()])
            self.app.world_panel.update_npc(self.current)
        except (OSError,ValueError) as exc:messagebox.showerror('NPC',str(exc),parent=self.app)

    def import_model(self,kind):
        suffix='mdm' if kind=='body' else 'mmb'
        source=filedialog.askopenfilename(parent=self.app,title='Импорт модели NPC',filetypes=[(suffix.upper(),'*.'+suffix)])
        if not source:return
        try:
            value=self.index.import_model(source,kind)
            self.index=NpcModelIndex(self.app.repo)
            field=self.app.npc_properties.fields[kind]
            field.options=self.index.options(kind)
            field.set_expression(value)
            self.save()
            self.app.resources.refresh()
        except (OSError,ValueError) as exc:messagebox.showerror('NPC',str(exc),parent=self.app)

    def preview(self,camera=None):
        app=self.app
        app._cancel_model_load()
        if self.current is None:return
        npc=self.current
        key=('npc',npc,self.stamp,app.viewer.textured)
        cached=app._preview_cache.get(key)
        if cached is not None:
            app.viewer.set_preview(cached,caption=npc.title,camera=camera)
            return
        future=app._model_executor.submit(load_npc_preview,npc,self.index,self.catalog,app.viewer.textured)
        app._model_future=future
        if camera is None:app.viewer.set_mesh(caption='Загрузка NPC…')
        def finish():
            if future is not app._model_future:return
            app._model_poll=None
            if not future.done():
                app._model_poll=app.after(20,finish)
                return
            app._model_future=None
            try:
                preview=future.result()
                with app._preview_cache.lock:
                    app._preview_cache.entries[key]=preview
                    while len(app._preview_cache.entries)>app._preview_cache.limit:app._preview_cache.entries.popitem(last=False)
                app.viewer.set_preview(preview,caption=npc.title,camera=camera)
            except (OSError,ValueError) as exc:app.viewer.set_mesh(caption=str(exc))
        app._model_poll=app.after(20,finish)
