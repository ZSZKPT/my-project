from PIL import Image, ImageOps, ImageTk
import tkinter as tk
from tkinter import ttk, messagebox


def preview_image(path, bounds=(76,92)):
    """Render a contained preview, honoring orientation without modifying source files."""
    with Image.open(path) as original:
        image=ImageOps.exif_transpose(original)
        image.thumbnail(bounds,Image.Resampling.LANCZOS)
        rgba=image.convert('RGBA')
        background=Image.new('RGB',rgba.size,'white')
        background.paste(rgba,mask=rgba.getchannel('A'))
        return background


def open_preview(parent,path,sku):
    try:
        bounds=(min(960,parent.winfo_screenwidth()-140),min(760,parent.winfo_screenheight()-160))
        image=preview_image(path,bounds)
        owner=parent._root()
        previous=getattr(owner,'_feifan_preview',None)
        if previous is not None and previous.winfo_exists():previous.destroy()
        window=tk.Toplevel(parent)
        owner._feifan_preview=window
        window.title(f'飞凡上架 · {sku} · 主图预览');window.configure(bg='white')
        photo=ImageTk.PhotoImage(image,master=window)
        label=tk.Label(window,image=photo,bg='white',padx=12,pady=12);label.image=photo;label.pack()
        ttk.Label(window,text=path.name,padding=10).pack()
        def close(event=None):
            if getattr(owner,'_feifan_preview',None) is window:owner._feifan_preview=None
            window.destroy()
        window.protocol('WM_DELETE_WINDOW',close)
        window.bind('<Escape>',close)
        return window
    except (OSError,ValueError,Image.DecompressionBombError) as error:
        messagebox.showerror('无法预览图片',str(error),parent=parent)
        return None


def add_thumbnail(app,group,index):
    path=group['files'][0]
    try:
        photo=ImageTk.PhotoImage(preview_image(path),master=app.window)
        app.thumbnails[group['sku']]=photo
        label=ttk.Label(app.table,image=photo,style='Card.TLabel',cursor='hand2')
        label.image=photo
        label.bind('<Button-1>',lambda event,p=path,sku=group['sku']:open_preview(app.window,p,sku))
    except (OSError,ValueError,Image.DecompressionBombError):
        label=ttk.Label(app.table,text='图片损坏\n无法预览',style='Muted.TLabel')
    label.grid(row=index,column=0,padx=(8,12),pady=8,sticky='w')
