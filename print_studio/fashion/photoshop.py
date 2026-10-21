"""Native Photoshop creation bridge. A prepared script is NOT a validated PSD."""
from pathlib import Path
import json
import os
import subprocess
from PIL import Image
from print_studio.core import atomic_json, load_image, save_png, sha256
from .library import validate,fingerprint
from .models import local
from .render import render


def prepare(path,sources,assignments,directory,jpg=None):
    s=validate(path,True);directory=Path(directory).resolve()
    directory.mkdir(parents=True,exist_ok=False)
    result,layers=render(path,sources,assignments,return_layers=True)
    save_png(load_image(local(Path(path).parent,s.base)),directory/'base.png')
    config={'template_id':s.id,'template_version':s.version,'width':result.width,'height':result.height,
            'template_fingerprint':fingerprint(path),
            'psd':str(directory/'mockup.psd'),'jpg':str(Path(jpg).resolve()) if jpg else '',
            'report':str(directory/'photoshop-report.json'),'base':str(directory/'base.png'),
            'preset':s.preset,'regions':[],'status':'awaiting_photoshop',
            'perspective_mode':'prepared_pixels_inside_native_smart_object'}
    mappings={m['region_id']:m['name'] for m in s.smart_objects}
    for rid,plane,mask in layers:
        image=directory/(rid+'-print.png');m=directory/(rid+'-mask.png')
        save_png(plane,image);save_png(mask,m)
        config['regions'].append({'id':rid,'name':mappings[rid],'image':str(image),'mask':str(m)})
    # print masks already exclude foreground; this top group also preserves it explicitly.
    occ=directory/'occlusion.png'
    with Image.open(local(Path(path).parent,s.occlusion['mask'])) as m:save_png(m,occ)
    config['occlusion']=str(occ)
    with Image.open(occ) as mask:config['has_occlusion']=bool(mask.getbbox())
    save_png(result,directory/'local-preview.png')
    atomic_json(directory/'manifest.json',config)
    script=JSX.replace('__CONFIG__',json.dumps(config,ensure_ascii=True))
    (directory/'create-and-verify.jsx').write_text(script,encoding='utf-8')
    (directory/'README.txt').write_text(
        '等待 Photoshop 验证。Photoshop：文件 > 脚本 > 浏览 > create-and-verify.jsx。\n'
        '脚本由 Photoshop 实际创建原生智能对象、打开内容并测试编辑、保存并重新打开PSD。\n'
        '完成后导入photoshop-report.json。没有该报告不能声称已验证。\n'
        '透视与平铺由本地计算准备，烘焙在智能对象内部；不声称为Photoshop可回退透视网格。\n'
        '每个对象可原生编辑、移动、缩放、旋转；更改原始花型/透视参数后在应用内重新准备。\n'
        '勿移动本目录后直接运行脚本（内部含本机绝对路径）；移动后请重新准备。',encoding='utf-8')
    return directory/'create-and-verify.jsx'


def verification(report,psd=None):
    r=json.loads(Path(report).read_text(encoding='utf-8'))
    if r.get('status')!='verified' or not r.get('photoshop_version') or not r.get('reopened'):
        raise ValueError('报告未通过Photoshop保存/重新打开验证')
    regions=r.get('regions',[])
    if not regions or not all(v.get('native') and v.get('editable') for v in regions):
        raise ValueError('原生智能对象或内容编辑验证失败')
    psd=Path(psd or r['psd'])
    if psd.read_bytes()[:4]!=b'8BPS':raise ValueError('未找到真实PSD文件头')
    # Bridge-produced report is evidence from the user's Photoshop, not a cloud test.
    return r


def run_script(script,timeout=600):
    if os.name!='nt':raise RuntimeError('此环境没有Windows Photoshop；请在安装Photoshop的电脑运行JSX')
    script=Path(script).resolve()
    # Do not interpolate file names into shell/PowerShell code.
    bridge=script.parent/'run-photoshop.ps1'
    bridge.write_text("param([string]$ScriptPath)\n$ErrorActionPreference='Stop'\n"
                      "$ps = New-Object -ComObject Photoshop.Application\n$ps.Visible=$true\n"
                      "$null=$ps.DoJavaScriptFile($ScriptPath)\n",encoding='utf-8')
    completed=subprocess.run(['powershell.exe','-NoProfile','-File',str(bridge),str(script)],capture_output=True,timeout=timeout)
    if completed.returncode:raise RuntimeError('Photoshop脚本执行失败；请在Photoshop中手动运行JSX并查看错误报告')


def render_in_photoshop(path,sources,assignments,target,directory):
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    # A failed run is retained for review, retries get their own preparation folder.
    import uuid
    directory=Path(directory)/uuid.uuid4().hex[:8]
    script=prepare(path,sources,assignments,directory,target)
    run_script(script)
    verification(directory/'photoshop-report.json')
    if not target.is_file():raise RuntimeError('Photoshop未导出JPG')


