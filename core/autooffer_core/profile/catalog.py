"""字段语义目录（canonical dictionary）——扁平标签/别名/受限级的唯一事实源。

背景：同一份「字段语义」知识曾分散在 6 处维护（schema 敏感级注释、
resolver 目录描述、flat_profile 标签、mapping 别名、extension 反向别名
与域正则、completeness 的 Python/TS 镜像），户籍语义修复一次要动 4 个
代码点即实证分叉。本模块收敛 Python 侧三处：

- ``FLAT_LABELS``：扁平档案可能输出的全部标签清单（flat_profile 产出、
  别名目标、守护测试比对口径）。新增标签必须先登记于此。
- ``LABEL_ALIASES``：常见站点措辞 → 扁平标签（AI 映射的零 LLM 快路径）。
  目标必须是 FLAT_LABELS 成员（守护测试强制）。
- ``RESTRICTED_LABELS``：受限（restricted）值的输出标签——授权后可写入
  页面，但禁止进入 LLM 提示词（插件与 option-match 双端过滤）。

schema 的 sensitivity 元数据仍是敏感**级**的判定源（_sensitive_names /
_get_by_path 直接读 pydantic 元数据），本清单只管**标签**层的一致性。

二阶段（另行开工）：域隔离（家庭/科研/奖惩/教育/户籍）的标签→域映射
在本模块登记并经 /flat 下发，extension 的硬编码域正则改为消费下发数据。
"""

from __future__ import annotations

# 扁平档案可能输出的全部标签（flat_profile._Flattener 各方法键的并集）。
# 守护测试断言实际输出 ⊆ 本清单；改名须同步 flat_profile 与此处。
FLAT_LABELS: frozenset[str] = frozenset({
    # basic（含并入的扩展常问字段）
    "姓名", "姓", "名", "性别", "出生日期", "手机号码", "电子邮箱",
    "籍贯", "现居住城市", "政治面貌", "国籍", "工作年限", "民族",
    "是否全日制", "是否统招", "学制", "生源地", "户籍所在地", "入党时间",
    # basic · 敏感授权后并入
    "身份证号", "婚姻状况", "身高（厘米）", "体重（公斤）", "健康状况",
    # intention
    "意向岗位", "期望城市", "期望月薪(税前)", "现月薪(税前)",
    "期望从事行业", "可到岗时间", "出差意愿", "接受工作地调剂",
    # education（repeat）
    "学校", "学院", "专业", "学历", "学位", "成绩", "开始时间", "结束时间",
    # experiences（repeat）
    "项目名称", "项目职务", "项目描述", "项目链接",
    "公司", "职位", "工作内容", "工作成果",
    # extended.languages（repeat）
    "外语种类", "外语水平", "外语成绩", "获得时间",
    # extended.awards（repeat）
    "奖惩名称", "奖励等级", "奖惩时间", "奖惩描述",
    # extended.campus_roles（repeat）
    "组织名称", "职务",
    # extended.family_members（repeat · 敏感授权后）
    "关系", "工作单位", "电话",
    # extended.emergency_contact（敏感授权后）
    "紧急联系人", "紧急联系人电话", "与紧急联系人关系",
    # other
    "专业技能", "证书", "自我评价", "兴趣爱好", "特长", "性格特点", "MBTI",
    # extended.links 的键（github/blog 等）为用户自定，不在此登记；
    # 守护测试对 other 段做白名单外的宽容处理
})

# 受限（restricted）值的输出标签：授权后可写入页面，但不得进入
# LLM 提示词（flat_profile 据此产出 restrictedLabels，插件据此过滤 picks）。
RESTRICTED_IDCARD = "身份证号"            # basic.id_number（restricted）
RESTRICTED_FAMILY_PHONE = "电话"          # 家庭成员电话（restricted）
RESTRICTED_EMERGENCY_PHONE = "紧急联系人电话"  # 紧急联系人电话（restricted）
RESTRICTED_LABELS: frozenset[str] = frozenset({
    RESTRICTED_IDCARD,
    RESTRICTED_FAMILY_PHONE,
    RESTRICTED_EMERGENCY_PHONE,
})

# 常见站点措辞 → 扁平档案标签（AI 映射快路径，零 LLM）。
# 只收录语义唯一、无分区歧义的映射；语义有歧义的（如 毕业时间→哪个
# 分区的结束时间）仍交 LLM 按区块判定。目标必须是 FLAT_LABELS 成员。
LABEL_ALIASES: dict[str, str] = {
    "出生地": "籍贯",
    "成长地": "籍贯",
    "祖籍": "籍贯",
    # 户口≠籍贯：户口类页面字段指向户籍（flat 已默认下发该字段）
    "户口所在地": "户籍所在地",
    "户口": "户籍所在地",
    "户籍": "户籍所在地",
    "手机": "手机号码",
    "联系电话": "手机号码",
    "联系方式": "手机号码",
    "电话": "手机号码",
    "手机号": "手机号码",
    "邮箱": "电子邮箱",
    "电子邮件": "电子邮箱",
    "mail": "电子邮箱",
    "e-mail": "电子邮箱",
    "毕业院校": "学校",
    "就读院校": "学校",
    "院校": "学校",
    "就读学校": "学校",
    "所学专业": "专业",
    "就读专业": "专业",
    "最高学历": "学历",
    "应聘职位": "意向岗位",
    "期望职位": "意向岗位",
    "意向职位": "意向岗位",
    "期望薪资": "期望月薪(税前)",
    "期望月薪": "期望月薪(税前)",
    "现月薪": "现月薪(税前)",
    "目前月薪": "现月薪(税前)",
    "居住城市": "现居住城市",
    "所在城市": "现居住城市",
    "现居城市": "现居住城市",
    "证件号码": "身份证号",
    "身份证号码": "身份证号",
    "自我介绍": "自我评价",
    "个人评价": "自我评价",
    "个人简介": "自我评价",
    "求职信": "自我评价",
}


def validate_catalog() -> list[str]:
    """自检（供测试与启动诊断）：返回问题清单，空列表即一致。"""
    problems: list[str] = []
    for src, dst in LABEL_ALIASES.items():
        if dst not in FLAT_LABELS:
            problems.append(f"别名目标不在 FLAT_LABELS: {src} -> {dst}")
    if not RESTRICTED_LABELS <= FLAT_LABELS:
        problems.append(
            f"RESTRICTED_LABELS 越界: {sorted(RESTRICTED_LABELS - FLAT_LABELS)}"
        )
    return problems
