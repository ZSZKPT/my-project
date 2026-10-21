"""Three-column desktop workspace for garment/model/print separation."""
from dataclasses import asdict
from pathlib import Path
import json
import queue
import shutil
import sys
import threading
import tkinter as tk
import uuid
from tkinter import ttk,filedialog,messagebox,simpledialog
from PIL import Image,ImageTk
from print_studio.core import atomic_json,load_image,save_png
from print_studio.mask_editor import MaskEditor
from .models import catalog,MockupTemplate,PrintRegion,identifier,local
from .library import TemplateLibrary,validate,approve
from .batch import Queue,plan,records_from_folder,records_from_table
from .render import render

ASSETS=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))/'assets'


class FashionApp:
    def __init__(self,root,home=None):
        self.root=root;root.title('飞凡印花设计 · Fashion Mockup Automation Studio 0.4')
        root.geometry(f'{min(1320,max(1080,root.winfo_screenwidth()-40))}x{min(900,max(740,root.winfo_screenheight()-60))}');root.minsize(1080,700)
        self.home=Path(home or Path.home()/'Documents'/'飞凡多版型样机');self.home.mkdir(parents=True,exist_ok=True)
        self.catalog_path=self.home/'garments.json'
        if not self.catalog_path.exists():shutil.copyfile(ASSETS/'fashion/garments.json',self.catalog_path)
        self.types=catalog(self.catalog_path);self.library=TemplateLibrary(self.home/'templates')
        self.records=[];self.overrides={};self.current=None;self.task=None;self.busy=False
        self.events=queue.Queue();self.preview_window=None;self.mask_editor=None
        self.status=tk.StringVar(value='先为每张模特/视角创建模板并核对各分区；Photoshop未验证的项目会明确标注。')
        self.query=tk.StringVar();self.type_filter=tk.StringVar(value='全部')
        self.output=tk.StringVar(value=str(self.home/'output'));self.mode=tk.StringVar(value='D')
        self.naming=tk.StringVar(value='{view}');self.backend=tk.StringVar(value='local')
        self.endpoint=tk.StringVar(value='https://api.openai.com/v1/chat/completions')
        self.model=tk.StringVar();self.key=tk.StringVar();self.ai_result=None
        self.setup();self.build();self.refresh();root.after(100,self.poll)
        root.protocol('WM_DELETE_WINDOW',self.close)

    def setup(self):
        from tkinter import font
        families=set(font.families(self.root))
        self.font_family=next((name for name in ['Microsoft YaHei UI','Microsoft YaHei','Noto Sans CJK SC','Noto Serif CJK SC'] if name in families),'TkDefaultFont')
        for name in ['TkDefaultFont','TkTextFont','TkMenuFont','TkHeadingFont']:
            font.nametofont(name).configure(family=self.font_family,size=10)
        style=ttk.Style(self.root);style.theme_use('clam')
        style.configure('.',font=(self.font_family,10),background='#edf3f6',foreground='#203b4a')
        style.configure('TButton',padding=(10,7));style.configure('Treeview',rowheight=32)
        style.configure('Accent.TButton',background='#087e8b',foreground='white')
        self.root.configure(bg='#edf3f6')

    def build(self):
        header=tk.Frame(self.root,bg='#122f40',padx=18,pady=12);header.pack(fill='x')
        tk.Label(header,text='飞凡印花设计',font=(self.font_family,20,'bold'),bg='#122f40',fg='white').pack(side='left')
        tk.Label(header,text='  多版型 · 多模特 · 独立分区 · 批量商品图',bg='#122f40',fg='#a9d8de').pack(side='left')
        ttk.Button(header,text='原套版 / 裁片工作台',command=self.legacy).pack(side='right')
        ttk.Label(self.root,textvariable=self.status,padding=10,wraplength=1250).pack(side='bottom',fill='x')
        body=ttk.Frame(self.root);body.pack(fill='both',expand=True,padx=10,pady=8)
        nav=ttk.Frame(body,width=150);nav.pack(side='left',fill='y',padx=(0,8))
        self.tabs=ttk.Notebook(body);self.tabs.pack(side='left',fill='both',expand=True)
        self.pages={}
        for label in ['服装版型库','模特模板库','印花素材库','智能对象管理','批量任务管理']:
            page=ttk.Frame(self.tabs,padding=12);self.tabs.add(page,text=label);self.pages[label]=page
            ttk.Button(nav,text=label,command=lambda p=page:self.tabs.select(p)).pack(fill='x',pady=4)
        ttk.Label(nav,text='本地工作目录',wraplength=150).pack(anchor='w',pady=(20,2))
        ttk.Label(nav,text=str(self.home),wraplength=150).pack(anchor='w')
        self.build_types();self.build_templates();self.build_prints();self.build_ps();self.build_batch()

    def safe(self,fn):
        if self.busy:return messagebox.showinfo('任务运行中','请暂停并等待当前图片保存后再编辑',parent=self.root)
        try:return fn()
        except Exception as e:messagebox.showerror('操作失败',str(e),parent=self.root)

    def build_types(self):
        page=self.pages['服装版型库']
        ttk.Label(page,text='配置驱动的服装版型',font=(self.font_family,17,'bold')).pack(anchor='w')
        ttk.Label(page,text='分类预设不是已制作的模特样机。每张照片都需要独立蒙版；新增版型可导入配置，无需修改渲染引擎。',wraplength=900).pack(anchor='w',pady=8)
        self.type_tree=ttk.Treeview(page,columns=('category','name','parts'),show='headings')
        for k,t,w in [('category','类别',100),('name','版型',180),('parts','建议部件 / 智能对象',570)]:self.type_tree.heading(k,text=t);self.type_tree.column(k,width=w)
        self.type_tree.pack(fill='both',expand=True)
        ttk.Button(page,text='导入版型配置 JSON',command=lambda:self.safe(self.import_catalog)).pack(anchor='w',pady=10)

    def import_catalog(self):
        p=filedialog.askopenfilename(filetypes=[('版型配置','*.json')])
        if not p:return
        new=catalog(p);merged=dict(self.types);merged.update(new)
        atomic_json(self.catalog_path,{'schema_version':1,'types':[asdict(g) for g in merged.values()]})
        self.types=merged;self.refresh()

    def build_templates(self):
        page=self.pages['模特模板库'];bar=ttk.Frame(page);bar.pack(fill='x')
        ttk.Entry(bar,textvariable=self.query).pack(side='left',fill='x',expand=True)
        self.filter_box=ttk.Combobox(bar,textvariable=self.type_filter,width=22,state='readonly');self.filter_box.pack(side='left',padx=6)
        self.filter_box.bind('<<ComboboxSelected>>',lambda e:self.refresh_templates())
        ttk.Button(bar,text='搜索',command=self.refresh_templates).pack(side='left')
        row=ttk.Frame(page);row.pack(fill='x',pady=8)
        for label,fn in [('新建',self.new_template),('编辑资料',self.edit_metadata),('复制',self.duplicate),('删除',self.delete),('导入ZIP',self.import_template),('导出ZIP',self.export_template),('核对批准',self.approve)]:
            ttk.Button(row,text=label,command=lambda f=fn:self.safe(f)).pack(side='left',padx=2)
        split=ttk.Panedwindow(page,orient='horizontal');split.pack(fill='both',expand=True)
        center=ttk.Frame(split);split.add(center,weight=3)
        self.template_tree=ttk.Treeview(center,columns=('name','model','view','type','review'),show='headings',selectmode='extended',height=5)
        for k,t in [('name','模板'),('model','模特'),('view','视角'),('type','版型'),('review','审核')]:self.template_tree.heading(k,text=t);self.template_tree.column(k,width=110)
        self.template_tree.pack(fill='x');self.template_tree.bind('<<TreeviewSelect>>',self.select_template)
        self.preview=ttk.Label(center,text='选择模特模板预览',anchor='center');self.preview.pack(fill='both',expand=True,pady=8)
        self.preview.bind('<Double-1>',lambda e:self.large_preview())
        right=ttk.Frame(split,width=290);split.add(right,weight=1)
        ttk.Label(right,text='可印花部件 / 独立印花',font=(self.font_family,12,'bold')).pack(anchor='w')
        self.region_list=tk.Listbox(right,exportselection=False,height=9);self.region_list.pack(fill='x',pady=6)
        for label,fn in [('绘制选中分区蒙版',self.edit_region),('导入选中分区蒙版',self.import_mask),('编辑前景遮挡蒙版',self.edit_occlusion),('修改分区 / 平铺 / 透视',self.edit_regions),('给选中部件指定印花',self.assign_region),('所有部件跟随货号印花',self.clear_assignments),('本地套印花预览',self.preview_render)]:
            ttk.Button(right,text=label,command=lambda f=fn:self.safe(f)).pack(fill='x',pady=3)
        ttk.Label(right,text='蒙版：白色印花。遮挡蒙版：白色保护头发/皮肤/饰品。AI建议需人工检查。',wraplength=260).pack(anchor='w',pady=6)

    def selected(self):
        if not self.current:raise ValueError('请选择模特模板')
        return self.current,validate(self.current)

    def selected_region(self):
        p,s=self.selected();indexes=self.region_list.curselection()
        if not indexes:raise ValueError('请选择右侧部件')
        return p,s,s.regions[indexes[0]]

    def refresh(self):
        self.type_tree.delete(*self.type_tree.get_children())
        for g in self.types.values():self.type_tree.insert('', 'end',iid=g.id,values=(g.category,g.name,' / '.join(p['smart_object'] for p in g.parts)))
        self.filter_box['values']=['全部']+list(self.types)
        self.refresh_templates()

    def refresh_templates(self):
        self.template_tree.delete(*self.template_tree.get_children());self.paths={}
        for p,s in self.library.list(self.query.get(),'' if self.type_filter.get()=='全部' else self.type_filter.get()):
            try:validate(p,True);status='已核对'
            except ValueError:status='待核对'
            self.paths[s.id]=p
            self.template_tree.insert('', 'end',iid=s.id,values=(s.name,s.model_id,s.view,s.garment_type,status))

    def select_template(self,event=None):
        ids=self.template_tree.selection()
        if not ids:return
        self.current=self.paths[ids[0]];s=validate(self.current)
        self.region_list.delete(0,'end')
        mappings={m['region_id']:m['name'] for m in s.smart_objects}
        for r in s.regions:self.region_list.insert('end',r['name']+' · '+mappings[r['id']])
        self.show_image(local(self.current.parent,s.base))
        self.ps_status.set('智能对象结构：'+', '.join(m['name'] for m in s.smart_objects)+'\nPhotoshop：未在本机验证（运行并导入报告后显示结果）')

    def show_image(self,path_or_image):
        image=path_or_image.copy() if isinstance(path_or_image,Image.Image) else load_image(path_or_image)
        self.current_preview=image.copy();image.thumbnail((650,300));self.photo=ImageTk.PhotoImage(image);self.preview.configure(image=self.photo,text='')
        if self.preview_window and self.preview_window.winfo_exists():self.preview_window.destroy();self.preview_window=None

    def large_preview(self):
        if not hasattr(self,'current_preview'):return
        if self.preview_window and self.preview_window.winfo_exists():self.preview_window.destroy()
        self.preview_window=tk.Toplevel(self.root);self.preview_window.title('样机预览')
        image=self.current_preview.copy();image.thumbnail((1000,780));self.large_photo=ImageTk.PhotoImage(image)
        ttk.Label(self.preview_window,image=self.large_photo).pack()

    def new_template(self,photo=None):
        photo=photo or filedialog.askopenfilename(title='每张模特/视角使用自己的原图',filetypes=[('图片','*.png *.jpg *.jpeg *.webp')])
        if not photo:return
        win=tk.Toplevel(self.root);win.title('新建模特模板');win.geometry('450x350')
        values={k:tk.StringVar(value=v) for k,v in {'name':Path(photo).stem,'type':next(iter(self.types)),'model':'model_01','view':'main'}.items()}
        from .vision import image_digest
        matched=self.ai_result and self.ai_result.get('source_sha256')==image_digest(photo)
        if matched:values['type'].set(self.ai_result['garment_type'])
        for k,label in [('name','模板名称'),('type','版型ID'),('model','模特ID'),('view','视角/输出名')]:
            ttk.Label(win,text=label).pack(anchor='w',padx=15)
            if k=='type':ttk.Combobox(win,textvariable=values[k],values=list(self.types),state='readonly').pack(fill='x',padx=15)
            else:ttk.Entry(win,textvariable=values[k]).pack(fill='x',padx=15)
        def create():
            def action():
                self.current=self.library.create(photo,self.types[values['type'].get()],values['name'].get(),values['model'].get(),values['view'].get())
                if matched and values['type'].get()==self.ai_result['garment_type']:
                    from .vision import apply_suggestion
                    apply_suggestion(self.current,self.ai_result)
                self.refresh_templates();self.template_tree.selection_set(MockupTemplate.read(self.current).id);self.select_template();win.destroy()
                self.status.set('模板已创建；蒙版为AI多边形草稿或空白草稿。逐部件精修后核对批准。')
            self.safe(action)
        ttk.Button(win,text='创建独立模板',command=create).pack(pady=15)

    def json_editor(self,title,value,callback):
        win=tk.Toplevel(self.root);win.title(title);win.geometry('760x620')
        text=tk.Text(win,wrap='none',undo=True);text.pack(fill='both',expand=True);text.insert('1.0',json.dumps(value,ensure_ascii=False,indent=2))
        def save():
            def action():callback(json.loads(text.get('1.0','end')));win.destroy()
            self.safe(action)
        ttk.Button(win,text='校验并保存',command=save).pack(pady=8)

    def edit_metadata(self):
        p,s=self.selected()
        def save(d):
            if d['garment_type'] not in self.types:raise ValueError('请先导入版型配置')
            for k in ('name','model_id','view','garment_type','preset'):setattr(s,k,d[k])
            self.library.save(p,s);self.refresh_templates()
        self.json_editor('模板资料 / 输出尺寸与裁剪',{k:getattr(s,k) for k in ('name','model_id','view','garment_type','preset')},save)

    def duplicate(self):
        p,_=self.selected();self.library.duplicate(p);self.refresh_templates()

    def delete(self):
        p,s=self.selected()
        if messagebox.askyesno('移到模板回收目录','移除 '+s.name+'？原始外部文件保留。'):
            self.library.delete(p);self.current=None;self.refresh_templates()

    def import_template(self):
        p=filedialog.askopenfilename(filetypes=[('模板包','*.zip')])
        if p:self.library.import_zip(p);self.refresh_templates()

    def export_template(self):
        p,s=self.selected();target=filedialog.asksaveasfilename(initialfile=s.name+'.zip',defaultextension='.zip')
        if target:self.library.export(p,target)

    def approve(self):
        p,_=self.selected()
        if messagebox.askyesno('确认已检查蒙版','是否已逐部件检查边缘、头发/皮肤遮挡、旧图案、光影与分区顺序？'):
            approve(p);self.refresh_templates();self.status.set('模板已核对。任何底图、蒙版或参数修改后都需要重新核对。')

    def editor(self,p,s,mask,occlusion=False):
        if self.mask_editor and self.mask_editor.window.winfo_exists():self.mask_editor.close()
        self.mask_editor=MaskEditor(self.root,local(p.parent,s.base),local(p.parent,mask),on_save=lambda:self.refresh_templates(),allow_empty=occlusion,
                                    caption='涂出需要保护的头发、皮肤、饰品等前景。没有遮挡时允许保存空蒙版。' if occlusion else None)

    def edit_region(self):
        p,s,r=self.selected_region();self.editor(p,s,r['mask'])

    def import_mask(self):
        p,s,r=self.selected_region();source=filedialog.askopenfilename(filetypes=[('灰度蒙版','*.png')])
        if not source:return
        with Image.open(source) as image:
            if image.size!=load_image(local(p.parent,s.base)).size:raise ValueError('蒙版尺寸必须与模特底图完全一致')
            save_png(image.convert('L'),local(p.parent,r['mask']))
        self.refresh_templates()

    def edit_occlusion(self):
        p,s=self.selected();self.editor(p,s,s.occlusion['mask'],occlusion=True)

    def edit_regions(self):
        p,s=self.selected()
        def save(d):
            # Missing masks for newly added regions start black; never borrow another photo's mask.
            for r in d['regions']:
                identifier(r['id']);m=local(p.parent,r['mask'])
                if not m.exists():save_png(Image.new('L',load_image(local(p.parent,s.base)).size),m)
            s.regions=d['regions'];s.smart_objects=d['smart_objects']
            # Validate manifest before replacing current version.
            tmp=p.parent/'validate.json';atomic_json(tmp,s.to_dict())
            try:validate(tmp)
            finally:tmp.unlink(missing_ok=True)
            self.library.save(p,s);self.refresh_templates();self.template_tree.selection_set(s.id);self.select_template()
        self.json_editor('动态分区 / 智能对象名称 / 平铺参数（quad为归一化四点）',{'regions':s.regions,'smart_objects':s.smart_objects},save)

    def assign_region(self):
        _,s,r=self.selected_region();source=filedialog.askopenfilename(title='为此部件指定独立花型（取消则不修改）',filetypes=[('印花','*.png *.jpg *.jpeg *.webp')])
        if source:self.overrides.setdefault(s.id,{})[r['id']]={'source':source,'params':{}};self.status.set(r['name']+' 已指定独立印花：'+Path(source).name)

    def clear_assignments(self):
        _,s=self.selected();self.overrides.pop(s.id,None);self.status.set('当前模板所有分区跟随每个货号的印花来源。')

    def preview_render(self):
        p,s=self.selected()
        source=self.records[0]['print'] if self.records else filedialog.askopenfilename(title='选择预览印花')
        if not source:return
        assignments={r['id']:{'source_id':'shared','params':{}} for r in s.regions};sources={'shared':source}
        for rid,a in self.overrides.get(s.id,{}).items():sources[rid]=a['source'];assignments[rid]={'source_id':rid,'params':a.get('params',{})}
        self.show_image(render(p,sources,assignments));self.tabs.select(self.pages['模特模板库'])

    def build_prints(self):
        page=self.pages['印花素材库'];row=ttk.Frame(page);row.pack(fill='x')
        for label,fn in [('导入印花图片',self.add_prints),('导入货号文件夹',self.add_folder),('导入Excel / CSV',self.add_table),('清空',self.clear_prints),('保存素材清单',self.save_prints),('加载素材清单',self.load_prints)]:
            ttk.Button(row,text=label,command=lambda f=fn:self.safe(f)).pack(side='left',padx=3)
        ttk.Label(page,text='一行一个货号/印花。表头：货号、印花路径、模板ID（可选；多个用分号）。相同货号的多个印花请用命名规则区分。',wraplength=900).pack(anchor='w',pady=12)
        self.print_tree=ttk.Treeview(page,columns=('sku','print','templates'),show='headings')
        for k,t,w in [('sku','货号',150),('print','印花路径',540),('templates','模板ID筛选',240)]:self.print_tree.heading(k,text=t);self.print_tree.column(k,width=w)
        self.print_tree.pack(fill='both',expand=True)

    def refresh_prints(self):
        self.print_tree.delete(*self.print_tree.get_children())
        for r in self.records:self.print_tree.insert('', 'end',values=(r['sku'],r['print'],r.get('templates','')))
        self.status.set(f'已载入 {len(self.records)} 个货号印花。')

    def add_prints(self):
        files=filedialog.askopenfilenames(filetypes=[('印花','*.png *.jpg *.jpeg *.webp')])
        self.records.extend({'sku':Path(p).stem,'print':p} for p in files);self.refresh_prints()

    def add_folder(self):
        p=filedialog.askdirectory(title='选择包含“货号/print.png”的根目录')
        if p:self.records.extend(records_from_folder(p));self.refresh_prints()

    def add_table(self):
        p=filedialog.askopenfilename(filetypes=[('货号表','*.csv *.xlsx')])
        if p:self.records.extend(records_from_table(p));self.refresh_prints()

    def clear_prints(self):self.records=[];self.refresh_prints()

    def save_prints(self):atomic_json(self.home/'materials.json',{'records':self.records})

    def load_prints(self):
        self.records=json.loads((self.home/'materials.json').read_text(encoding='utf-8'))['records'];self.refresh_prints()

    def build_ps(self):
        page=self.pages['智能对象管理']
        ttk.Label(page,text='Photoshop原生智能对象 / AI分区建议',font=(self.font_family,16,'bold')).pack(anchor='w')
        self.ps_status=tk.StringVar(value='先选择模特模板。未安装Photoshop时，原生智能对象保持未验证。')
        ttk.Label(page,textvariable=self.ps_status,wraplength=900).pack(anchor='w',pady=10)
        row=ttk.Frame(page);row.pack(fill='x')
        ttk.Button(row,text='准备原生PSD创建/验证脚本',command=lambda:self.safe(self.prepare_ps)).pack(side='left')
        ttk.Button(row,text='导入Photoshop验证报告',command=lambda:self.safe(self.import_ps_report)).pack(side='left',padx=8)
        ttk.Label(page,text='本地PNG/JPG可直接生成。JSX须在真实Photoshop运行后才产生PSD与验证报告。每个分区成为独立原生智能对象；透视/平铺当前烘焙在其内容中，修改参数后重新准备，不是原生可回退变形网格。',wraplength=900).pack(anchor='w',pady=12)
        for title,var in [('视觉API完整HTTPS地址（OpenAI兼容chat/completions）',self.endpoint),('支持图片输入的模型ID（按账户实际权限填写）',self.model),('API Key（仅内存，不保存）',self.key)]:
            ttk.Label(page,text=title).pack(anchor='w',pady=(6,2))
            if var==self.model:
                self.model_box=ttk.Combobox(page,textvariable=var);self.model_box.pack(fill='x')
            else:ttk.Entry(page,textvariable=var,show='*' if var==self.key else '').pack(fill='x')
        row=ttk.Frame(page);row.pack(fill='x',pady=10)
        ttk.Button(row,text='读取模型列表',command=lambda:self.safe(self.query_models)).pack(side='left',padx=3)
        ttk.Button(row,text='导入照片并AI识别',command=lambda:self.safe(self.analyze_photo)).pack(side='left',padx=3)
        ttk.Button(row,text='AI分析当前模特照片',command=lambda:self.safe(self.analyze)).pack(side='left')
        ttk.Button(row,text='应用AI多边形草稿',command=lambda:self.safe(self.apply_ai)).pack(side='left',padx=6)
        ttk.Button(row,text='按AI建议新建模板',command=lambda:self.safe(lambda:self.new_template(getattr(self,'ai_photo',None)))).pack(side='left')
        self.ai_text=tk.Text(page,height=9,wrap='word');self.ai_text.pack(fill='both',expand=True)
        ttk.Label(page,text='AI为粗略分类/多边形建议，不是像素级分割。必须手工精修蒙版和遮挡。密钥不写入模板/任务。超时不自动重发付费请求。',wraplength=900).pack(anchor='w',pady=8)

    def prepare_ps(self):
        p,s=self.selected()
        if not self.records:raise ValueError('先导入至少一张测试印花')
        output=filedialog.askdirectory(title='选择PS准备包父目录')
        if not output:return
        from .photoshop import prepare
        source=self.records[0]['print'];sources={'shared':source};assignments={r['id']:{'source_id':'shared','params':{}} for r in s.regions}
        for rid,a in self.overrides.get(s.id,{}).items():sources[rid]=a['source'];assignments[rid]={'source_id':rid,'params':a.get('params',{})}
        script=prepare(p,sources,assignments,Path(output)/('Photoshop_'+s.id+'_'+uuid.uuid4().hex[:6]))
        self.status.set('已准备，尚未生成PSD：'+str(script))

    def import_ps_report(self):
        p,s=self.selected();file=filedialog.askopenfilename(filetypes=[('PS验证报告','*.json')])
        if not file:return
        from .photoshop import verification
        from .library import fingerprint
        report=verification(file)
        if report['template_id']!=s.id or report['template_version']!=s.version:raise ValueError('验证报告不是当前模板版本')
        if report.get('template_fingerprint')!=fingerprint(p):raise ValueError('模板蒙版/参数已改变，报告已过期')
        expected={m['name'] for m in s.smart_objects}
        if expected!={r['name'] for r in report['regions']}:raise ValueError('报告智能对象结构不匹配')
        dest=p.parent/'native-mockup.psd';shutil.copyfile(report['psd'],dest)
        s.psd=dest.name;atomic_json(p,s.to_dict())
        atomic_json(p.parent/'photoshop-verification.json',report)
        self.ps_status.set('用户Photoshop '+report['photoshop_version']+' 验证通过；请另外目视检查褶皱、对花与蒙版。')

    def analyze(self):
        p,s=self.selected()
        self.analyze_source(local(p.parent,s.original))

    def analyze_photo(self):
        source=filedialog.askopenfilename(title='选择待分类的模特原图',filetypes=[('图片','*.png *.jpg *.jpeg *.webp')])
        if source:self.analyze_source(source)

    def query_models(self):
        from .vision import list_models
        endpoint,key=self.endpoint.get(),self.key.get();self.busy=True
        def work():
            try:self.events.put(('models',list_models(endpoint,key)))
            except Exception as e:self.events.put(('error',str(e)))
            finally:self.events.put(('idle',None))
        threading.Thread(target=work,daemon=True).start()

    def analyze_source(self,source):
        if not messagebox.askyesno('上传照片进行AI分析','将当前模特原图上传至所填API地址，可能计费。继续？'):return
        from .vision import suggest
        self.ai_photo=source;config=(self.endpoint.get(),self.model.get(),self.key.get());self.busy=True
        def work():
            try:self.events.put(('ai',suggest(source,self.types,*config)))
            except Exception as e:self.events.put(('error',str(e)))
            finally:self.events.put(('idle',None))
        threading.Thread(target=work,daemon=True).start();self.status.set('AI分析中，最多一次请求，不自动重发。')

    def apply_ai(self):
        p,s=self.selected()
        if not self.ai_result:raise ValueError('尚无AI建议')
        from .vision import apply_suggestion
        if messagebox.askyesno('替换当前蒙版为草稿','将覆盖当前部件/遮挡蒙版并撤销批准，是否继续？'):
            apply_suggestion(p,self.ai_result);self.refresh_templates();self.status.set('AI草稿已写入，请逐部件精修后批准。')

    def build_batch(self):
        page=self.pages['批量任务管理']
        ttk.Label(page,text='A 单模板多印花 · B 同版型多模特/视角 · C 多版型同印花 · D 自由组合',wraplength=920).pack(anchor='w')
        row=ttk.Frame(page);row.pack(fill='x',pady=8)
        for label,var,options in [('模式',self.mode,['A','B','C','D']),('后端',self.backend,['local','photoshop'])]:
            ttk.Label(row,text=label).pack(side='left');ttk.Combobox(row,textvariable=var,values=options,state='readonly',width=13).pack(side='left',padx=5)
        ttk.Label(row,text='命名').pack(side='left');ttk.Entry(row,textvariable=self.naming).pack(side='left',fill='x',expand=True)
        ttk.Label(page,text='在模特模板库按Ctrl/Shift多选。命名可用 {view}、{index}、{model}、{garment}、{sku}、{print}；冲突会阻止创建。',wraplength=900).pack(anchor='w')
        row=ttk.Frame(page);row.pack(fill='x',pady=8);ttk.Entry(row,textvariable=self.output).pack(side='left',fill='x',expand=True)
        ttk.Button(row,text='输出目录',command=self.choose_output).pack(side='left')
        row=ttk.Frame(page);row.pack(fill='x',pady=6)
        for label,fn in [('预计数量',self.estimate),('创建并开始',self.start),('加载断点',self.load_job),('继续',self.resume),('重试失败项',self.retry)]:
            ttk.Button(row,text=label,command=lambda f=fn:self.safe(f)).pack(side='left',padx=2)
        ttk.Button(row,text='暂停',command=self.pause).pack(side='left',padx=2)
        ttk.Button(row,text='取消',command=self.cancel).pack(side='left',padx=2)
        self.batch_tree=ttk.Treeview(page,columns=('sku','file','status','error'),show='headings')
        for k,t,w in [('sku','货号',120),('file','输出',330),('status','状态',90),('error','错误',320)]:self.batch_tree.heading(k,text=t);self.batch_tree.column(k,width=w)
        self.batch_tree.pack(fill='both',expand=True)
        self.progress=ttk.Progressbar(page,maximum=100);self.progress.pack(fill='x',pady=8)
        self.log=tk.Text(page,height=5,wrap='word',bg='#132e40',fg='#d5edf1');self.log.pack(fill='x')

    def selected_paths(self):return [self.paths[i] for i in self.template_tree.selection()]

    def estimate(self):
        items=plan(self.records,self.selected_paths(),self.mode.get(),self.naming.get(),self.overrides)
        self.status.set(f'预计生成 {len(items)} 张商品图片；按所选货号、印花、模板ID筛选及视角实际计算。')

    def choose_output(self):
        if self.busy:return
        p=filedialog.askdirectory()
        if p:self.output.set(p)

    def start(self):
        self.task=Queue.create(self.records,self.selected_paths(),self.output.get(),self.mode.get(),self.naming.get(),self.overrides,self.backend.get());self.run()

    def load_job(self):
        p=filedialog.askopenfilename(filetypes=[('多版型任务','batch.json')])
        if p:self.task=Queue(p);self.draw_queue();self.status.set('已加载断点，沿用模板/参数/印花快照：'+str(p))

    def run(self):
        if not self.task:raise ValueError('先创建或加载任务')
        self.busy=True;self.task.emit=lambda item:self.events.put(('item',item));self.draw_queue()
        def work():
            try:self.events.put(('done',self.task.run()))
            except Exception as e:self.events.put(('error',str(e)))
            finally:self.events.put(('idle',None))
        threading.Thread(target=work,daemon=True).start();self.status.set('任务运行中，原始文件不改动。')

    def resume(self):self.run()

    def retry(self):
        if not self.task:raise ValueError('先加载任务')
        self.task.retry_failed();self.run()

    def pause(self):
        if self.task:self.task.pause_event.set();self.status.set('正在暂停，等待当前图片/Photoshop操作保存。')

    def cancel(self):
        if self.task:self.task.cancel_event.set();self.status.set('当前项保存后取消剩余队列；完成的文件保留。')

    def draw_queue(self):
        self.batch_tree.delete(*self.batch_tree.get_children())
        if not self.task:return
        for it in self.task.state.items:self.batch_tree.insert('', 'end',iid=it['id'],values=(it['sku'],it['output'],it['status'],it['error']))
        done=sum(i['status']=='done' for i in self.task.state.items);self.progress['value']=100*done/max(1,len(self.task.state.items))

    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='idle':self.busy=False
                elif kind=='ai':
                    self.ai_result=value;self.ai_text.delete('1.0','end');self.ai_text.insert('end',json.dumps(value,ensure_ascii=False,indent=2));self.status.set('AI建议已返回，尚未应用或批准。')
                elif kind=='models':self.model_box['values']=value;self.status.set(f'读取到 {len(value)} 个模型；列表存在不表示支持视觉输入，请按服务商文档选择。')
                elif kind=='item':
                    self.draw_queue();self.log.insert('end',f"{value['sku']} {value['status']} {value['error']}\n");self.log.see('end')
                elif kind=='done':self.draw_queue();self.status.set('任务状态：'+value+' · '+str(self.task.path))
                elif kind=='error':self.status.set(value);self.log.insert('end',value+'\n')
        except queue.Empty:pass
        self.root.after(100,self.poll)

    def legacy(self):
        if self.busy:return
        from print_studio.app import App
        App(tk.Toplevel(self.root))

    def close(self):
        if self.busy:self.pause();messagebox.showinfo('保存中','等待当前工作保存完成后再关闭。');return
        self.key.set('');self.root.destroy()
