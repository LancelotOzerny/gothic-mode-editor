"""Media hierarchy and inspector following the editor's existing three-column layout."""
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path

from gothic_editor.core.game_media import CATEGORIES, GameMedia
from gothic_editor.core.textures import read_texture
from gothic_editor.ui.widgets import PANEL, BG, TXT, MUTED, label
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea
from .hierarchy import HierarchyBrowser, HierarchyCategory, CategoryRow, HierarchyRow


class MediaPanel(HierarchyBrowser):
    """Use the exact category/row widgets shared with World and NPC."""
    def __init__(self, parent, on_select, on_load, on_import):
        super().__init__(parent)
        self.on_select, self.on_load, self.on_import=on_select,on_load,on_import
        self.owner,self.origin=self,'project'
        self.resources={}
        self.entries={}
        self.grouped={}
        self.category_rows={}
        self.rows={}
        self.selected=None
        self.area=ScrollableArea(self)
        self.area.pack(fill='both',expand=True)
        self.search.trace_add('write',lambda *_:self.rebuild())
        self.rebuild()

    def set_resources(self,resources,loaded,selected=()):
        self.resources={row.kind+':'+row.name.casefold():row for row in resources
                        if row.category in loaded or row.overridden
                        or row.kind+':'+row.name.casefold() in selected}
        self.rebuild()

    def rebuild(self):
        position=self.area.canvas.yview()
        for child in self.area.content.winfo_children():child.destroy()
        self.grouped={}
        self.entries={}
        self.category_rows={}
        self.rows={}
        query=self.search.get().strip().casefold()
        for code,title in CATEGORIES.items():
            matching={key:row for key,row in self.resources.items()
                      if row.category==code and (not query or query in row.name.casefold()
                                                 or query in title.casefold())}
            self.entries.update(matching)
            self.grouped[code]=list(matching)
            CategoryRow(self,self.area.content,HierarchyCategory(code,title),0)
        if query and not self.entries:
            label(self.area.content,'Ничего не найдено',fg=MUTED).pack(padx=12,pady=15)
        self.area.canvas.yview_moveto(position[0] if position else 0)

    def count(self,category):
        return len(self.grouped.get(category.key,()))

    def bind_category(self,row,category):
        super().bind_category(row,category)
        row.header.bind_row('<Button-3>',
                            lambda event,key=category.key:self.context(event,key))

    def row_item(self,parent,key,level):
        resource=self.entries[key]
        title=resource.name+('  • Проект' if resource.overridden else '')
        row=HierarchyRow(parent,title,level)
        self.rows[key]=row
        row.set_selected(key==self.selected)
        self.bind_activate(row,lambda:self.select(key))
        row.bind_row('<Button-3>',lambda event:self.context(event,resource.category))

    def select(self,key):
        resource=self.entries[key]
        if self.on_select(resource) is False:return False
        previous=self.rows.get(self.selected)
        if previous is not None:previous.set_selected(False)
        self.selected=key
        self.select_category(None)
        row=self.rows.get(key)
        if row is not None:row.set_selected(True)
        return True

    def context(self,event,category):
        self.popup(event,[('Импортировать файл из Gothic…',
                           lambda:self.on_import(category)),
                          ('Загрузить все файлы медиа',
                           lambda:self.on_load(category))])

    def expand(self,category):
        row=self.category_rows.get(category)
        if row is not None and not row.opened:row.toggle()