JSX=r'''#target photoshop
(function () {
var C = __CONFIG__;
var oldDialogs=app.displayDialogs, oldUnits=app.preferences.rulerUnits;
var report={status:'failed',template_id:C.template_id,template_version:C.template_version,
    template_fingerprint:C.template_fingerprint,photoshop_version:app.version,psd:C.psd,regions:[],reopened:false};
var doc=null;
// ExtendScript hosts do not consistently ship JSON.stringify.
function json(v){
    if(v===null)return 'null';
    if(typeof v=='string')return '"'+v.replace(/\\/g,'\\\\').replace(/"/g,'\\"').replace(/\r/g,'\\r').replace(/\n/g,'\\n').replace(/\t/g,'\\t')+'"';
    if(typeof v=='boolean'||typeof v=='number')return String(v);
    var a=[],k;if(v instanceof Array){for(k=0;k<v.length;k++)a.push(json(v[k]));return '['+a.join(',')+']';}
    for(k in v)if(v.hasOwnProperty(k))a.push(json(k)+':'+json(v[k]));return '{'+a.join(',')+'}';
}
function writeReport(){var f=new File(C.report);f.encoding='UTF8';f.open('w');f.write(json(report));f.close();}
function importLayer(file,name){
    var input=app.open(new File(file));
    input.activeLayer.name=name;
    var layer=input.activeLayer.duplicate(doc,ElementPlacement.PLACEATBEGINNING);
    input.close(SaveOptions.DONOTSAVECHANGES);app.activeDocument=doc;
    return layer;
}
function mask(group,file){
    var src=app.open(new File(file));src.selection.selectAll();src.selection.copy();src.close(SaveOptions.DONOTSAVECHANGES);
    app.activeDocument=doc;
    var alpha=doc.channels.add();alpha.name='mask_temp';doc.activeChannels=[alpha];doc.paste();doc.selection.deselect();
    doc.activeChannels=doc.componentChannels;doc.selection.load(alpha,SelectionType.REPLACE);doc.activeLayer=group;
    var d=new ActionDescriptor(),ref=new ActionReference();ref.putClass(charIDToTypeID('Chnl'));d.putReference(charIDToTypeID('Nw  '),ref);
    var at=new ActionReference();at.putEnumerated(charIDToTypeID('Chnl'),charIDToTypeID('Chnl'),charIDToTypeID('Msk '));d.putReference(charIDToTypeID('At  '),at);
    d.putEnumerated(charIDToTypeID('Usng'),charIDToTypeID('UsrM'),charIDToTypeID('RvlS'));executeAction(charIDToTypeID('Mk  '),d,DialogModes.NO);
    doc.selection.deselect();alpha.remove();doc.activeChannels=doc.componentChannels;
}
try{
    app.displayDialogs=DialogModes.NO;app.preferences.rulerUnits=Units.PIXELS;
    doc=app.open(new File(C.base));doc.activeLayer.name='MODEL_BASE';
    for(var i=0;i<C.regions.length;i++){
        var r=C.regions[i],group=doc.layerSets.add();group.name=r.name+'_REGION';
        var layer=importLayer(r.image,r.name);layer.move(group,ElementPlacement.INSIDE);doc.activeLayer=layer;
        executeAction(stringIDToTypeID('newPlacedLayer'),undefined,DialogModes.NO);
        var smart=doc.activeLayer;smart.name=r.name;
        var nativeOK=smart.kind==LayerKind.SMARTOBJECT;
        if(!nativeOK)throw new Error('Not native smart object: '+r.name);
        executeAction(stringIDToTypeID('placedLayerEditContents'),undefined,DialogModes.NO);
        var content=app.activeDocument;
        if(content==doc)throw new Error('Cannot open smart contents: '+r.name);
        // Actually edit/save a transparent probe layer in the smart contents.
        var probe=content.artLayers.add();probe.name='EDITABILITY_CHECK';probe.remove();
        content.save();content.close(SaveOptions.SAVECHANGES);app.activeDocument=doc;
        mask(group,r.mask);
        report.regions.push({name:r.name,native:nativeOK,editable:true});
    }
    if(C.has_occlusion){var foreground=doc.layerSets.add();foreground.name='FOREGROUND_OCCLUSION';
    var fg=importLayer(C.base,'ORIGINAL_FOREGROUND');fg.move(foreground,ElementPlacement.INSIDE);mask(foreground,C.occlusion);}
    var opts=new PhotoshopSaveOptions();opts.layers=true;opts.embedColorProfile=true;
    doc.saveAs(new File(C.psd),opts,true,Extension.LOWERCASE);doc.close(SaveOptions.DONOTSAVECHANGES);
    doc=app.open(new File(C.psd));
    if(doc.width.as('px')!=C.width || doc.height.as('px')!=C.height)throw new Error('PSD dimensions changed');
    for(var j=0;j<C.regions.length;j++){
        var g=doc.layerSets.getByName(C.regions[j].name+'_REGION');
        if(g.artLayers.getByName(C.regions[j].name).kind!=LayerKind.SMARTOBJECT)throw new Error('Reopened layer not smart');
    }
    report.reopened=true;
    if(C.jpg){
        // Export a duplicate; preserve layered master PSD.
        var out=doc.duplicate();out.flatten();
        var crop=C.preset.crop;if(crop && crop.length==4)out.crop(crop);
        if(C.preset.width && C.preset.height)out.resizeImage(UnitValue(C.preset.width,'px'),UnitValue(C.preset.height,'px'),null,ResampleMethod.BICUBIC);
        var jpg=new JPEGSaveOptions();jpg.quality=Math.max(1,Math.min(12,Math.round(C.preset.quality*12/100)));jpg.embedColorProfile=true;
        out.saveAs(new File(C.jpg),jpg,true,Extension.LOWERCASE);out.close(SaveOptions.DONOTSAVECHANGES);
    }
    doc.close(SaveOptions.DONOTSAVECHANGES);doc=null;report.status='verified';
}catch(e){report.error=String(e);throw e;}
finally{writeReport();app.displayDialogs=oldDialogs;app.preferences.rulerUnits=oldUnits;}
})();
'''
