"""选项语义匹配与地名标准化单元测试（docs/03 §3.2）。

这两个纯函数决定了下拉与级联的泛化准确率，是控件层最需要回归保护的部分。
"""

from __future__ import annotations

from autooffer_core.widgets.matching import match_option, normalize_text
from autooffer_core.widgets.region import split_region_chain, standardize_region

# ---------- 选项语义匹配 ----------


def test_exact_match_wins() -> None:
    hit = match_option("本科", ["大专", "本科", "硕士"])
    assert hit == ("本科", "exact")


def test_normalized_match_synonym() -> None:
    """档案"本科" 应命中站点的"全日制本科"（同义词表加速）。"""
    hit = match_option("本科", ["请选择", "全日制本科", "硕士研究生"])
    assert hit is not None
    assert hit[0] == "全日制本科"
    assert hit[1] == "normalized"


def test_normalized_match_ignores_whitespace_and_case() -> None:
    assert match_option("cet-6", ["  CET-6 "]) == ("  CET-6 ", "normalized")


def test_normalized_match_fullwidth() -> None:
    """全角数字/字母经 NFKC 归一后应匹配。"""
    hit = match_option("N2", ["Ｎ２"])
    assert hit is not None
    assert hit[1] == "normalized"


def test_contains_match_prefers_shortest() -> None:
    """包含级命中多个时取最短候选，减少误命中。"""
    hit = match_option("硕士", ["硕士研究生（学术型）", "硕士", "工程硕士专业学位"])
    assert hit == ("硕士", "exact")  # 有精确项时不降级

    hit2 = match_option("研究生", ["硕士研究生（学术型）", "研究生及以上"])
    assert hit2 is not None
    assert hit2[0] == "研究生及以上"  # 两者都含"研究生"，取更短的


def test_no_match_returns_none() -> None:
    assert match_option("博士后", ["大专", "本科"]) is None
    assert match_option("", ["本科"]) is None
    assert match_option("本科", []) is None


def test_present_synonyms_for_date_range() -> None:
    """日期区间"至今"需能匹配站点的多种表达。"""
    for opt in ("现在", "目前", "Present", "now"):
        assert match_option("至今", [opt]) is not None


def test_gender_synonyms() -> None:
    assert match_option("男", ["male", "female"]) is not None
    assert match_option("女", ["女性"]) is not None


def test_normalize_text() -> None:
    assert normalize_text(" 全日制 本科 ") == "全日制本科"
    assert normalize_text("ＣＥＴ-６") == "cet-6"


# ---------- 地名标准化 ----------


def test_standardize_province_and_city() -> None:
    assert standardize_region("四川") == "四川省"
    assert standardize_region("成都") == "成都市"  # 无后缀默认按市级
    assert standardize_region("成都市") == "成都市"  # 已有后缀不重复加


def test_standardize_autonomous_and_municipality() -> None:
    assert standardize_region("内蒙古") == "内蒙古自治区"
    assert standardize_region("广西") == "广西壮族自治区"
    assert standardize_region("北京") == "北京市"
    assert standardize_region("上海市") == "上海市"


def test_standardize_keeps_district_suffix() -> None:
    assert standardize_region("武侯区") == "武侯区"
    assert standardize_region("双流县") == "双流县"


def test_split_chain_with_separators() -> None:
    assert split_region_chain("四川省/成都市/武侯区") == ["四川省", "成都市", "武侯区"]
    assert split_region_chain("四川省 成都市") == ["四川省", "成都市"]
    assert split_region_chain("四川省，成都市") == ["四川省", "成都市"]


def test_split_chain_single_string_by_suffix() -> None:
    """档案里常见的连写形式需能切成级联层级。"""
    assert split_region_chain("四川省成都市武侯区") == ["四川省", "成都市", "武侯区"]


def test_split_chain_abbreviated() -> None:
    """"四川成都" 无后缀：切分后各段补全标准后缀。"""
    assert split_region_chain("四川成都") == ["四川省", "成都市"]


def test_split_chain_single_and_empty() -> None:
    assert split_region_chain("成都市") == ["成都市"]
    assert split_region_chain("") == []