class MediaPreview(Panel):
    """Reuse the editor's central viewport for the selected image."""
    def __init__(self,parent):
        super().__init__(parent,bg=BG)
        self.resource=None
        self.texture=None
        self.photo=None
        self.caption='Выберите изображение'
        self.canvas=tk.Canvas(self,bg=BG,highlightthickness=0)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',self.redraw)
        self._video_decoder=None
        self._video_paused=False
        self._video_after=None
        self._video_temp=None
        self.bind('<Destroy>',self._close_video,add='+')

    def play_video(self,game):
        """Render the installed game's Bink decoder output on our own Tk canvas."""
        import tempfile
        from gothic_editor.core.bink_decoder import BinkDecoder
        resource=self.resource
        if resource is None or resource.kind!='videos':return
        self._close_video()
        try:
            source=resource.source
            if isinstance(source,Path):
                path=source
            else:
                self._video_temp=tempfile.TemporaryDirectory(prefix='gothic-video-')
                path=Path(self._video_temp.name)/resource.name
                path.write_bytes(source.read_bytes())
            self._video_decoder=BinkDecoder(game,path)
            self._video_paused=False
            self._video_frame()
        except Exception:
            self._close_video()
            raise

    def pause_video(self):
        if self._video_decoder is not None:
            self._video_paused=not self._video_paused
            if self._video_paused and self._video_after is not None:
                self.after_cancel(self._video_after)
                self._video_after=None
            if not self._video_paused:self._video_frame()

    def _video_frame(self):
        decoder=self._video_decoder
        if decoder is None or self._video_paused:return
        data=decoder.next_frame()
        if data is None:
            self._close_video()
            return
        ppm=f'P6\n{decoder.width} {decoder.height}\n255\n'.encode('ascii')+data
        self.photo=tk.PhotoImage(master=self,data=ppm,format='PPM')
        self.texture=None
        self.canvas.delete('all')
        self.canvas.create_image(self.canvas.winfo_width()//2,
                                 self.canvas.winfo_height()//2,image=self.photo)
        self.canvas.create_text(12,10,text=f'{decoder.number}/{decoder.frames}',
                                anchor='nw',fill=MUTED)
        self._video_after=self.after(decoder.interval_ms,self._video_frame)

    def _close_video(self,event=None):
        if event is not None and event.widget is not self:return
        after=self._video_after
        self._video_after=None
        if after is not None:
            try:self.after_cancel(after)
            except tk.TclError:pass
        decoder=self._video_decoder
        self._video_decoder=None
        if decoder is not None:decoder.close()
        if self.resource is not None and self.resource.kind=='videos':
            self.caption='Видео остановлено'
            self.photo=None
            if event is None:self.redraw()
        temporary=self._video_temp
        self._video_temp=None
        if temporary is not None:
            try:temporary.cleanup()
            except OSError:pass

    def show(self,resource):
        self._close_video()
        self.resource=resource
        self.texture=None
        self.photo=None
        if resource is not None and resource.kind=='images':
            try:self.texture=read_texture(resource.source.read_bytes())
            except (OSError,ValueError) as exc:
                self.caption='Ошибка чтения: '+str(exc)
            else:self.caption=''
        else:
            self.caption='Выберите изображение' if resource is None else 'Видео BIK: предпросмотр недоступен'
        self.redraw()

    def redraw(self,_event=None):
        self.canvas.delete('all')
        width=max(1,self.canvas.winfo_width())
        height=max(1,self.canvas.winfo_height())
        if self._video_decoder is not None and self.photo is not None:
            self.canvas.create_image(width//2,height//2,image=self.photo)
            return
        if self.texture is None:
            self.canvas.create_text(width//2,height//2,text=self.caption,
                                    fill=MUTED,font=('Arial',13),width=max(150,width-35))
            return
        texture=self.texture
        scale=max(1,(texture.width+width-31)//max(1,width-30),
                  (texture.height+height-31)//max(1,height-30))
        out_w=(texture.width+scale-1)//scale
        out_h=(texture.height+scale-1)//scale
        rgb=bytearray(out_w*out_h*3)
        pos=0
        for y in range(0,texture.height,scale):
            for x in range(0,texture.width,scale):
                offset=(y*texture.width+x)*4
                rgb[pos:pos+3]=texture.pixels[offset:offset+3]
                pos+=3
        ppm=f'P6\n{out_w} {out_h}\n255\n'.encode('ascii')+rgb
        try:self.photo=tk.PhotoImage(master=self,data=ppm,format='PPM')
        except tk.TclError as exc:
            self.texture=None
            self.caption='Не удалось показать изображение: '+str(exc)
            self.redraw()
            return
        self.canvas.create_image(width//2,height//2,image=self.photo)
        self.canvas.create_text(12,10,text=f'{texture.width} × {texture.height}',
                                anchor='nw',fill=MUTED,font=('Arial',10))


class MediaPropertiesPanel(Panel):
    def __init__(self,parent,app):
        super().__init__(parent)
        self.app=app
        self.current=None
        self.photo=None
        label(self,'Свойства медиа',font=('Arial',10,'bold')).pack(fill='x',padx=14,pady=(14,8))
        self.caption=label(self,'Выберите файл в иерархии',fg=MUTED,wraplength=280)
        self.caption.pack(fill='x',padx=14,pady=(0,14))
        self.area=ScrollableArea(self)
        self.area.pack(fill='both',expand=True)

    def show(self,resource):
        self.current=resource
        self.photo=None
        for child in self.area.content.winfo_children():child.destroy()
        self.caption.config(text=resource.name if resource else 'Выберите файл в иерархии')
        if resource is None:return
        group=self.add_group('Ресурс',parent=self.area.content)
        group.add_field('Название в Gothic',value=resource.name,readonly=True)
        label(group.body,'Заменён в проекте' if resource.overridden else 'Оригинал Gothic',
              fg=MUTED).pack(fill='x',padx=8,pady=6)
        origin=resource.source
        origin_label=(origin.archive.name if hasattr(origin,'archive') else str(origin))
        group.add_field('Источник',value=origin_label,readonly=True)
        group.add_button('Заменить изображение' if resource.kind=='images' else 'Заменить видео BIK',
                         self.replace)
        group.add_button('Экспортировать PNG' if resource.kind=='images' else 'Экспортировать BIK',
                         self.export)
        if resource.kind=='videos':
            group.add_button('Воспроизвести BIK',self.play)
            group.add_button('Пауза / продолжить',self.app.media_viewer.pause_video)
            group.add_button('Остановить',self.app.media_viewer._close_video)
        if resource.overridden:group.add_button('Отменить замену',self.remove)
        if resource.kind=='videos':
            label(group.body,'Встроенный просмотр использует Bink-библиотеку Gothic. Звук пока не поддерживается.',
                  fg=MUTED,wraplength=280).pack(fill='x',padx=8,pady=8)
        else:
            label(group.body,'Изображение показано в центральном окне.',
                  fg=MUTED,wraplength=280).pack(fill='x',padx=8,pady=8)

    def export(self):
        row=self.current
        if row is None:return
        ext='.bik' if row.kind=='videos' else '.png'
        name=Path(row.name).stem
        if name.lower().endswith('-c'):name=name[:-2]
        destination=filedialog.asksaveasfilename(
            parent=self,title='Экспорт медиа',
            initialfile=name+ext,defaultextension=ext,
            filetypes=[('Видео BIK','*.bik')] if row.kind=='videos' else [('Изображение PNG','*.png')])
        if not destination:return
        try:GameMedia.export_file(row,destination)
        except (OSError,ValueError) as exc:
            messagebox.showerror('Экспорт медиа',str(exc),parent=self)

    def play(self):
        try:self.app.media_viewer.play_video(self.app.repo.game)
        except (OSError,ValueError) as exc:
            messagebox.showerror('Просмотр BIK',str(exc),parent=self)

    def replace(self):
        row=self.current
        if row is None:return
        media=GameMedia(self.app.repo.root)
        filters=[('Изображения','*.png *.jpg *.jpeg *.tga *.tex')] if row.kind=='images' else [('Видео BIK','*.bik')]
        source=filedialog.askopenfilename(parent=self,title='Выберите замену для '+row.name,filetypes=filters)
        if not source:return
        try:
            target=media.path(row.kind,row.name)
            saved=self.app.history.capture((target,))
            if row.kind=='images':media.replace_image(row.name,source)
            else:media.import_file('videos',row.name,source)
            self.app.history.record(saved)
            self.app.load_media(keep=True)
        except (OSError,ValueError) as exc:
            messagebox.showerror('Медиа',str(exc),parent=self)

    def remove(self):
        row=self.current
        if row is None:return
        media=GameMedia(self.app.repo.root)
        target=media.path(row.kind,row.name)
        try:
            saved=self.app.history.capture((target,))
            media.delete(row.kind,row.name)
            self.app.history.record(saved)
            self.app.load_media(keep=True)
        except (OSError,ValueError) as exc:
            messagebox.showerror('Медиа',str(exc),parent=self)
