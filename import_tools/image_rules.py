MIN_IMAGES=5
MAX_IMAGES=10


def validate_count(count,label='商品'):
    if not MIN_IMAGES<=count<=MAX_IMAGES:
        raise ValueError(f'{label}有{count}张商品图，需要5至10张；素材图不计入，请补齐或移除多余图片')


def validate_groups(groups,key='files'):
    invalid=[f'{group["sku"]}（{len(group[key])}张）' for group in groups if not MIN_IMAGES<=len(group[key])<=MAX_IMAGES]
    if invalid:raise ValueError('以下货号需要5至10张商品图，素材图不计入：'+ '、'.join(invalid))


def validate_urls(urls,label='商品'):
    validate_count(len(urls),label)
    if len(set(urls))!=len(urls):raise ValueError(f'{label}的商品图链接有重复，请提供5至10张不同图片')
