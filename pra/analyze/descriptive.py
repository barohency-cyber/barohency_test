"""描述性分析与政策组合（policy mix）统计。"""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations

from ..store import get_codes


def load_rows(conn, coder: str | None = None) -> list[dict]:
    return [dict(r) for r in get_codes(conn, coder=coder)]


def category_distribution(rows: list[dict]) -> dict[str, int]:
    return dict(Counter(r["category"] for r in rows))


def subcategory_distribution(rows: list[dict]) -> list[tuple[str, str, int]]:
    c = Counter((r["category"], r["subcategory"]) for r in rows)
    return [(cat, sub, n) for (cat, sub), n in c.most_common()]


def by_year(rows: list[dict], dates: dict[str, str]) -> dict[str, dict[str, int]]:
    out: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        date = dates.get(r["doc_id"], "") or ""
        year = date[:4] if len(date) >= 4 else "未知"
        out[year][r["category"]] += 1
    return {y: dict(c) for y, c in sorted(out.items())}


def by_field(rows: list[dict], field: dict[str, str]) -> dict[str, Counter]:
    out: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        key = field.get(r["doc_id"], "") or "未标注"
        out[key][r["category"]] += 1
    return {k: dict(v) for k, v in sorted(out.items())}


def documents_meta(conn) -> tuple[dict[str, dict], dict[str, str]]:
    rows = conn.execute("SELECT doc_id, date, domain, region, level, issuer, title FROM documents").fetchall()
    meta = {r["doc_id"]: dict(r) for r in rows}
    dates = {r["doc_id"]: (r["date"] or "") for r in rows}
    return meta, dates


def policy_mix(rows: list[dict]) -> dict:
    """政策组合：每篇文档使用的工具数量、以及工具共现强度。"""
    per_doc: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for r in rows:
        per_doc[r["doc_id"]].add((r["category"], r["subcategory"]))
    sizes = [len(v) for v in per_doc.values()]
    pair_counts: Counter = Counter()
    for tools in per_doc.values():
        for a, b in combinations(sorted(tools), 2):
            pair_counts[(a, b)] += 1
    n_docs = len(per_doc)
    top_pairs = [
        {"a": f"{a[0]}/{a[1]}", "b": f"{b[0]}/{b[1]}", "count": n, "share": round(n / n_docs, 3)}
        for (a, b), n in pair_counts.most_common(15)
    ]
    return {
        "n_documents": n_docs,
        "avg_tools_per_doc": round(sum(sizes) / n_docs, 2) if n_docs else 0.0,
        "max_tools": max(sizes) if sizes else 0,
        "min_tools": min(sizes) if sizes else 0,
        "top_pairs": top_pairs,
    }


def coverage(rows: list[dict], meta: dict[str, dict]) -> dict:
    coded_docs = {r["doc_id"] for r in rows}
    by_domain: dict[str, dict[str, int]] = defaultdict(lambda: {"documents": 0, "coded": 0})
    for doc_id, m in meta.items():
        d = m.get("domain") or "未标注"
        by_domain[d]["documents"] += 1
        if doc_id in coded_docs:
            by_domain[d]["coded"] += 1
    return dict(by_domain)


def summarize(conn, coder: str | None = None) -> dict:
    rows = load_rows(conn, coder)
    meta, dates = documents_meta(conn)
    return {
        "coder": coder or "全部",
        "n_codes": len(rows),
        "n_documents": len({r["doc_id"] for r in rows}),
        "categories": category_distribution(rows),
        "subcategories": subcategory_distribution(rows),
        "by_year": by_year(rows, dates),
        "by_domain": by_field(rows, {k: v.get("domain", "") for k, v in meta.items()}),
        "by_region": by_field(rows, {k: v.get("region", "") for k, v in meta.items()}),
        "by_level": by_field(rows, {k: v.get("level", "") for k, v in meta.items()}),
        "policy_mix": policy_mix(rows),
        "coverage": coverage(rows, meta),
        "documents": meta,
    }
