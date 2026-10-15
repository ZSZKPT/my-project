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
from desktop.thumbnails import add_thumbnail


ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'assets'


class App:
    def __init__(self, window):
        self.window=window
        window.title('飞凡上架 · 图片自动处理')
        window.geometry('1100x900')
        self.events=queue.Queue(); self.groups=[]; self.names=[]; self.busy=False; self.thumbnails={}
        self.variables={k:tk.StringVar(value=v) for k,v in {
            'source':'','output':'','profile':str(ASSETS/'运动短袖套装.json'),'template':str(ASSETS/'妙手Temu服饰模板.xlsx'),'price':'',
            'title':'女士圆领短袖2件套{print_name}印花圆领T恤+短裤',
            'mode':'ImgBB 自动上传','key':'','links':'','size':'1000'}.items()}
        self.active_profile=load_template(ASSETS/'运动短袖套装.json')
        self.profile_paths={'运动短袖套装（内置）':ASSETS/'运动短袖套装.json'}
        self.selected_profile=tk.StringVar(value='运动短袖套装（内置）')
        from desktop.ui import build
        build(self)
        self.refresh_templates()
        self.current_output=None
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
            self.thumbnails={}
            self.table.columnconfigure(1,weight=1);self.table.columnconfigure(2,weight=1)
            for i,g in enumerate(self.groups):
                add_thumbnail(self,g,i)
                ttk.Label(self.table,text=f'{g["sku"]}\n{len(g["files"])} 张图片',style='Card.TLabel',width=20,wraplength=180).grid(row=i,column=1,sticky='w',padx=(0,8))
                variable=tk.StringVar(value=old.get(g['sku'],''));self.names.append(variable)
                ttk.Entry(self.table,textvariable=variable,width=20).grid(row=i,column=2,pady=8,padx=(0,8),sticky='ew')
            self.counts_text.set(f'{len(self.groups)} 个货号 · {sum(len(g["files"]) for g in self.groups)} 张图片')
            self.status_text.set('待填写印花名称')
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
            self.profile_select.configure(state='disabled')
            self.progress_value.set(0);self.status_text.set('正在处理');self.status_label.configure(bg='#244b53',fg='#d9eff0')
            threading.Thread(target=self.work,args=(values,config,groups),daemon=True).start()
        except Exception as error:messagebox.showerror('信息不完整',str(error))

    def work(self,values,config,groups):
        try:
            out=Path(values['output'])/('妙手_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir(parents=True,exist_ok=False)
            self.events.put(('log',f'输出目录：{out}'))
            self.events.put(('output',str(out)))
            total=sum(len(group['files'])+1 for group in groups);completed=0
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
                            completed+=1;self.events.put(('progress',completed/total*90))
                            self.events.put(('log',f'{g["sku"]} 已上传 {len(urls)} 张'))
                        row.update(carousel_urls='|'.join(urls),material_url=upload_imgbb(ready['material'],values['key']),preview_url=urls[0])
                        completed+=1;self.events.put(('progress',completed/total*90))
                    elif g['sku'] in link_rows:
                        row.update({k:link_rows[g['sku']].get(k,'') for k in ['carousel_urls','material_url','preview_url']})
                    writer.writerow(row);f.flush();products.append(row)
            (out/'模板配置.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
            if all(p['carousel_urls'] and p['material_url'] for p in products):
                rows,titles=products_to_rows(config,products,config['price'])
                self.events.put(('progress',95))
                result=export(values['template'],rows,out/'妙手导入.xlsx',titles,config['origin'])
                self.events.put(('progress',100));self.events.put(('status','表格已生成 · 待手动导入'))
                self.events.put(('log',f'已生成妙手 Excel：{result["product_count"]}个商品，{result["sku_count"]}行SKU；建议售价=申报价5倍。'))
                for warning in result['warnings']:self.events.put(('log','提示：'+warning))
                self.events.put(('log','表格已生成，待手动导入。请在妙手批量选择尺码表、补充属性并确认发布。'))
            else:
                self.events.put(('status','图片已处理 · 待补链接'))
                self.events.put(('log','尚缺在线链接：已生成图片和图片链接.csv。上传后填写链接表，下次选择该CSV再生成Excel。'))
        except Exception as error:
            self.events.put(('status','处理失败 · 请查看日志'))
            self.events.put(('log',f'处理停止：{error}。已生成文件保留；已上传图片不会自动删除。'))
        finally:self.events.put(('done',None))

    def open_output(self):
        if not self.current_output:return
        import os,subprocess
        try:
            if sys.platform=='win32':os.startfile(self.current_output)
            elif sys.platform=='darwin':subprocess.Popen(['open',self.current_output])
            else:subprocess.Popen(['xdg-open',self.current_output])
        except OSError as error:messagebox.showerror('无法打开目录',str(error))

    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='log':self.write(value)
                elif kind=='progress':self.progress_value.set(value)
                elif kind=='status':
                    self.status_text.set(value)
                    self.status_label.configure(bg='#863a39' if '失败' in value else '#176459',fg='white')
                elif kind=='output':self.current_output=value;self.open_button.configure(state='normal')
                elif kind=='done':
                    self.busy=False;self.run_button.configure(state='normal');self.scan_button.configure(state='normal');self.profile_select.configure(state='readonly')
        except queue.Empty:pass
        self.window.after(100,self.poll)

if __name__=='__main__':
    window=tk.Tk();App(window);window.mainloop()
