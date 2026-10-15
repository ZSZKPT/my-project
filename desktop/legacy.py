import csv
import json
import math
import queue
import sys
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.core import discover, prepare, upload_imgbb, load_profile
from import_tools.miaoshou import export
from desktop.profiles import load as load_template, storage_dir, products_to_rows
from desktop.template_editor import open_editor
from desktop.print_names import read_names, title_for


ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'assets'


class App:
    def __init__(self, window):
        self.window=window
        window.title('妙手批量上架助手 · 图片自动处理')
        window.geometry('1100x900')
        self.events=queue.Queue(); self.groups=[]; self.names=[]; self.busy=False
        self.variables={k:tk.StringVar(value=v) for k,v in {
            'source':'','output':'','profile':str(ASSETS/'运动短袖套装.json'),'template':str(ASSETS/'妙手Temu服饰模板.xlsx'),'price':'',
            'title':'女士圆领短袖2件套{print_name}印花圆领T恤+短裤',
            'mode':'ImgBB 自动上传','key':'','links':'','size':'1000'}.items()}
        self.active_profile=load_template(ASSETS/'运动短袖套装.json')
        self.profile_paths={'运动短袖套装（内置）':ASSETS/'运动短袖套装.json'}
        self.selected_profile=tk.StringVar(value='运动短袖套装（内置）')
        frame=ttk.Frame(window,padding=16);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='选择模板 → 导入图片及印花名 → 自动上传取链接 → 生成妙手表格',font=('',13,'bold')).pack(anchor='w')
        row=ttk.Frame(frame);row.pack(fill='x',pady=6)
        ttk.Label(row,text='产品模板',width=26).pack(side='left')
        self.profile_select=ttk.Combobox(row,textvariable=self.selected_profile,values=list(self.profile_paths),state='readonly');self.profile_select.pack(side='left',fill='x',expand=True)
        self.profile_select.bind('<<ComboboxSelected>>',self.select_template)
        ttk.Button(row,text='编辑 / 另存模板',command=self.edit_template).pack(side='left')
        ttk.Button(row,text='导入模板JSON',command=self.import_template).pack(side='left')
        self.refresh_templates()
        self.controls=[]
        for key,label,folder in [('source','图片目录',True),('output','输出目录',True),('template','创建商品导入模板',False)]:
            row=ttk.Frame(frame);row.pack(fill='x',pady=4)
            ttk.Label(row,text=label,width=26).pack(side='left')
            ttk.Entry(row,textvariable=self.variables[key]).pack(side='left',fill='x',expand=True)
            button=ttk.Button(row,text='选择',command=lambda k=key,f=folder:self.choose(k,f));button.pack(side='left');self.controls.append(button)
        for key,label in [('title','标题规则（含 {print_name}）'),('price','统一申报价CNY（建议售价自动5倍）')]:
            row=ttk.Frame(frame);row.pack(fill='x',pady=4);ttk.Label(row,text=label,width=26).pack(side='left');ttk.Entry(row,textvariable=self.variables[key]).pack(side='left',fill='x',expand=True)
        row=ttk.Frame(frame);row.pack(fill='x',pady=4)
        ttk.Label(row,text='素材图尺寸',width=26).pack(side='left');ttk.Combobox(row,textvariable=self.variables['size'],values=['800','1000','1200'],state='readonly',width=10).pack(side='left')
        ttk.Label(row,text='建议1000：导入模板要求大于800；居中裁切需核对构图').pack(side='left',padx=12)
        row=ttk.Frame(frame);row.pack(fill='x',pady=4)
        ttk.Label(row,text='图片上传方式',width=26).pack(side='left');ttk.Combobox(row,textvariable=self.variables['mode'],values=['先处理图片，手动补链接','ImgBB 自动上传'],state='readonly').pack(side='left')
        row=ttk.Frame(frame);row.pack(fill='x',pady=4);ttk.Label(row,text='ImgBB API Key（不保存）',width=26).pack(side='left');ttk.Entry(row,textvariable=self.variables['key'],show='*').pack(side='left',fill='x',expand=True)
        row=ttk.Frame(frame);row.pack(fill='x',pady=4);ttk.Label(row,text='已有图片链接 CSV（可选）',width=26).pack(side='left');ttk.Entry(row,textvariable=self.variables['links']).pack(side='left',fill='x',expand=True);ttk.Button(row,text='选择',command=lambda:self.choose('links',False)).pack(side='left')
        ttk.Label(frame,text='上传会将图片交给 ImgBB 并生成公开链接；密钥仅用于本次运行。手动模式不会上传。').pack(anchor='w',pady=4)
        self.scan_button=ttk.Button(frame,text='扫描货号 / 刷新名称表',command=self.scan);self.scan_button.pack(anchor='w')
        ttk.Button(frame,text='导入印花名称表格（按货号）',command=self.import_names).pack(anchor='w',pady=4)
        self.canvas=tk.Canvas(frame,height=150);self.canvas.pack(fill='both',expand=True,pady=6)
        self.table=ttk.Frame(self.canvas);self.canvas.create_window((0,0),window=self.table,anchor='nw')
        scrollbar=ttk.Scrollbar(frame,orient='vertical',command=self.canvas.yview);scrollbar.pack(side='right',fill='y');self.canvas.configure(yscrollcommand=scrollbar.set)
        self.table.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.run_button=ttk.Button(frame,text='自动处理 / 上传 / 生成妙手表格',command=self.start);self.run_button.pack(anchor='w',pady=6)
        self.log=tk.Text(frame,height=9,state='disabled');self.log.pack(fill='x')
        ttk.Label(frame,text='生成后到妙手批量手动导入、选择尺码表及属性并发布。原文件不覆盖。').pack(anchor='w')
        ttk.Button(frame,text='已有SKU CSV转换工具',command=self.csv_tool).pack(anchor='w',pady=4)
        window.after(100,self.poll)

    def refresh_templates(self):
        directory=storage_dir()
        if directory.exists():
            for path in sorted(directory.glob('*.json')):
                try:
                    profile=load_template(path)
                    self.profile_paths[profile['name']+' · '+path.stem[-8:]]=path
                except (ValueError, OSError):continue
        self.profile_select.configure(values=list(self.profile_paths))

    def select_template(self,event=None):
        if self.busy:return
        try:
            path=self.profile_paths[self.selected_profile.get()]
            self.active_profile=load_template(path)
            self.variables['profile'].set(str(path));self.variables['title'].set(self.active_profile['title'])
            self.write('已选择模板：'+self.active_profile['name'])
        except Exception as error:messagebox.showerror('模板加载失败',str(error))

    def edit_template(self):
        if self.busy:return
        config=json.loads(json.dumps(self.active_profile));config['title']=self.variables['title'].get()
        open_editor(self.window,config,storage_dir(),self.template_saved)

    def template_saved(self,path,profile):
        self.refresh_templates()
        key=profile['name']+' · '+path.stem[-8:]
        self.profile_paths[key]=path;self.profile_select.configure(values=list(self.profile_paths));self.selected_profile.set(key)
        self.select_template()

    def import_template(self):
        if self.busy:return
        try:
            path=filedialog.askopenfilename(filetypes=[('模板JSON','*.json')])
            if not path:return
            profile=load_template(path)
            from desktop.profiles import save
            saved=save(storage_dir(),profile);self.template_saved(saved,profile)
        except Exception as error:messagebox.showerror('模板导入失败',str(error))

    def csv_tool(self):
        from desktop.main import App as CsvApp
        CsvApp(tk.Toplevel(self.window))

    def choose(self,key,folder):
        if self.busy:return
        path=filedialog.askdirectory() if folder else filedialog.askopenfilename(filetypes=[('表格','*.xlsx *.csv')])
        if path:self.variables[key].set(path)

    def scan(self):
        if self.busy:return
        try:
            old={g['sku']:v.get() for g,v in zip(self.groups,self.names)}
            self.groups=discover(self.variables['source'].get());self.scanned_source=Path(self.variables['source'].get()).resolve();self.names=[]
            for child in self.table.winfo_children():child.destroy()
            for i,g in enumerate(self.groups):
                ttk.Label(self.table,text=f'{g["sku"]}  ({len(g["files"])}张)',width=45).grid(row=i,column=0,sticky='w')
                variable=tk.StringVar(value=old.get(g['sku'],''));self.names.append(variable)
                ttk.Entry(self.table,textvariable=variable,width=35).grid(row=i,column=1,pady=2)
            self.write('扫描完成，请逐行填写印花名称。')
        except Exception as error:messagebox.showerror('扫描失败',str(error))

    def import_names(self):
        if self.busy:return
        try:
            if not self.groups:raise ValueError('请先扫描货号')
            path=filedialog.askopenfilename(filetypes=[('印花表格','*.xlsx *.csv')])
            if not path:return
            mapping=read_names(path);matched=0
            for group,var in zip(self.groups,self.names):
                if group['sku'] in mapping:var.set(mapping[group['sku']]);matched+=1
            self.write(f'已匹配 {matched}/{len(self.groups)} 个货号，未匹配项保持原值。')
        except Exception as error:messagebox.showerror('导入失败',str(error))

    def write(self,text):
        self.log.configure(state='normal');self.log.insert('end',text+'\n');self.log.see('end');self.log.configure(state='disabled')

    def start(self):
        if self.busy:return
        try:
            values={k:v.get().strip() for k,v in self.variables.items()}
            if not self.groups or any(not v.get().strip() for v in self.names):raise ValueError('先扫描并填写所有印花名称')
            if Path(values['source']).resolve()!=self.scanned_source:raise ValueError('图片目录已变化，请重新扫描')
            price=float(values['price'])
            if not math.isfinite(price) or price<=0:raise ValueError('请填写正数申报价')
            if not values['output']:raise ValueError('请选择输出目录')
            if Path(values['output']).resolve().is_relative_to(self.scanned_source):raise ValueError('输出目录必须在图片输入目录之外，避免重复扫描生成图片')
            config=json.loads(json.dumps(self.active_profile));config['title']=values['title']
            if '{print_name}' not in config['title']:raise ValueError('标题规则必须包含 {print_name}')
            titles=[title_for(config['title'],v.get().strip(),g['sku']) for g,v in zip(self.groups,self.names)]
            if len(titles)!=len(set(titles)):raise ValueError('不同货号生成了相同标题，请使用不同印花名或增加 {sku}')
            config['price']=price
            from desktop.profiles import validate
            validate(config)
            if any(len(g['files'])>10 for g in self.groups):raise ValueError('单个货号超过10张，请先移除多余轮播图')
            if not Path(values['template']).is_file():raise ValueError('请选择官方创建商品导入模板')
            if values['mode']=='ImgBB 自动上传':
                if not values['key']:raise ValueError('请输入 ImgBB API Key')
                if not messagebox.askyesno('确认上传','将本次所有商品图和素材图上传到 ImgBB，生成公开链接。是否继续？'):return
            groups=[dict(g,print_name=v.get().strip()) for g,v in zip(self.groups,self.names)]
            self.busy=True;self.run_button.configure(state='disabled');self.scan_button.configure(state='disabled')
            threading.Thread(target=self.work,args=(values,config,groups),daemon=True).start()
        except Exception as error:messagebox.showerror('信息不完整',str(error))

    def work(self,values,config,groups):
        try:
            out=Path(values['output'])/('妙手_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir(parents=True,exist_ok=False)
            self.events.put(('log',f'输出目录：{out}'))
            link_rows={}
            if values['links']:
                with open(values['links'],encoding='utf-8-sig',newline='') as f:
                    for r in csv.DictReader(f):
                        if r.get('sku') in link_rows:raise ValueError('链接表有重复货号')
                        link_rows[r['sku']]=r
            products=[]
            link_file=out/'图片链接.csv'
            with open(link_file,'w',encoding='utf-8-sig',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=['sku','print_name','carousel_urls','material_url','preview_url']);writer.writeheader()
                for g in groups:
                    if len(g['files'])>10:raise ValueError(f'{g["sku"]} 超过10张，请先移除不需要的轮播图')
                    ready=prepare(g,out,int(values['size']));self.events.put(('log',f'{g["sku"]} 图片处理完成'))
                    row={'sku':g['sku'],'print_name':g['print_name'],'carousel_urls':'','material_url':'','preview_url':''}
                    if values['mode']=='ImgBB 自动上传':
                        urls=[]
                        for path in ready['carousel']:
                            urls.append(upload_imgbb(path,values['key']))
                            self.events.put(('log',f'{g["sku"]} 已上传 {len(urls)} 张'))
                        row.update(carousel_urls='|'.join(urls),material_url=upload_imgbb(ready['material'],values['key']),preview_url=urls[0])
                    elif g['sku'] in link_rows:
                        row.update({k:link_rows[g['sku']].get(k,'') for k in ['carousel_urls','material_url','preview_url']})
                    writer.writerow(row);f.flush();products.append(row)
            (out/'模板配置.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
            if all(p['carousel_urls'] and p['material_url'] for p in products):
                rows,titles=products_to_rows(config,products,config['price'])
                result=export(values['template'],rows,out/'妙手导入.xlsx',titles,config['origin'])
                self.events.put(('log',f'已生成妙手 Excel：{result["product_count"]}个商品，{result["sku_count"]}行SKU；建议售价=申报价5倍。'))
                for warning in result['warnings']:self.events.put(('log','提示：'+warning))
                self.events.put(('log','表格已生成，待手动导入。请在妙手批量选择尺码表、补充属性并确认发布。'))
            else:self.events.put(('log','尚缺在线链接：已生成图片和图片链接.csv。上传后填写链接表，下次选择该CSV再生成Excel。'))
        except Exception as error:self.events.put(('log',f'处理停止：{error}。已生成文件保留；已上传图片不会自动删除。'))
        finally:self.events.put(('done',None))

    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='log':self.write(value)
                else:self.busy=False;self.run_button.configure(state='normal');self.scan_button.configure(state='normal')
        except queue.Empty:pass
        self.window.after(100,self.poll)

if __name__=='__main__':
    window=tk.Tk();App(window);window.mainloop()
