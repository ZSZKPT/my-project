"""Editable OpenRaster sources (Krita/GIMP), without requiring Photoshop."""
from io import BytesIO
from pathlib import Path
import os
import uuid
from zipfile import ZipFile,ZIP_STORED,ZIP_DEFLATED
from xml.etree.ElementTree import Element,SubElement,tostring
from PIL import Image,ImageMath
from print_studio.core import load_image


def png(image):
    stream=BytesIO();image.save(stream,'PNG');return stream.getvalue()


def export_ora(base_path,mask_path,target,rendered=None):
    base=load_image(base_path)
    with Image.open(mask_path) as source:mask=source.convert('L')
    if mask.size!=base.size:raise ValueError('分层源文件的蒙版与底图尺寸不一致')
    if rendered is not None and rendered.size!=base.size:raise ValueError('套版效果图尺寸与底图不一致')
    merged=rendered if rendered is not None else base
    root=Element('image',{'w':str(base.width),'h':str(base.height),'name':Path(target).stem,'version':'0.0.3'})
    stack=SubElement(root,'stack')
    target=Path(target);temp=target.with_name('.'+uuid.uuid4().hex+'.ora')
    try:
        with ZipFile(temp,'w',compression=ZIP_DEFLATED) as archive:
            archive.writestr('mimetype','image/openraster',compress_type=ZIP_STORED)
            if rendered is not None:
                channels=[]
                alpha=mask.convert('F')
                for r,b in zip(rendered.convert('RGB').split(),base.split()):
                    recovered=ImageMath.lambda_eval(lambda d:((d['r']*255-d['b']*(255-d['a']))/(d['a']+(d['a']==0))), **{'r':r.convert('F'),'b':b.convert('F'),'a':alpha}).convert('L')
                    channels.append(recovered)
                layer=Image.merge('RGB',channels).convert('RGBA');layer.putalpha(mask)
                archive.writestr('data/pattern.png',png(layer))
                SubElement(stack,'layer',{'name':'花型套版（可隐藏或替换）','src':'data/pattern.png','opacity':'1.0','visibility':'visible','composite-op':'svg:src-over','x':'0','y':'0'})
            archive.writestr('data/base.png',png(base))
            SubElement(stack,'layer',{'name':'无印花底版','src':'data/base.png','opacity':'1.0','visibility':'visible','composite-op':'svg:src-over','x':'0','y':'0'})
            archive.writestr('data/mask.png',png(mask))
            SubElement(stack,'layer',{'name':'印花区域蒙版（隐藏参考）','src':'data/mask.png','opacity':'1.0','visibility':'hidden','composite-op':'svg:src-over','x':'0','y':'0'})
            archive.writestr('stack.xml',tostring(root,encoding='utf-8',xml_declaration=True))
            archive.writestr('mergedimage.png',png(merged))
            thumb=merged.copy();thumb.thumbnail((256,256));archive.writestr('Thumbnails/thumbnail.png',png(thumb))
        os.replace(temp,target)
    finally:temp.unlink(missing_ok=True)
    return target
