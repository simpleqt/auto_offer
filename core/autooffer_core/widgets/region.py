"""地名标准化（docs/03 §3.2 CascadeHandler）：档案地名 → 省/市/区 标准层级。

只做通用规则（后缀补全、分隔切分），不针对任何真实站点写死。
"""

from __future__ import annotations

import re

# 直辖市：省、市同名
_MUNICIPALITIES = {"北京", "北京市", "天津", "天津市", "上海", "上海市", "重庆", "重庆市"}

# 省级行政区（简称 → 标准名）
_PROVINCES: dict[str, str] = {
    "河北": "河北省", "山西": "山西省", "辽宁": "辽宁省", "吉林": "吉林省",
    "黑龙江": "黑龙江省", "江苏": "江苏省", "浙江": "浙江省", "安徽": "安徽省",
    "福建": "福建省", "江西": "江西省", "山东": "山东省", "河南": "河南省",
    "湖北": "湖北省", "湖南": "湖南省", "广东": "广东省", "海南": "海南省",
    "四川": "四川省", "贵州": "贵州省", "云南": "云南省", "陕西": "陕西省",
    "甘肃": "甘肃省", "青海": "青海省", "台湾": "台湾省",
    "内蒙古": "内蒙古自治区", "广西": "广西壮族自治区", "西藏": "西藏自治区",
    "宁夏": "宁夏回族自治区", "新疆": "新疆维吾尔自治区",
    "香港": "香港特别行政区", "澳门": "澳门特别行政区",
}

_SPLIT_RE = re.compile(r"[/,，、\-—\s]+")
# 单串按行政后缀切段："四川省成都市武侯区" → [四川省, 成都市, 武侯区]
_CHAIN_RE = re.compile(r"[^省市县区州盟旗]+(?:省|市|县区|区县|县|区|州|盟|旗)")


def standardize_region(name: str) -> str:
    """单个地名补全标准后缀："四川" → "四川省"，"成都" → "成都市"。"""
    name = name.strip()
    if not name:
        return name
    if name in _MUNICIPALITIES:
        return name[:2] + "市"
    if name in _PROVINCES:
        return _PROVINCES[name]
    if re.search(r"(省|市|区|县|州|盟|旗|自治区)$", name):
        return name
    # 无后缀默认按市级处理（级联中城市层最常见）
    return name + "市"


def split_region_chain(text: str) -> list[str]:
    """把档案地名拆成标准层级列表。

    >>> split_region_chain("四川省/成都市/武侯区")
    ['四川省', '成都市', '武侯区']
    >>> split_region_chain("四川成都")
    ['四川省', '成都市']
    """
    text = text.strip()
    if not text:
        return []
    parts = [p for p in _SPLIT_RE.split(text) if p]
    if len(parts) > 1:
        return [standardize_region(p) for p in parts]
    # 单串：按行政后缀切分
    chain = _CHAIN_RE.findall(text)
    if len(chain) > 1:
        return [standardize_region(p) for p in chain]
    if len(chain) == 1 and chain[0] != text:
        rest = text[len(chain[0]):]
        out = [standardize_region(chain[0])]
        if rest:
            out.append(standardize_region(rest))
        return out
    return [standardize_region(text)]
