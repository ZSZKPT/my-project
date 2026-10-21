"""Portable, versioned domain objects. No garment names in the render engine."""
from dataclasses import dataclass, field, asdict
from pathlib import Path
import json
import math
import re


def identifier(value):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_\-]{0,79}', str(value)):
        raise ValueError('ID须为字母开头的英文、数字、下划线或短横线（最多80字符）')
    return value


def local(root, relative):
    root = Path(root).resolve()
    # JSON packages use portable relative paths, including on Linux validation.
    if not relative or '\\' in str(relative) or ':' in str(relative):
        raise ValueError('素材路径必须为模板内相对路径')
    p = (root / relative).resolve()
    if not p.is_relative_to(root) or p == root:
        raise ValueError('素材路径越出模板目录')
    return p


def finite(value, low, high, label):
    v = float(value)
    if not math.isfinite(v) or not low <= v <= high:
        raise ValueError(f'{label}范围 {low}–{high}')
    return v


@dataclass
class GarmentPart:
    id: str
    name: str
    smart_object: str


@dataclass
class GarmentType:
    id: str
    category: str
    name: str
    parts: list


@dataclass
class PrintRegion:
    id: str
    name: str
    mask: str
    part_id: str
    params: dict = field(default_factory=lambda: {
        'tile_px': 180, 'scale': 1, 'rotation': 0, 'offset_x': 0, 'offset_y': 0,
        'quad': None, 'shade_strength': 0.35})
    shade: str = ''


@dataclass
class OcclusionMask:
    mask: str = 'occlusion.png'
    description: str = '头发、皮肤、饰品等前景；白色保护'


@dataclass
class SmartObjectMapping:
    region_id: str
    name: str


@dataclass
class ExportPreset:
    width: int = 0
    height: int = 0
    crop: list = field(default_factory=list)
    quality: int = 95
    naming: str = '{view}'


@dataclass
class PrintAssignment:
    source_id: str
    params: dict = field(default_factory=dict)


@dataclass
class MockupTemplate:
    id: str
    garment_type: str
    name: str
    model_id: str
    view: str
    original: str
    base: str
    regions: list
    smart_objects: list
    occlusion: dict = field(default_factory=lambda: asdict(OcclusionMask()))
    preset: dict = field(default_factory=lambda: asdict(ExportPreset()))
    psd: str = ''
    created_at: str = ''
    version: int = 1
    schema_version: int = 1
    review: dict = field(default_factory=dict)
    ai_suggestion: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def read(cls, path):
        d = json.loads(Path(path).read_text(encoding='utf-8'))
        if d.get('schema_version') != 1:
            raise ValueError('不支持的多版型模板版本')
        obj = cls(**d)
        identifier(obj.id); identifier(obj.garment_type)
        if not isinstance(obj.regions,list) or not obj.regions:
            raise ValueError('模板至少需要一个印花分区')
        if not all(isinstance(r,dict) and all(k in r for k in ('id','name','mask','part_id','params')) for r in obj.regions):
            raise ValueError('分区须包含id/name/mask/part_id/params')
        if not isinstance(obj.smart_objects,list) or not all(isinstance(m,dict) and 'name' in m and 'region_id' in m for m in obj.smart_objects):
            raise ValueError('智能对象映射结构无效')
        if not isinstance(obj.occlusion,dict) or not obj.occlusion.get('mask') or not isinstance(obj.preset,dict):
            raise ValueError('遮挡蒙版或输出预设无效')
        ids = [identifier(r['id']) for r in obj.regions]
        names = [identifier(m['name']) for m in obj.smart_objects]
        if len(set(ids)) != len(ids) or len(set(names)) != len(names):
            raise ValueError('分区ID或智能对象名称重复')
        if sorted(m['region_id'] for m in obj.smart_objects) != sorted(ids):
            raise ValueError('每个分区必须对应唯一智能对象')
        return obj


def catalog(path):
    types = json.loads(Path(path).read_text(encoding='utf-8'))['types']
    result = {}
    for d in types:
        g = GarmentType(**d); identifier(g.id)
        if g.id in result or not g.parts:
            raise ValueError('版型ID重复或部件为空')
        seen = set()
        for part in g.parts:
            p = GarmentPart(**part); identifier(p.id); identifier(p.smart_object)
            if p.id in seen: raise ValueError('部件ID重复')
            seen.add(p.id)
        result[g.id] = g
    return result
