import json
import os
import uuid
from pathlib import Path
from desktop.print_names import title_for
from import_tools.miaoshou import number
from import_tools.image_rules import validate_urls

FIELDS=('main_suffix','name','title','english_title','category_id','origin','color','description','packaging_shape','packaging_type','packaging_image','variants')


def storage_dir():
    return Path(os.environ.get('APPDATA',str(Path.home()/'.config')))/'MiaoshouTemuTool'/'templates'


def validate(profile):
    if not isinstance(profile.get("main_suffix", "前"),str):raise ValueError("主图后缀必须为文字")
    for key in ('name','title','english_title','category_id','origin','color'):
        if not isinstance(profile.get(key),str) or not profile[key].strip():raise ValueError(f'模板字段 {key} 不能为空')
    title_for(profile['title'],'测试','TEST')
    variants=profile.get('variants')
    if not isinstance(variants,list) or not variants:raise ValueError('模板至少包含一个尺码')
    seen=set()
    for variant in variants:
        size=str(variant.get('size','')).strip()
        if not size or size in seen:raise ValueError('模板尺码为空或重复')
        seen.add(size)
        for key,label in [('length_cm','包装长'),('width_cm','包装宽'),('height_cm','包装高'),('weight_g','毛重')]:number(variant.get(key),size+'尺码的'+label)
        if variant.get('net_weight_g') not in (None,''):number(variant['net_weight_g'],'净重',False)
    if profile.get('packaging_shape') not in ('','长方体','不规则','圆柱体',None):raise ValueError('外包装形状无效')
    if profile.get('packaging_type') not in ('','硬包装','软包装+硬物','软包装+软物',None):raise ValueError('外包装类型无效')
    return profile


def load(path):
    data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    return validate({key:data[key] for key in FIELDS if key in data})


def save(directory,profile):
    validate(profile)
    safe={key:profile[key] for key in FIELDS if key in profile}
    path=Path(directory)/('template-'+uuid.uuid4().hex+'.json');path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as file:json.dump(safe,file,ensure_ascii=False,indent=2)
    return path


def products_to_rows(profile,products,price):
    validate(profile);price=number(price,'统一申报价');rows=[];titles={};seen=set()
    for product in products:
        sku=product['sku'];name=product['print_name']
        if not sku or not name or sku in seen:raise ValueError('货号、印花名不能为空，货号不得重复')
        seen.add(sku)
        title=title_for(profile['title'],name,sku)
        english=profile['english_title'].replace('{sku}',sku)
        titles[title]=english
        images=product['carousel_urls'].split('|')
        validate_urls(images,sku)
        from import_tools.dianxiaomi import image_url
        for url in images:image_url(url)
        image_url(product['material_url'])
        for variant in profile['variants']:
            rows.append({'产品ID':sku,'产品名称':title,'英文标题':english,'类目ID':profile['category_id'],'主货号':sku,
            '产品规格':profile['color']+'|'+str(variant['size']),'供货价':str(price)+'CNY',
            '尺寸':f'长：{variant["length_cm"]},宽：{variant["width_cm"]},高：{variant["height_cm"]}',
            '毛重(g)':str(variant['weight_g']),'净重(g)':str(variant.get('net_weight_g') or ''),
            '平台SKU':sku+'-'+str(variant['size']),'产品颜色图链接':'\n'.join(images),
            '产品素材图链接':product['material_url'],'产品描述':profile.get('description',''),
            '包装信息':f'外包装形状：{profile.get("packaging_shape","")}\n外包装类型：{profile.get("packaging_type","")}\n外包装图片链接：{profile.get("packaging_image","")}'})
    return rows,titles
