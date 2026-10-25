"""数据模型：文档、编码、编码手册。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Document:
    """一篇政策文本及其元数据。"""

    doc_id: str
    title: str
    text: str
    path: str = ""
    issuer: str = ""          # 发文机关，如 "国家卫生健康委员会"
    doc_number: str = ""      # 发文字号，如 "国卫医发〔2023〕12号"
    date: str = ""            # 发文日期 YYYY-MM-DD
    level: str = ""           # 效力层级: 法律/行政法规/部门规章/规范性文件/地方规范性文件
    region: str = ""          # 地区: 国家/省级/市级，或具体省市名
    domain: str = ""          # 政策领域: 医疗卫生/人工智能/...
    url: str = ""

    @staticmethod
    def make_id(source: str) -> str:
        return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("text", None)
        return d


@dataclass
class Code:
    """一次政策工具编码结果（可追溯到方法、模型与标注者）。"""

    doc_id: str
    category: str              # 一级类目：供给型 / 需求型 / 环境型
    subcategory: str           # 二级类目：资金投入 / 政府采购 / 法规管制 ...
    evidence: str = ""         # 支撑编码的原文片段
    span_start: int = -1
    span_end: int = -1
    method: str = "rules"      # rules | llm | human
    model: str = ""            # 模型名与版本（llm 时填写）
    confidence: float = 1.0
    coder: str = "system"      # 标注者标识
    note: str = ""
    created_at: str = ""

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CodebookEntry:
    """编码手册里的一个类目。"""

    category: str
    subcategory: str
    definition: str = ""
    keywords: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    weight: float = 1.0


def now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
