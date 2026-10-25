"""编码手册加载与校验。"""

from __future__ import annotations

from pathlib import Path

import yaml

from ..schema import CodebookEntry

CODEBOOK_DIR = Path(__file__).parent
DEFAULT_CODEBOOK = CODEBOOK_DIR / "zegveld.yaml"


def load_codebook(path: str | Path | None = None) -> tuple[dict, list[CodebookEntry]]:
    """返回 (原始 meta, 展平后的类目列表)。"""
    path = Path(path) if path else DEFAULT_CODEBOOK
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries: list[CodebookEntry] = []
    for category, block in raw.get("categories", {}).items():
        for item in block.get("entries", []):
            entries.append(
                CodebookEntry(
                    category=category,
                    subcategory=item["subcategory"],
                    definition=item.get("definition", ""),
                    keywords=list(item.get("keywords", [])),
                    excludes=list(item.get("excludes", [])),
                    examples=list(item.get("examples", [])),
                    weight=float(item.get("weight", 1.0)),
                )
            )
    meta = {k: v for k, v in raw.items() if k != "categories"}
    return meta, entries


def category_map(entries: list[CodebookEntry]) -> dict[str, list[str]]:
    """一级类目 -> 二级类目列表。"""
    out: dict[str, list[str]] = {}
    for e in entries:
        out.setdefault(e.category, []).append(e.subcategory)
    return out


def validate(entries: list[CodebookEntry]) -> list[str]:
    """返回发现的问题；空列表表示通过。"""
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    for e in entries:
        key = (e.category, e.subcategory)
        if key in seen:
            problems.append(f"重复类目: {e.category}/{e.subcategory}")
        seen.add(key)
        if not e.keywords:
            problems.append(f"缺少关键词: {e.category}/{e.subcategory}")
    overlap = set()
    for e in entries:
        overlap |= set(e.keywords)
    for e in entries:
        for kw in e.keywords:
            if sum(kw in other.keywords for other in entries) > 1:
                problems.append(f"关键词跨类目重复: {kw}")
                break
    return sorted(set(problems))
