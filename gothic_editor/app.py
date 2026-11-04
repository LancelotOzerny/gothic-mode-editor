"""Gothic Editor desktop entry — orchestrates views and repository."""
from __future__ import annotations
import os,tkinter as tk
from pathlib import Path
from tkinter import filedialog,messagebox,ttk,simpledialog
from .core.project import ProjectRepository
from .ui.widgets import BG,PANEL,TXT,MUTED,label
from .ui.hierarchy import HierarchyPanel
from .ui.properties import PropertiesPanel
from .ui.viewer import ModelViewer,read_3ds,MeshFormatError

class EditorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Gothic Editor — 0.2')
        self.geometry('1240x760');self.minsize(870,540)
        self.configure(bg=BG)
        self.repo=ProjectRepository()
        self.current=None
        self._build_menu();self._build_layout()
        self.bind_all('<Control-o>',lambda e:self.open_project())
        self.bind_all('<Control-s>',lambda e:self.properties.save())

    def _build_menu(self):
        menu=tk.Menu(self)
        file=tk.Menu(menu,tearoff=False)
        file.add_command(label='Создать проект...',command=self.create_project)
        file.add_command(label='Открыть проект...',command=self.open_project,accelerator='Ctrl+O')
        file.add_separator();file.add_command(label='Обновить данные',command=self.refresh)
        file.add_separator();file.add_command(label='Выход',command=self.destroy)
        menu.add_cascade(label='Файл',menu=file)
        project=tk.Menu(menu,tearoff=False)
        settings=tk.Menu(project,tearoff=False)
        resources=tk.Menu(settings,tearoff=False)
        resources.add_command(label='Путь к файлам Gothic 2...',command=self.select_game)
        resources.add_command(label='Отключить Gothic 2',command=self.clear_game)
        settings.add_cascade(label='Ресурсы',menu=resources)
        project.add_cascade(label='Настройки',menu=settings)
        menu.add_cascade(label='Проект',menu=project)
        self.config(menu=menu)

    def _build_layout(self):
        header=tk.Frame(self,bg=BG);header.pack(fill='x',padx=14,pady=12)
        label(header,'Режим:',bg=BG,font=('Arial',11)).pack(side='left',padx=(0,10))
        self.mode=ttk.Combobox(header,values=['Предметы'],state='readonly',width=19)
        self.mode.current(0);self.mode.pack(side='left')
        self.project_label=label(header,'Проект не открыт',bg=BG,fg=MUTED,anchor='e')
        self.project_label.pack(side='right',fill='x',expand=True)
        panes=tk.PanedWindow(self,orient='horizontal',bg=BG,bd=0,sashwidth=7)
        panes.pack(fill='both',expand=True,padx=9,pady=(0,8))
        self.hierarchy=HierarchyPanel(panes,self.select,self.create_item,self.duplicate,self.delete,self.rename)
        panes.add(self.hierarchy,width=300,minsize=225)
        middle=tk.Frame(panes,bg='#191e29')
        panes.add(middle,width=550,minsize=250)
        self.viewer=ModelViewer(middle)
        self.viewer.pack(fill='both',expand=True)
        self.properties=PropertiesPanel(panes,self.save_fields)
        panes.add(self.properties,width=350,minsize=240)
        self.status=tk.StringVar(value='Файл → Создать проект, затем Проект → Настройки → Ресурсы → Путь к файлам Gothic 2')
        label(self,textvariable=self.status,bg=BG,fg=MUTED,anchor='w').pack(fill='x',padx=14,pady=(0,8))

    def need_project(self):
        if self.repo.root is None:
            messagebox.showinfo('Проект','Сначала создайте или откройте отдельный проект Gothic Editor.')
            return False
        return True

    def create_project(self):
        base=filedialog.askdirectory(title='Выберите папку нового проекта (можно пустую)')
        if not base:return
        name=simpledialog.askstring('Новый проект','Название проекта:',initialvalue=Path(base).name,parent=self)
        if not name:return
        try:self.repo.create(Path(base),name);self.show_project()
        except Exception as exc:messagebox.showerror('Создание проекта',str(exc))

    def open_project(self):
        base=filedialog.askdirectory(title='Папка с project.json')
        if not base:return
        try:self.repo.open(Path(base));self.show_project()
        except Exception as exc:messagebox.showerror('Открытие проекта',str(exc))

    def show_project(self):
        self.current=None
        self.project_label.config(text=f'{self.repo.name}   |   {self.repo.root}')
        self.update_hierarchy()
        self.viewer.set_mesh(caption='Выберите предмет слева')
        self.properties.show(None)

    def select_game(self):
        if not self.need_project():return
        chosen=filedialog.askdirectory(title='Корневая папка Gothic II или папка распакованных .d-скриптов')
        if not chosen:return
        try:self.repo.set_game_path(chosen);self.show_project()
        except Exception as exc:messagebox.showerror('Ресурсы',str(exc))

    def clear_game(self):
        if not self.need_project():return
        self.repo.set_game_path('');self.show_project()

    def refresh(self):
        if not self.need_project():return
        try:self.repo.refresh();self.update_hierarchy()
        except Exception as exc:messagebox.showerror('Обновление',str(exc))

    def update_hierarchy(self):
        self.hierarchy.set_items(self.repo.items)
        project_count=sum(x.origin=='project' for x in self.repo.items)
        self.status.set(f'Предметов: {len(self.repo.items)}  ·  в проекте: {project_count}  ·  моделей .3DS: {len(self.repo.mesh_index)}  ·  ошибок чтения: {len(self.repo.errors)}')

    def select(self,item):
        self.current=item
        self.properties.show(item)
        visual=item.visual
        mesh=self.repo.mesh_index.get(Path(visual.replace('\\','/')).name.lower()) if visual else None
        if mesh is None:
            self.viewer.set_mesh(caption=f'Нет доступной модели .3DS\n\n{visual or "Поле visual не задано"}\n\nМодели внутри VDF/MRM пока не читаются.\nРаспакуйте .3DS в Assets/Models проекта.')
            return
        try:
            verts,faces=read_3ds(mesh)
            self.viewer.set_mesh(verts,faces,caption=mesh.name)
        except (OSError,MeshFormatError,ValueError) as exc:
            self.viewer.set_mesh(caption=f'Не удалось открыть модель:\n{exc}')

    def _action(self,method,*args):
        if not self.need_project():return
        try:
            result=method(*args)
            self.update_hierarchy()
            if result is not None:
                self.hierarchy.choose(result);self.select(result)
            return result
        except Exception as exc:
            messagebox.showerror('Ошибка',str(exc))

    def create_item(self,key):self._action(self.repo.create_item,key)
    def duplicate(self,item):self._action(self.repo.duplicate,item)

    def delete(self,item):
        if item.origin!='project':return
        if not messagebox.askyesno('Удалить предмет',f'Удалить {item.instance} из проекта?\nОригинальные файлы игры не изменятся.'):
            return
        self._action(self.repo.delete,item)
        self.current=None;self.properties.show(None);self.viewer.set_mesh(caption='Выберите предмет слева')

    def rename(self,item,new_name):
        # The Daedalus name attribute is the in-game name, not INSTANCE.
        escaped=new_name.replace('\\','\\\\').replace('"','\\"')
        self.save_fields(item,{'name':'"'+escaped+'"'})

    def save_fields(self,item,values):
        self._action(self.repo.edit,item,values)


def main():EditorApp().mainloop()
