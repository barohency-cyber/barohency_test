"""元数据抽取：从正文里猜发文机关、文号、日期、效力层级。"""

from __future__ import annotations

import re

DOC_NUMBER = re.compile(r"[\u4e00-\u9fa5]{1,12}〔\d{4}〕\d{1,4}号|[\u4e00-\u9fa5]{1,12}\[\d{4}\]\d{1,4}号")
DATE_CN = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
DATE_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")

ISSUER_HINTS = [
    "国务院", "中共中央", "国家发展改革委", "国家卫生健康委员会", "国家卫健委",
    "工业和信息化部", "科学技术部", "国家网信办", "国家互联网信息办公室",
    "国家医疗保障局", "国家中医药管理局", "教育部", "财政部", "民政部",
    "省人民政府", "市人民政府", "区人民政府", "县人民政府",
]

LEVEL_RULES = [
    ("法律", ["全国人民代表大会常务委员会", "主席令", "本法"]),
    ("行政法规", ["国务院令", "条例"]),
    ("部门规章", ["部令", "部门规章"]),
    ("地方性法规", ["省人民代表大会常务委员会", "市人大常委会"]),
    ("规范性文件", ["通知", "意见", "办法", "方案", "规划", "纲要"]),
]

REGION_HINTS = [
    ("国家", ["国务院", "国家", "全国", "中共中央"]),
    ("省级", ["省人民政府", "省卫生", "省卫生健康委", "省人民政府办公厅"]),
    ("市级", ["市人民政府", "市卫生健康委", "市卫健委"]),
    ("区县", ["区人民政府", "县人民政府"]),
]


def extract_doc_number(text: str) -> str:
    m = DOC_NUMBER.search(text[:2000])
    return m.group(0) if m else ""


def extract_date(text: str, fallback: str = "") -> str:
    head = text[:2000]
    m = DATE_CN.search(head) or DATE_ISO.search(head)
    if not m:
        return fallback
    y, mo, d = (int(x) for x in m.groups())
    try:
        return f"{y:04d}-{mo:02d}-{d:02d}"
    except Exception:
        return fallback


def extract_issuer(text: str, title: str = "") -> str:
    """取正文中最靠前的发文机关线索（联合发文的第一个署名机关）。"""
    head = (title + "\n" + text[:600])
    found = [(head.find(hint), -len(hint), hint) for hint in ISSUER_HINTS if hint in head]
    if found:
        return sorted(found)[0][2]
    m = re.search(r"([\u4e00-\u9fa5]{2,20}(?:委员会|部|厅|局|办公室|人民政府))", head)
    return m.group(1) if m else ""


def extract_level(text: str, title: str = "") -> str:
    head = title + "\n" + text[:800]
    for level, hints in LEVEL_RULES:
        if any(h in head for h in hints):
            return level
    return "其他"


def extract_region(text: str, issuer: str = "") -> str:
    head = issuer + "\n" + text[:800]
    for region, hints in REGION_HINTS:
        if any(h in head for h in hints):
            return region
    for name in ("北京", "上海", "广东", "江苏", "浙江", "山东", "四川", "湖北", "湖南", "河南", "河北", "安徽", "福建"):
        if name in head:
            return name
    return "国家"


SITE_SUFFIXES = ("中国政府网", "国务院文件", "中央网络安全和信息化委员会办公室", "其他")


def clean_title(line: str) -> str:
    """去掉网页标题里的站点后缀与栏目名，例如「……通知_国务院文件_中国政府网」。"""
    for sep in ("_", "｜", "|"):
        if sep in line:
            line = line.split(sep)[0]
    line = line.strip()
    for suffix in SITE_SUFFIXES:
        line = line.replace(suffix, "").strip(" -—_·")
    return line


def extract_title(text: str, fallback: str = "") -> str:
    for line in text.splitlines():
        line = clean_title(line.strip())
        if 4 <= len(line) <= 60 and not line.endswith(("。", "；")):
            return line
    return fallback or (text.strip()[:40] + "…" if text.strip() else "未命名")
