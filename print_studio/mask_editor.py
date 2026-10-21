"""Full-resolution mask painting with a tiled viewport and bounded patch undo."""
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageChops, ImageDraw, ImageTk
from print_studio.core import load_image, save_png


class MaskEditor:
    def __init__(self, root, base_path, mask_path, on_save=None, allow_empty=False, caption=None):
        self.base = load_image(base_path); self.path = mask_path; self.on_save = on_save
        self.allow_empty = allow_empty
        with Image.open(mask_path) as image: self.mask = image.convert('L')
        if self.mask.size != self.base.size: raise ValueError('蒙版与底图尺寸不一致')
        self.window = tk.Toplevel(root); self.window.title('全分辨率蒙版编辑 · 红色为印花区域'); self.window.geometry(f'{min(1050,max(900,root.winfo_screenwidth()-60))}x{min(800,max(650,root.winfo_screenheight()-90))}')
        self.zoom = min(940 / self.base.width, 620 / self.base.height, 1)
        self.brush = tk.IntVar(value=20); self.erase = tk.BooleanVar(value=False)
        self.history = []; self.pending = None; self.before = None; self.last = None; self.bounds = None
        toolbar = ttk.Frame(self.window, padding=8); toolbar.pack(fill='x')
        ttk.Button(toolbar, text='放大＋', command=lambda:self.scale(1.5)).pack(side='left')
        ttk.Button(toolbar, text='缩小－', command=lambda:self.scale(1/1.5)).pack(side='left', padx=4)
        ttk.Label(toolbar, text='画笔（屏幕像素）').pack(side='left', padx=(10,0))
        ttk.Scale(toolbar, from_=2, to=100, variable=self.brush, length=150).pack(side='left')
        ttk.Checkbutton(toolbar, text='橡皮擦', variable=self.erase).pack(side='left', padx=8)
        ttk.Button(toolbar, text='撤销', command=self.undo).pack(side='left')
        ttk.Button(toolbar, text='保存蒙版', command=self.save).pack(side='right')
        frame = ttk.Frame(self.window); frame.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(frame, bg='#344656', highlightthickness=0)
        xs = ttk.Scrollbar(frame, orient='horizontal', command=lambda *a:self.scroll('x',*a))
        ys = ttk.Scrollbar(frame, orient='vertical', command=lambda *a:self.scroll('y',*a))
        self.canvas.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)
        self.canvas.grid(row=0,column=0,sticky='nsew'); ys.grid(row=0,column=1,sticky='ns'); xs.grid(row=1,column=0,sticky='ew')
        frame.columnconfigure(0,weight=1); frame.rowconfigure(0,weight=1)
        self.info = tk.StringVar(); ttk.Label(self.window,textvariable=self.info,padding=8).pack(anchor='w')
        ttk.Label(self.window,text=caption or '涂出当前可印花部件；避开皮肤、头发、挂架、轮廓线和生产标记。编辑不会缩小蒙版。',padding=(8,0,8,8)).pack(anchor='w')
        self.canvas.bind('<Configure>',lambda e:self.schedule())
        self.canvas.bind('<Button-1>',self.press); self.canvas.bind('<B1-Motion>',self.paint); self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<MouseWheel>',self.wheel); self.canvas.bind('<Button-4>',lambda e:self.scroll('y','scroll',-3,'units')); self.canvas.bind('<Button-5>',lambda e:self.scroll('y','scroll',3,'units'))
        self.window.protocol('WM_DELETE_WINDOW',self.close); self.schedule()

    def scroll(self,axis,*args):
        (self.canvas.xview if axis=='x' else self.canvas.yview)(*args); self.schedule()

    def wheel(self,event):
        if event.state & 4: self.scale(1.2 if event.delta>0 else 1/1.2)
        else:self.scroll('y','scroll',-3 if event.delta>0 else 3,'units')
        return 'break'

    def scale(self,factor):
        self.zoom = max(.04,min(4,self.zoom*factor)); self.schedule()

    def schedule(self):
        if self.pending: self.window.after_cancel(self.pending)
        self.pending = self.window.after(25,self.redraw)

    def redraw(self):
        self.pending = None; w,h=self.base.size; z=self.zoom
        self.canvas.configure(scrollregion=(0,0,round(w*z),round(h*z)))
        x=max(0,int(self.canvas.canvasx(0)/z)); y=max(0,int(self.canvas.canvasy(0)/z))
        right=min(w,x+int(max(1,self.canvas.winfo_width())/z)+2); bottom=min(h,y+int(max(1,self.canvas.winfo_height())/z)+2)
        if right<=x or bottom<=y:return
        box=(x,y,right,bottom); size=(max(1,round((right-x)*z)),max(1,round((bottom-y)*z)))
        base=self.base.crop(box).resize(size,Image.Resampling.BILINEAR); mask=self.mask.crop(box).resize(size,Image.Resampling.NEAREST)
        tinted=Image.blend(base,Image.new('RGB',size,'#fb5173'),.5)
        view=Image.composite(tinted,base,mask)
        self.photo=ImageTk.PhotoImage(view); self.canvas.delete('view'); self.canvas.create_image(x*z,y*z,image=self.photo,anchor='nw',tags='view')
        self.info.set(f'原始尺寸 {w} × {h} 像素 · 缩放 {z*100:.0f}% · Ctrl＋滚轮缩放 · 拖动滚动条查看边缘')

    def point(self,event):
        return (max(0,min(self.mask.width-1,round(self.canvas.canvasx(event.x)/self.zoom))),
                max(0,min(self.mask.height-1,round(self.canvas.canvasy(event.y)/self.zoom))))

    def press(self,event):
        self.before=self.mask.copy(); self.bounds=None; self.last=self.point(event); self.paint(event)

    def paint(self,event):
        if self.before is None:return
        p=self.point(event); width=max(1,round(float(self.brush.get())/self.zoom)); radius=width/2; color=0 if self.erase.get() else 255
        draw=ImageDraw.Draw(self.mask); draw.line([self.last,p],fill=color,width=width)
        draw.ellipse((p[0]-radius,p[1]-radius,p[0]+radius,p[1]+radius),fill=color)
        box=(max(0,int(min(self.last[0],p[0])-radius-2)),max(0,int(min(self.last[1],p[1])-radius-2)),min(self.mask.width,int(max(self.last[0],p[0])+radius+3)),min(self.mask.height,int(max(self.last[1],p[1])+radius+3)))
        self.bounds=box if self.bounds is None else (min(self.bounds[0],box[0]),min(self.bounds[1],box[1]),max(self.bounds[2],box[2]),max(self.bounds[3],box[3]))
        self.last=p; self.schedule()

    def release(self,event=None):
        if self.before is not None and self.bounds:
            self.history.append((self.bounds,self.before.crop(self.bounds)))
            while len(self.history)>20 or sum(p.width*p.height for _,p in self.history)>80_000_000:
                self.history.pop(0)
        self.before=None; self.bounds=None; self.last=None

    def undo(self):
        self.release()
        if self.history:
            box,patch=self.history.pop(); self.mask.paste(patch,box); self.schedule()

    def save(self):
        self.release()
        if not self.mask.getbbox() and not self.allow_empty:return messagebox.showinfo('蒙版为空','请先涂抹印花区域',parent=self.window)
        try:
            save_png(self.mask,self.path)
            if self.on_save:self.on_save()
            self.close()
        except Exception as error:messagebox.showerror('保存失败',str(error),parent=self.window)

    def close(self):
        if self.pending:self.window.after_cancel(self.pending);self.pending=None
        self.window.destroy();self.base.close();self.mask.close();self.history.clear()
