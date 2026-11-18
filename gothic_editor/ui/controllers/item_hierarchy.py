"""Editor-only hierarchy actions, sharing the existing inspector and dialogs."""
from tkinter import messagebox
from gothic_editor.core.categories import walk_categories
from gothic_editor.ui.windows.dialog import EditorDialog
from gothic_editor.ui.widgets.form import FormGroup


class ItemHierarchyController:
    def __init__(self, app):
        self.app = app

    def select(self, node):
        app = self.app
        if not app._save_editors():return False
        app._cancel_model_load()
        app.current = None
        app.viewer.set_inventory_source(None)
        app.viewer.set_mesh(caption=node.name)
        app.resources.set_item(app.repo.root,None)
        app.properties.show_node(node,self.rename)
        return True

    def rename(self, node, name):
        self.app.repo.item_hierarchy.rename(node.key,name)
        node.name = name.strip()
        self.app.hierarchy.rebuild()

    def move(self, item, key):
        if not self.app._save_editors():return
        try:
            self.app.repo.item_hierarchy.assign(item,key)
            self.app.update_hierarchy()
            self.app.hierarchy.choose(item)
        except (ValueError,OSError) as exc:messagebox.showerror('Иерархия',str(exc),parent=self.app)

    def action(self, action, node):
        app = self.app
        if not app._save_editors():return
        store = app.repo.item_hierarchy
        try:
            key = node.key
            if action == 'rename':
                dialog = EditorDialog(app)
                dialog.title('Переименовать')
                group = FormGroup(dialog,'Группа' if node.kind=='group' else 'Категория')
                group.pack(fill='both',expand=True,padx=16,pady=16)
                code = group.add_field('Код',value=node.code) if node.kind=='category' else None
                name = group.add_field('Название',value=node.name)
                def save():
                    try:store.rename(key,name.get(),code.get() if code else None)
                    except (OSError,ValueError) as exc:
                        messagebox.showerror('Иерархия',str(exc),parent=dialog)
                        return
                    dialog.destroy()
                    self.refresh(key)
                group.add_button('Сохранить',save)
                group.add_button('Отмена',dialog.destroy)
                dialog.bind('<Escape>',lambda _:dialog.destroy())
                dialog.show_centered(modal=True)
                return
            if action == 'create':key = store.create_group(key)
            elif action == 'duplicate':key = store.duplicate(key)[key]
            elif action == 'delete':
                if not messagebox.askyesno('Удалить',
                        'Удалить «'+node.name+'» и вложенные группы? Предметы сохранятся.',parent=app):return
                store.delete(key)
                app.properties.show(None)
                app.hierarchy.selected_node = None
                app.update_hierarchy()
                return
            elif action == 'add':
                result = app.create_item(node.source)
                if result is not None:self.move(result,key)
                return
            self.refresh(key)
        except (ValueError,OSError) as exc:messagebox.showerror('Иерархия',str(exc),parent=app)

    def refresh(self, key):
        panel = self.app.hierarchy
        nodes = list(walk_categories(self.app.repo.item_hierarchy.tree()))
        node = next(node for node in nodes if node.key==key)
        parent = node.parent
        while parent:
            panel.expanded[('project',parent)] = True
            parent = next(value.parent for value in nodes if value.key==parent)
        panel.selected_node = key
        self.app.update_hierarchy()
        self.select(node)
