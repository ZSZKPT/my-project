"""Tk desktop UI. All network and batch work runs outside the Tk thread."""
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import uuid
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageDraw, ImageTk
from print_studio.api import DEFAULT_PROMPT
from print_studio.core import atomic_json, load_image, mockup, number, proof, settings, template
from print_studio.jobs import Job, scan

ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'assets'


class App:
    def __init__(self, root):
        self.root = root; root.title('飞凡印花设计 · 满版循环'); root.geometry('1240x860'); root.minsize(1000, 700)
        self.files = []; self.templates = []; self.task_path = None; self.busy = False
        self.events = queue.Queue(); self.stop = threading.Event(); self.current_output = None; self.preview_window = None
        self.vars = {k: tk.StringVar(value=v) for k, v in {
            'output': str(Path.home() / 'Documents' / '飞凡印花输出'), 'width_cm': '40', 'height_cm': '40',
            'tile_cm': '12', 'dpi': '150', 'offset_x_cm': '0', 'offset_y_cm': '0',
            'endpoint': 'https://api.openai.com/v1/images/edits', 'model': '', 'size': '1024x1024',
            'protocol': 'OpenAI兼容图像编辑', 'key': '', 'max_calls': '20'}.items()}
        self.use_api = tk.BooleanVar(value=False); self.shade = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value='导入花型即可本地铺图；导入效果图可选择 API 还原')
        self.task_text = tk.StringVar(value='未加载任务')
        self.setup_style(); self.build(); root.after(100, self.poll)
        root.protocol('WM_DELETE_WINDOW', self.close)
        demo = ASSETS / 'demo' / 'template.json'
        if demo.exists(): self.templates = [demo]; self.refresh_templates()

    def setup_style(self):
        self.root.configure(bg='#edf3f6')
        style = ttk.Style(self.root); style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10), background='#edf3f6', foreground='#233647')
        style.configure('TButton', padding=(12, 8), background='#ffffff', borderwidth=1)
        style.configure('Accent.TButton', background='#087e8b', foreground='white', padding=(14, 10))
        style.map('Accent.TButton', background=[('active', '#05636e'), ('disabled', '#afc5ca')])
        style.configure('Card.TFrame', background='white')
        style.configure('Card.TLabel', background='white')
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 13, 'bold'), background='white')
        style.configure('TNotebook.Tab', padding=(16, 9))
        style.configure('Treeview', rowheight=62, background='white', fieldbackground='white')
        style.configure('TProgressbar', background='#0a9c94', troughcolor='#dce8ec')

    def card(self, parent, title):
        frame = ttk.Frame(parent, style='Card.TFrame', padding=14); frame.pack(fill='x', padx=8, pady=7)
        ttk.Label(frame, text=title, style='Title.TLabel').pack(anchor='w', pady=(0, 10))
        return frame

    def field(self, parent, key, label, browse=False):
        ttk.Label(parent, text=label, style='Card.TLabel').pack(anchor='w', pady=(5, 3))
        row = ttk.Frame(parent, style='Card.TFrame'); row.pack(fill='x')
        ttk.Entry(row, textvariable=self.vars[key]).pack(side='left', fill='x', expand=True)
        if browse: ttk.Button(row, text='选择', command=self.choose_output).pack(side='left', padx=(5, 0))

    def build(self):
        header = tk.Frame(self.root, bg='#132e40', padx=22, pady=15); header.pack(fill='x')
        tk.Label(header, text='飞凡印花设计', bg='#132e40', fg='white', font=('Microsoft YaHei UI', 21, 'bold')).pack(anchor='w')
        tk.Label(header, text='FULL REPEAT STUDIO  ·  花型还原 / 循环铺图 / 批量套版', bg='#132e40', fg='#a9d8de', font=('', 10)).pack(anchor='w', pady=(4, 0))
        body = ttk.Panedwindow(self.root, orient='horizontal'); body.pack(fill='both', expand=True, padx=14, pady=12)
        left = ttk.Frame(body); body.add(left, weight=0)
        canvas = tk.Canvas(left, width=352, bg='#edf3f6', highlightthickness=0)
        scrollbar = ttk.Scrollbar(left, orient='vertical', command=canvas.yview); scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True); canvas.configure(yscrollcommand=scrollbar.set)
        controls = ttk.Frame(canvas); window = canvas.create_window((0, 0), window=controls, anchor='nw')
        controls.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))
        def wheel(event):
            widget = event.widget
            while widget:
                if widget == left:
                    canvas.yview_scroll(-1 if event.delta > 0 or getattr(event, 'num', 0) == 4 else 1, 'units'); return
                widget = getattr(widget, 'master', None)
        self.root.bind_all('<MouseWheel>', wheel, add='+'); self.root.bind_all('<Button-4>', wheel, add='+'); self.root.bind_all('<Button-5>', wheel, add='+')
        source = self.card(controls, '01  导入图片')
        ttk.Label(source, text='本地花型直接铺图；模特效果图先勾选 API 还原。', wraplength=295, style='Card.TLabel').pack(anchor='w')
        row = ttk.Frame(source, style='Card.TFrame'); row.pack(fill='x', pady=(10, 0))
        ttk.Button(row, text='选择图片', command=self.add_files).pack(side='left')
        ttk.Button(row, text='导入文件夹', command=self.add_folder).pack(side='left', padx=5)
        ttk.Button(source, text='清空列表', command=self.clear_files).pack(fill='x', pady=(6, 0))
        params = self.card(controls, '02  满版循环参数')
        ttk.Label(params, text='首版模式：满版循环（碎花 / 几何 / 无缝图案）', style='Card.TLabel', wraplength=295).pack(anchor='w')
        for key, label in [('tile_cm', '循环单元宽度 / cm'), ('width_cm', '平面画布宽度 / cm'), ('height_cm', '平面画布高度 / cm'), ('dpi', '导出 DPI'), ('offset_x_cm', '水平偏移 / cm'), ('offset_y_cm', '垂直偏移 / cm')]:
            self.field(params, key, label)
        ttk.Checkbutton(params, text='套版保留底图明暗（建议浅色底图）', variable=self.shade).pack(anchor='w', pady=9)
        ttk.Button(params, text='预览选中图片', command=self.preview_selected).pack(fill='x')
        output = self.card(controls, '03  输出设置')
        self.field(output, 'output', '保存目录', True)
        ttk.Checkbutton(output, text='先通过 API 将效果图还原为相似花型', variable=self.use_api).pack(anchor='w', pady=10)
        self.field(output, 'max_calls', '本次新提交 API 请求上限（不自动重试）')
        ttk.Label(output, text='不会改动原图。平面画布不是含放码、缝份的生产裁片。', style='Card.TLabel', wraplength=295).pack(anchor='w', pady=9)
        right = ttk.Frame(body); body.add(right, weight=1)
        tabs = ttk.Notebook(right); tabs.pack(fill='both', expand=True)
        batch = ttk.Frame(tabs, padding=12); tabs.add(batch, text='批量任务')
        batch.columnconfigure(0, weight=1); batch.rowconfigure(1, weight=1); batch.rowconfigure(3, weight=2)
        ttk.Label(batch, textvariable=self.task_text, wraplength=720).grid(row=0, column=0, sticky='w', pady=(0, 8))
        listing = ttk.Frame(batch); listing.grid(row=1, column=0, sticky='nsew')
        self.tree = ttk.Treeview(listing, columns=('name',), show='tree headings', selectmode='browse', height=4)
        self.tree.heading('#0', text='缩略图'); self.tree.heading('name', text='输入图片'); self.tree.column('#0', width=88, stretch=False); self.tree.column('name', width=400)
        scroll = ttk.Scrollbar(listing, orient='vertical', command=self.tree.yview); self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='both', expand=True); scroll.pack(side='right', fill='y')
        self.tree.bind('<<TreeviewSelect>>', self.select_source)
        ttk.Label(batch, text='预览 · 双击打开大图；打开下一张会关闭上一张').grid(row=2, column=0, sticky='w', pady=8)
        self.preview = tk.Label(batch, bg='#dce6eb', text='导入图片后选择一张查看', fg='#4b6675', width=1, height=1); self.preview.grid(row=3, column=0, sticky='nsew')
        self.preview.bind('<Double-1>', lambda e: self.large_preview())
        templates_tab = ttk.Frame(tabs, padding=18); tabs.add(templates_tab, text='套版模板')
        ttk.Label(templates_tab, text='底图＋灰度蒙版', font=('', 15, 'bold')).pack(anchor='w')
        ttk.Label(templates_tab, text='蒙版必须与底图同尺寸：白色区域印花，黑色区域保留，灰色柔化边缘。\n不支持透明蒙版；使用无透明通道的灰度 PNG。支持同时套多个模板。', wraplength=680).pack(anchor='w', pady=10)
        self.template_list = tk.Listbox(templates_tab, height=9, relief='flat', bg='white', font=('', 11)); self.template_list.pack(fill='both', expand=True)
        row = ttk.Frame(templates_tab); row.pack(fill='x', pady=12)
        ttk.Button(row, text='创建套版模板', command=self.create_template).pack(side='left')
        ttk.Button(row, text='导入模板 JSON', command=self.import_template).pack(side='left', padx=6)
        ttk.Button(row, text='绘制服装蒙版', command=self.draw_mask).pack(side='left', padx=6)
        ttk.Button(row, text='移除选中', command=self.remove_template).pack(side='left')
        ttk.Label(templates_tab, text='示例模板是平铺T恤示意图，用于验证流程。真实模特套版请导入你自己的底图与服装蒙版。\n模板整张底图对应宽度用于计算花型比例；可反复调整，效果图比例仍需人工确认。', wraplength=680).pack(anchor='w')
        api_tab = ttk.Frame(tabs, padding=18); tabs.add(api_tab, text='API 花型还原')
        ttk.Label(api_tab, text='接入服务商的图像编辑接口', font=('', 15, 'bold')).pack(anchor='w')
        ttk.Label(api_tab, text='默认接入 OpenAI 图像编辑 API。模型 ID 以账户可用列表为准；ChatGPT 网页订阅与 API 分别计费。', wraplength=680).pack(anchor='w', pady=8)
        for key, label in [('protocol', '接口协议'), ('endpoint', '完整 HTTPS 接口地址'), ('model', 'OpenAI 图像模型 ID（以账户权限为准）'), ('size', 'API 输出尺寸'), ('key', 'API Key（仅内存，不保存）')]:
            ttk.Label(api_tab, text=label).pack(anchor='w', pady=(7, 2))
            if key == 'protocol': ttk.Combobox(api_tab, textvariable=self.vars[key], values=['OpenAI兼容图像编辑', 'DashScope同步多模态'], state='readonly').pack(fill='x')
            elif key == 'size': ttk.Combobox(api_tab, textvariable=self.vars[key], values=['1024x1024', '1536x1536', '2048x2048']).pack(fill='x')
            else: ttk.Entry(api_tab, textvariable=self.vars[key], show='*' if key == 'key' else '').pack(fill='x')
        ttk.Label(api_tab, text='花型还原提示词').pack(anchor='w', pady=(10, 3))
        self.prompt = tk.Text(api_tab, height=7, wrap='word', relief='flat', padx=8, pady=8); self.prompt.pack(fill='both', expand=True); self.prompt.insert('1.0', DEFAULT_PROMPT)
        row = ttk.Frame(api_tab); row.pack(fill='x', pady=8)
        ttk.Button(row, text='导入 API 配置', command=self.import_api).pack(side='left')
        ttk.Button(row, text='导出配置（不含密钥）', command=self.export_api).pack(side='left', padx=5)
        ttk.Button(row, text='允许重试未返回请求', command=self.allow_retry).pack(side='left')
        help_tab = ttk.Frame(tabs, padding=20); tabs.add(help_tab, text='使用说明')
        text = ('① 本地模式：导入已有花型，设置循环宽度、画布尺寸和DPI，点击预览或新建并开始。\n\n'
                '② AI模式：导入服装效果图，勾选API还原，在API页填写服务商文档中的完整接口地址、协议、模型及密钥。每张参考图请求一张候选稿。\n\n'
                '③ 套版：添加底图和同尺寸黑白蒙版。明暗保留适合白色/浅色衣服；需要准确褶皱变形的真实摄影模板，后续可增加位移图。首版是二维蒙版套版。\n\n'
                '④ 输出：花型单元、2×2平铺检查图、带DPI的满版画布、多模板效果图、任务参数和生成清单。\n\n'
                '⑤ 暂停后加载“印花任务.json”继续。已完成项校验后复用，不重新出图。网络超时不自动重发付费请求；先到平台核对费用和结果。\n\n'
                '⑥ AI输出为相似花型。不要直接将其当成原版复原或生产裁片；检查无缝接缝、颜色和真实花型尺寸。任务目录内的API响应可能含临时图片下载地址，请勿公开上传。')
        ttk.Label(help_tab, text=text, wraplength=680, justify='left').pack(anchor='w')
        bottom = ttk.Frame(right, padding=(0, 10, 0, 0)); bottom.pack(fill='x')
        self.progress = ttk.Progressbar(bottom, maximum=100); self.progress.pack(fill='x')
        ttk.Label(bottom, textvariable=self.status, wraplength=750).pack(anchor='w', pady=5)
        self.log = tk.Text(bottom, height=4, bg='#132e40', fg='#d5edf1', relief='flat', padx=9, pady=6, state='disabled', wrap='word'); self.log.pack(fill='x')
        row = ttk.Frame(bottom); row.pack(fill='x', pady=(8, 0))
        self.start_button = ttk.Button(row, text='新建并开始', style='Accent.TButton', command=self.start); self.start_button.pack(side='left')
        self.load_button = ttk.Button(row, text='加载任务', command=self.load_task); self.load_button.pack(side='left', padx=5)
        self.resume_button = ttk.Button(row, text='继续任务', command=self.resume); self.resume_button.pack(side='left')
        ttk.Button(row, text='暂停', command=self.pause).pack(side='left', padx=5)
        ttk.Button(row, text='输出目录', command=self.open_output).pack(side='right')

    def choose_output(self):
        if self.busy: return
        path = filedialog.askdirectory(title='选择输出目录')
        if path: self.vars['output'].set(path)

    def add_files(self):
        if self.busy: return
        paths = filedialog.askopenfilenames(title='选择印花或模特效果图', filetypes=[('图片', '*.png *.jpg *.jpeg *.webp *.tif *.tiff *.bmp')])
        self.set_files(list(dict.fromkeys(self.files + [Path(p) for p in paths])))

    def add_folder(self):
        if self.busy: return
        path = filedialog.askdirectory(title='选择输入文件夹；请勿把输出目录放在这里')
        if not path: return
        try:
            output = Path(self.vars['output'].get()).resolve()
            if output.is_relative_to(Path(path).resolve()): raise ValueError('输出目录不能位于输入文件夹内，避免重复扫描生成图')
            self.set_files(list(dict.fromkeys(self.files + scan(path))))
        except Exception as error: messagebox.showerror('导入失败', str(error))

    def clear_files(self):
        if not self.busy: self.set_files([])

    def set_files(self, files):
        if len(files) > 1000: raise ValueError('最多1000张图片')
        self.files = files; self.tree.delete(*self.tree.get_children()); self.thumbs = []
        for i, path in enumerate(files):
            image = None
            if i < 100:
                try:
                    image = load_image(path); image.thumbnail((54, 54)); image = ImageTk.PhotoImage(image); self.thumbs.append(image)
                except Exception: pass
            self.tree.insert('', 'end', iid=str(i), values=(path.name,), **({'image': image} if image else {}))
        self.status.set(f'已导入 {len(files)} 张图片；前100张显示列表缩略图，选中可查看所有图片')
        if files: self.tree.selection_set('0')

    def select_source(self, event=None):
        selected = self.tree.selection()
        if not selected: return
        try: self.show_image(self.files[int(selected[0])])
        except Exception as error: self.write(str(error))

    def show_image(self, path):
        self.preview_path = Path(path); image = load_image(path)
        image.thumbnail((max(350, self.preview.winfo_width() - 16), max(230, self.preview.winfo_height() - 16)))
        self.preview_image = ImageTk.PhotoImage(image); self.preview.configure(image=self.preview_image, text='')
        if self.preview_window and self.preview_window.winfo_exists(): self.preview_window.destroy(); self.preview_window = None

    def large_preview(self):
        if not getattr(self, 'preview_path', None): return
        if self.preview_window and self.preview_window.winfo_exists(): self.preview_window.destroy()
        self.preview_window = tk.Toplevel(self.root); self.preview_window.title(self.preview_path.name)
        image = load_image(self.preview_path); image.thumbnail((self.root.winfo_screenwidth() - 100, self.root.winfo_screenheight() - 150))
        self.large_image = ImageTk.PhotoImage(image); tk.Label(self.preview_window, image=self.large_image).pack()

    def options(self): return settings({**{k: v.get() for k, v in self.vars.items()}, 'shade': self.shade.get()})

    def api_config(self):
        return {'endpoint': self.vars['endpoint'].get().strip(), 'model': self.vars['model'].get().strip(),
                'protocol': 'dashscope' if self.vars['protocol'].get() == 'DashScope同步多模态' else 'openai_edit',
                'size': self.vars['size'].get().strip(), 'prompt': self.prompt.get('1.0', 'end').strip()}

    def preview_selected(self):
        if self.busy: return
        selected = self.tree.selection()
        if not selected: return messagebox.showinfo('预览', '请先导入并选中一张图片')
        if self.use_api.get(): return messagebox.showinfo('预览', '效果图须先运行API还原；完成后可在任务输出查看花型和套版预览')
        try:
            options = self.options(); image = load_image(self.files[int(selected[0])])
            if self.templates:
                image = mockup(image, template(self.templates[0]), options)
            else: image = proof(image)
            # Preview file is local, isolated from user sources and final outputs.
            import tempfile
            if not hasattr(self, 'preview_dir'): self.preview_dir = tempfile.TemporaryDirectory(prefix='feifan-preview-')
            path = Path(self.preview_dir.name) / 'preview.png'; image.save(path); self.show_image(path)
        except Exception as error: messagebox.showerror('预览失败', str(error))

    def refresh_templates(self):
        self.template_list.delete(0, 'end')
        for path in self.templates:
            try: self.template_list.insert('end', template(path)['name'])
            except Exception: self.template_list.insert('end', '模板不可用：' + str(path))

    def import_template(self):
        if self.busy: return
        path = filedialog.askopenfilename(title='选择套版模板JSON', filetypes=[('套版模板', '*.json')])
        if not path: return
        try:
            template(path)
            if Path(path) not in self.templates: self.templates.append(Path(path))
            self.refresh_templates()
        except Exception as error: messagebox.showerror('模板错误', str(error))

    def remove_template(self):
        if self.busy: return
        selected = self.template_list.curselection()
        if selected: self.templates.pop(selected[0]); self.refresh_templates()

    def create_template(self):
        if self.busy: return
        from tkinter.simpledialog import askstring, askfloat
        name = askstring('创建模板', '模板名称，例如：长袖衬衫正面')
        if not name: return
        base = filedialog.askopenfilename(title='选择服装底图')
        if not base: return
        mask = filedialog.askopenfilename(title='选择同尺寸灰度蒙版（无透明通道）：白色印花，黑色保留')
        if not mask: return
        width = askfloat('花型比例', '整张底图对应宽度/cm（用于估算花型比例）', initialvalue=60, minvalue=1, maxvalue=500)
        if width is None: return
        parent = filedialog.askdirectory(title='选择模板保存位置，将新建独立模板文件夹')
        if not parent: return
        try:
            import re
            folder = Path(parent) / ((re.sub(r'[^\w\-\u4e00-\u9fff]', '_', name)[:50] or '模板') + '_' + uuid.uuid4().hex[:6]); folder.mkdir()
            # Normalize without overwriting selected images.
            load_image(base).save(folder / 'base.png')
            with Image.open(mask) as source:
                from PIL import ImageOps
                if 'A' in source.getbands(): raise ValueError('蒙版不能含透明通道，请先保存为灰度PNG')
                ImageOps.exif_transpose(source).convert('L').save(folder / 'mask.png')
            atomic_json(folder / 'template.json', {'name': name, 'mode': 'full_repeat', 'base': 'base.png', 'mask': 'mask.png', 'canvas_width_cm': width})
            template(folder / 'template.json'); self.templates.append(folder / 'template.json'); self.refresh_templates()
            self.write('模板已保存：' + str(folder))
        except Exception as error: messagebox.showerror('创建失败', str(error))

    def draw_mask(self):
        if self.busy: return
        path = filedialog.askopenfilename(title='选择底图，手动涂抹需要印花的衣服区域')
        if not path: return
        try:
            base = load_image(path)
            display = base.copy(); display.thumbnail((900, 600))
            mask = Image.new('L', display.size, 0)
            window = tk.Toplevel(self.root); window.title('绘制服装蒙版 · 红色为印花区域')
            bar = ttk.Frame(window, padding=8); bar.pack(fill='x')
            size = tk.IntVar(value=30); erase = tk.BooleanVar(value=False)
            ttk.Label(bar, text='画笔').pack(side='left')
            ttk.Scale(bar, from_=2, to=120, variable=size, length=180).pack(side='left')
            ttk.Checkbutton(bar, text='橡皮擦', variable=erase).pack(side='left', padx=10)
            canvas = tk.Canvas(window, width=display.width, height=display.height, highlightthickness=0); canvas.pack()
            history = []; last = [None]; drawing = [False]
            def redraw():
                tinted = Image.blend(display, Image.new('RGB', display.size, '#f14368'), .5)
                view = Image.composite(tinted, display, mask)
                window.photo = ImageTk.PhotoImage(view)
                canvas.delete('all'); canvas.create_image(0, 0, anchor='nw', image=window.photo)
            def press(event):
                history.append(mask.copy())
                if len(history) > 20: history.pop(0)
                last[0] = (event.x, event.y); drawing[0] = True; paint(event)
            def paint(event):
                if not drawing[0]: return
                point = (event.x, event.y); width = max(2, int(size.get())); color = 0 if erase.get() else 255
                draw = ImageDraw.Draw(mask); draw.line([last[0], point], fill=color, width=width)
                radius = width / 2
                draw.ellipse((point[0]-radius, point[1]-radius, point[0]+radius, point[1]+radius), fill=color)
                last[0] = point; redraw()
            def undo():
                if history: mask.paste(history.pop()); redraw()
            def save():
                if not mask.getbbox(): return messagebox.showinfo('蒙版', '请先涂抹衣服区域', parent=window)
                target = filedialog.asksaveasfilename(parent=window, title='保存灰度蒙版；请勿覆盖底图', initialfile=Path(path).stem+'_mask.png', defaultextension='.png', filetypes=[('PNG', '*.png')])
                if not target: return
                if Path(target).resolve() == Path(path).resolve(): return messagebox.showerror('保存失败', '不能覆盖原始底图', parent=window)
                try:
                    mask.resize(base.size, Image.Resampling.LANCZOS).save(target, 'PNG')
                    self.write('蒙版已保存，可与底图一起创建模板：' + target); window.destroy()
                except Exception as error: messagebox.showerror('保存失败', str(error), parent=window)
            canvas.bind('<Button-1>', press); canvas.bind('<B1-Motion>', paint)
            canvas.bind('<ButtonRelease-1>', lambda e: drawing.__setitem__(0, False))
            ttk.Button(bar, text='撤销', command=undo).pack(side='left', padx=8)
            ttk.Button(bar, text='保存蒙版', command=save).pack(side='right')
            ttk.Label(window, text='左键涂抹衣服，避开皮肤、头发和纽扣；勾选橡皮擦修正。保存后点击“创建套版模板”。', padding=8).pack()
            redraw()
        except Exception as error: messagebox.showerror('蒙版编辑失败', str(error))

    def import_api(self):
        if self.busy: return
        path = filedialog.askopenfilename(filetypes=[('API配置', '*.json')])
        if not path: return
        try:
            config = json.loads(Path(path).read_text(encoding='utf-8'))
            if config.get('protocol') not in ('openai_edit', 'dashscope'): raise ValueError('未知API协议')
            for key in ('endpoint', 'model', 'size'):
                if key in config: self.vars[key].set(str(config[key]))
            self.vars['protocol'].set('DashScope同步多模态' if config['protocol'] == 'dashscope' else 'OpenAI兼容图像编辑')
            if 'prompt' in config: self.prompt.delete('1.0', 'end'); self.prompt.insert('1.0', config['prompt'])
            self.write('API配置已导入；密钥请单独填写')
        except Exception as error: messagebox.showerror('导入失败', str(error))

    def export_api(self):
        path = filedialog.asksaveasfilename(defaultextension='.json', initialfile='图像API配置.json', filetypes=[('JSON', '*.json')])
        if not path: return
        try: atomic_json(path, self.api_config()); self.write('已导出API配置，不含密钥')
        except Exception as error: messagebox.showerror('保存失败', str(error))

    def call_limit(self):
        value = number(self.vars['max_calls'].get(), 'API请求上限', 1, 1000)
        if value != int(value): raise ValueError('API请求上限必须是整数')
        return int(value)

    def confirm_api(self, config, limit):
        from print_studio.api import secure_url
        secure_url(config['endpoint'])
        if not self.vars['key'].get().strip(): raise ValueError('请填写本次API密钥；密钥不会保存')
        if not config['model'].strip(): raise ValueError('请填写图像模型ID')
        return messagebox.askyesno('确认 API 处理', f'将未完成的参考图上传到：\n{config["endpoint"]}\n模型：{config["model"]}\n本次最多新提交 {limit} 次，每次请求1张图片。费用以服务商为准。\n\n生成相似花型；可能计费，不会自动重发超时请求。继续？')

    def start(self):
        if self.busy: return
        try:
            if not self.files: raise ValueError('请先导入图片')
            if not self.vars['output'].get().strip(): raise ValueError('请选择输出目录')
            options = self.options(); config = self.api_config() if self.use_api.get() else None; limit = self.call_limit()
            if config and not self.confirm_api(config, limit): return
            files = list(self.files); templates = list(self.templates); output = self.vars['output'].get().strip()
            self.start_worker(lambda emit: Job.create(files, output, options, templates, config, emit, self.stop), limit)
        except Exception as error: messagebox.showerror('无法开始', str(error))

    def start_worker(self, factory, limit):
        key = self.vars['key'].get().strip(); self.stop.clear(); self.busy = True
        for button in (self.start_button, self.load_button, self.resume_button): button.configure(state='disabled')
        self.status.set('正在处理；API请求期间暂停会等待结果保存'); self.progress['value'] = 0
        def work():
            try:
                emit = lambda kind, value: self.events.put((kind, value))
                job = factory(emit); self.events.put(('task', str(job.path)))
                job.run(key, limit); self.events.put(('status', '生成完成 · 请审核平铺接缝与比例'))
            except InterruptedError as error: self.events.put(('status', str(error))); self.events.put(('log', str(error)))
            except Exception as error:
                message = str(error)
                self.events.put(('status', '任务中断 · 可加载任务继续')); self.events.put(('log', message))
            finally: self.events.put(('done', None))
        threading.Thread(target=work, daemon=True).start()

    def load_task(self):
        if self.busy: return
        path = filedialog.askopenfilename(title='选择印花任务.json', filetypes=[('印花任务', '*.json')])
        if not path: return
        try:
            job = Job(path); self.task_path = job.path; self.current_output = job.root; self.task_text.set('任务：' + str(job.path))
            for k, value in job.state['settings'].items():
                if k in self.vars: self.vars[k].set(str(value))
            self.shade.set(job.state['settings'].get('shade', True)); self.vars['output'].set(str(job.root.parent))
            self.set_files([job.local(item['source']) for item in job.state['items']])
            self.templates = [job.local(item['path']) for item in job.state['templates']]; self.refresh_templates()
            self.use_api.set(bool(job.state['api']))
            if job.state['api']:
                config = job.state['api']
                for key in ('endpoint', 'model', 'size'): self.vars[key].set(config.get(key, ''))
                self.vars['protocol'].set('DashScope同步多模态' if config['protocol'] == 'dashscope' else 'OpenAI兼容图像编辑')
                self.prompt.delete('1.0', 'end'); self.prompt.insert('1.0', config['prompt'])
            self.status.set('已加载原任务；继续时沿用保存的模板和参数')
        except Exception as error: messagebox.showerror('加载失败', str(error))

    def resume(self):
        if self.busy: return
        if not self.task_path: return self.load_task()
        try:
            job = Job(self.task_path); limit = self.call_limit()
            if job.state['api'] and any(i['status'] != 'complete' for i in job.state['items']):
                if not self.confirm_api(job.state['api'], limit): return
            path = self.task_path
            self.start_worker(lambda emit: Job(path, emit, self.stop), limit)
        except Exception as error: messagebox.showerror('无法继续', str(error))

    def allow_retry(self):
        if self.busy: return
        if not self.task_path: return messagebox.showinfo('重试', '请先加载需要继续的印花任务')
        if messagebox.askyesno('可能重复计费', '请先在服务商平台确认上次请求是否已生成和扣费。\n此操作允许重新提交未返回结果的请求，可能再次收费。是否确认？'):
            try: Job(self.task_path).permit_uncertain_retries(); self.write('已允许重试未返回请求；点击继续任务开始')
            except Exception as error: messagebox.showerror('操作失败', str(error))

    def pause(self):
        if self.busy: self.stop.set(); self.status.set('正在暂停，等待当前图片或API结果保存…')

    def write(self, message):
        self.log.configure(state='normal'); self.log.insert('end', message + '\n'); self.log.see('end'); self.log.configure(state='disabled')

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'log': self.write(value)
                elif kind == 'status': self.status.set(value)
                elif kind == 'progress': self.progress['value'] = value
                elif kind == 'image':
                    try: self.show_image(value)
                    except Exception as error: self.write(str(error))
                elif kind == 'task': self.task_path = Path(value); self.current_output = self.task_path.parent; self.task_text.set('任务：' + value)
                elif kind == 'done':
                    self.busy = False
                    for button in (self.start_button, self.load_button, self.resume_button): button.configure(state='normal')
        except queue.Empty: pass
        self.root.after(100, self.poll)

    def open_output(self):
        path = self.current_output
        if not path or not path.is_dir(): return messagebox.showinfo('输出目录', '尚未创建任务')
        try:
            if sys.platform == 'win32': os.startfile(path)
            else: subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)])
        except Exception as error: messagebox.showerror('打开失败', str(error))

    def close(self):
        if self.busy:
            self.stop.set(); messagebox.showinfo('正在暂停', '请等待当前图片或API结果保存后，再关闭窗口，避免重复计费。'); return
        self.root.destroy()
