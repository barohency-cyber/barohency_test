"""规则基线编码器。

为什么要有规则基线？
  - LLM 编码需要网络与 API key，审稿人会问「换台机器还能复现吗」
  - 规则版无依赖、可完全复现，可作为 LLM 标注的对照与兜底
  - 两者的一致性本身就是论文里的一张表
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..schema import Code, CodebookEntry, Document, now_iso

# 否定线索：出现时该命中视为「禁止/限制」语境，不计入供给型或需求型
NEGATIONS = ("不得", "禁止", "严禁", "不予", "不得擅自", "取消", "暂停")
NEGATION_WINDOW = 8

WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """去掉空白，避免「财 政 拨 款」这类排版断裂导致漏检。"""
    return WS.sub("", text)


def _snippet(text: str, start: int, end: int, pad: int = 18) -> str:
    lo = max(0, start - pad)
    hi = min(len(text), end + pad)
    return ("…" if lo > 0 else "") + text[lo:hi] + ("…" if hi < len(text) else "")


def _negated(text: str, start: int) -> bool:
    window = text[max(0, start - NEGATION_WINDOW):start]
    return any(n in window for n in NEGATIONS)


def _excluded(text: str, start: int, end: int, excludes: list[str], pad: int = 12) -> bool:
    if not excludes:
        return False
    window = text[max(0, start - pad):end + pad]
    return any(x in window for x in excludes)


@dataclass
class Match:
    subcategory: str
    category: str
    keyword: str
    start: int
    end: int
    count: int
    negated: bool


def find_matches(text: str, entries: list[CodebookEntry]) -> list[Match]:
    norm = normalize(text)
    out: list[Match] = []
    for entry in entries:
        hits: list[tuple[int, int, str]] = []
        for kw in entry.keywords:
            start = 0
            while True:
                i = norm.find(kw, start)
                if i < 0:
                    break
                start = i + len(kw)
                if _excluded(norm, i, i + len(kw), entry.excludes):
                    continue
                hits.append((i, i + len(kw), kw))
        if not hits:
            continue
        # 选一个最具代表性的命中：关键词最长、位置最靠前
        best = sorted(hits, key=lambda h: (-len(h[2]), h[0]))[0]
        out.append(
            Match(
                subcategory=entry.subcategory,
                category=entry.category,
                keyword=best[2],
                start=best[0],
                end=best[1],
                count=len(hits),
                negated=_negated(norm, best[0]),
            )
        )
    return out


def confidence_of(match: Match) -> float:
    base = 0.50 + 0.08 * min(match.count, 5) + 0.03 * min(len(match.keyword), 6)
    if match.negated:
        base -= 0.15
    return round(max(0.30, min(0.95, base)), 2)


def code_document(doc: Document, entries: list[CodebookEntry], coder: str = "rules") -> list[Code]:
    """对单篇文档编码。同一二级类目只保留一条最强证据。"""
    norm = normalize(doc.text)
    codes: list[Code] = []
    for m in find_matches(doc.text, entries):
        code = Code(
            doc_id=doc.doc_id,
            category=m.category,
            subcategory=m.subcategory,
            evidence=_snippet(norm, m.start, m.end),
            span_start=m.start,
            span_end=m.end,
            method="rules",
            model="keyword-v1",
            confidence=confidence_of(m),
            coder=coder,
            note=f"命中 {m.count} 次" + ("；否定语境" if m.negated else ""),
            created_at=now_iso(),
        )
        codes.append(code)
    return codes


def code_corpus(docs: list[Document], entries: list[CodebookEntry], coder: str = "rules") -> dict[str, list[Code]]:
    return {doc.doc_id: code_document(doc, entries, coder) for doc in docs}
