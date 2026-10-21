"""Reproducible technical fixtures and headless batch entrypoint."""
from dataclasses import asdict
from pathlib import Path
import argparse
import json
import tempfile
import sys
from PIL import Image,ImageDraw
from print_studio.core import atomic_json,save_png,sha256
from .models import catalog,local
from .library import TemplateLibrary,validate,approve
from .batch import Queue


def demo(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    config=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))/'assets/fashion/garments.json'
    # The fixtures are technical drawings, not evidence of real-photo AI segmentation.
    types=catalog(config);library=TemplateLibrary(root/'templates')
    base=Image.new('RGB',(300,420),'#dce6ee');draw=ImageDraw.Draw(base)
    draw.ellipse((125,12,175,62),fill='#b47d60');draw.rectangle((130,60,170,83),fill='#b47d60')
    photo=root/'technical-model.png';save_png(base,photo)
    templates=[]
    shapes={
        'set_tee_shorts':[[ (90,80),(210,80),(205,205),(95,205)],[(65,80),(90,80),(90,140),(65,140)],[(210,80),(235,80),(235,140),(210,140)],[(95,215),(148,215),(145,300),(85,300)],[(152,215),(205,215),(215,300),(155,300)]],
        'set_long_pants':[[ (90,80),(210,80),(205,205),(95,205)],[(65,80),(90,80),(90,208),(65,208)],[(210,80),(235,80),(235,208),(210,208)],[(95,215),(148,215),(145,405),(85,405)],[(152,215),(205,215),(215,405),(155,405)]],
        'dress_long':[[ (95,80),(205,80),(200,180),(100,180)],[(100,185),(200,185),(245,405),(55,405)],[(65,85),(90,85),(90,150),(65,150)]]}
    for index,(tid,polygons) in enumerate(shapes.items()):
        path=library.create(photo,types[tid],types[tid].name,'technical_model_'+str(index),'main')
        s=validate(path);background=base.copy()
        for region,polygon in zip(s.regions,polygons):
            mask=Image.new('L',base.size);ImageDraw.Draw(mask).polygon(polygon,fill=255)
            save_png(mask,local(path.parent,region['mask']))
            background.paste('white',mask=mask);region['params']['shade_strength']=0
        # An occluder crossing printable regions proves foreground protection.
        occ=Image.new('L',base.size);ImageDraw.Draw(occ).rectangle((140,90,160,110),fill=255)
        ImageDraw.Draw(background).rectangle((140,90,160,110),fill='#b47d60')
        save_png(background,local(path.parent,s.base));save_png(occ,local(path.parent,s.occlusion['mask']))
        atomic_json(path,s.to_dict());approve(path);templates.append(path)
    print_path=root/'geometric.png';tile=Image.new('RGB',(32,32),'#f1c146');ImageDraw.Draw(tile).ellipse((8,8,24,24),fill='#a64d75');save_png(tile,print_path)
    return templates,print_path


def demo_report(root):
    root=Path(root);paths,pattern=demo(root)
    records=[{'sku':'DEMO001','print':str(pattern.resolve())}]
    q=Queue.create(records,paths,root/'jobs',naming='{garment}_{view}')
    q.run();previews=[]
    for item in q.state.items:
        image=Image.open(q.root/item['output']);image.thumbnail((300,420));previews.append(image.copy())
    sheet=Image.new('RGB',(900,460),'white');d=ImageDraw.Draw(sheet)
    for i,image in enumerate(previews):sheet.paste(image,(i*300,32))
    d.text((10,10),'TECHNICAL FIXTURES ONLY - no real photo / Photoshop validation',fill='black')
    save_png(sheet,root/'technical-proof.png')
    report={'version':'0.4.0','local_batch':q.state.status,'fixtures':'synthetic technical drawings, not model photos',
            'cases':[{'garment_type':validate(p).garment_type,'regions':[r['id'] for r in validate(p).regions],
                      'smart_object_mapping':[m['name'] for m in validate(p).smart_objects],
                      'native_photoshop':'UNVERIFIED','real_photo_masks':'UNVERIFIED'} for p in paths],
            'ai_api_live':'UNVERIFIED (no credentials)','production_fold_and_perspective':'UNVERIFIED',
            'outputs':[{'file':str(q.root/i['output']),'sha256':i['sha256']} for i in q.state.items]}
    atomic_json(root/'acceptance-report.json',report)
    return report


def gui_smoke():
    import tkinter as tk
    from .studio import FashionApp
    with tempfile.TemporaryDirectory() as temp:
        root=tk.Tk();app=FashionApp(root,Path(temp)/'workspace');root.update()
        assert len(app.types)>=23
        paths,pattern=demo(Path(temp)/'fixture')
        archive=Path(temp)/'template.zip';TemplateLibrary(paths[0].parent.parent).export(paths[0],archive)
        imported=app.library.import_zip(archive);approve(imported);app.refresh()
        s=validate(imported);app.template_tree.selection_set(s.id);app.select_template();root.update()
        assert app.region_list.size()==5
        app.records=[{'sku':'GUI01','print':str(pattern)}];app.refresh_prints();app.estimate()
        app.preview_render();root.update();app.large_preview();root.update()
        assert app.preview_window.winfo_exists()
        app.region_list.selection_set(0);app.edit_region();root.update();app.mask_editor.close()
        app.task=Queue.create(app.records,[imported],Path(temp)/'jobs');assert app.task.run()=='done'
        app.draw_queue();root.update();assert len(app.batch_tree.get_children())==1
        root.destroy()


def main():
    p=argparse.ArgumentParser(description='多版型本地批量/验证（不生成虚假PSD）')
    sub=p.add_subparsers(dest='command',required=True)
    d=sub.add_parser('demo');d.add_argument('output')
    r=sub.add_parser('resume');r.add_argument('batch_json');r.add_argument('--retry-failed',action='store_true')
    v=sub.add_parser('validate');v.add_argument('template')
    args=p.parse_args()
    if args.command=='demo':print(json.dumps(demo_report(args.output),ensure_ascii=False,indent=2))
    elif args.command=='validate':print(validate(args.template,True).to_dict())
    else:
        q=Queue(args.batch_json)
        if args.retry_failed:q.retry_failed()
        status=q.run();print(status)
        if status!='done':raise SystemExit(1)


if __name__=='__main__':main()
