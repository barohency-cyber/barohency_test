"""编码信度：Krippendorff's α、Cohen's κ、简单一致率。

政策文本编码里，审稿人几乎必问「两个编码员一致性多少」。
本模块把这件事做成一条命令。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations

Unit = tuple[str, str, str]  # (doc_id, category, subcategory)


@dataclass
class ReliabilityResult:
    metric: str
    value: float
    n_units: int
    n_values: int
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "metric": self.metric,
            "value": round(self.value, 4),
            "n_units": self.n_units,
            "n_values": self.n_values,
            "note": self.note,
        }

    def __str__(self) -> str:
        return f"{self.metric} = {self.value:.3f} (units={self.n_units}, values={self.n_values})"


def build_units(coded: dict[str, set[Unit]], universe: set[Unit] | None = None) -> dict[Unit, list[str]]:
    """coded: coder -> 该编码员判定为「存在」的单元集合。返回 unit -> [1/0 序列]。

    universe 为空时只统计至少被一人判定的单元；**强烈建议传入完整判定空间**
    （文档 × 编码手册类目），否则「两人都没编码」的单元被丢弃，会导致
    κ 与 α 严重失真——这正是 kappa paradox 的常见成因。
    """
    if universe is not None:
        all_units = set(universe)
        for units in coded.values():
            all_units |= units
    else:
        all_units = set()
        for units in coded.values():
            all_units |= units
    out: dict[Unit, list[str]] = {}
    for u in sorted(all_units):
        out[u] = ["1" if u in units else "0" for units in coded.values()]
    return out


def universe_from_docs(doc_ids, entries) -> set[Unit]:
    """完整判定空间：每篇文档 × 每个二级类目。"""
    return {(doc_id, e.category, e.subcategory) for doc_id in doc_ids for e in entries}


def percent_agreement(units: dict[Unit, list[str]]) -> ReliabilityResult:
    if not units:
        return ReliabilityResult("percent_agreement", float("nan"), 0, 0, "无重叠编码单元")
    agree = sum(1 for vals in units.values() if len(set(vals)) == 1)
    return ReliabilityResult("percent_agreement", agree / len(units), len(units), sum(len(v) for v in units.values()))


def krippendorff_alpha_nominal(units: dict[Unit, list[str]]) -> ReliabilityResult:
    """名义尺度 Krippendorff's α，支持 2 名以上编码员、允许缺失值。"""
    usable = {u: v for u, v in units.items() if len(v) >= 2}
    if not usable:
        return ReliabilityResult("krippendorff_alpha", float("nan"), 0, 0, "可用单元不足")

    total_values = sum(len(v) for v in usable.values())
    observed = 0.0
    for vals in usable.values():
        m = len(vals)
        counts = Counter(vals)
        disagreements = sum(c * (m - c) for c in counts.values())
        observed += disagreements / (m - 1)
    do = observed / total_values

    all_values = [x for vals in usable.values() for x in vals]
    n = len(all_values)
    counts = Counter(all_values)
    if n < 2:
        return ReliabilityResult("krippendorff_alpha", float("nan"), len(usable), n, "值数量不足")
    de = sum(c * (n - c) for c in counts.values()) / (n - 1) / n * 1.0
    de = (n * n - sum(c * c for c in counts.values())) / (n * (n - 1))
    if de == 0:
        return ReliabilityResult("krippendorff_alpha", 1.0 if do == 0 else float("nan"), len(usable), n, "无变异")
    return ReliabilityResult("krippendorff_alpha", 1 - do / de, len(usable), n)


def cohen_kappa(units: dict[Unit, list[str]]) -> ReliabilityResult:
    """仅两名编码员时的 Cohen's κ。"""
    usable = {u: v for u, v in units.items() if len(v) == 2}
    if not usable:
        return ReliabilityResult("cohen_kappa", float("nan"), 0, 0, "需要恰好两名编码员")
    n = len(usable)
    po = sum(1 for v in usable.values() if v[0] == v[1]) / n
    c1 = Counter(v[0] for v in usable.values())
    c2 = Counter(v[1] for v in usable.values())
    pe = sum((c1[k] / n) * (c2[k] / n) for k in set(c1) | set(c2))
    if pe >= 1.0:  # 两名编码员边际分布完全一致且无变异：κ 在数学上无定义
        if po >= 1.0:
            return ReliabilityResult("cohen_kappa", 1.0, n, 2 * n, "无变异且完全一致")
        return ReliabilityResult("cohen_kappa", float("nan"), n, 2 * n, "无变异，κ 无定义")
    kappa = (po - pe) / (1 - pe)
    return ReliabilityResult("cohen_kappa", kappa, n, 2 * n)


def disagreement_units(units: dict[Unit, list[str]]) -> list[dict]:
    """列出有分歧的单元，供人工复核与论文附表。"""
    out = []
    for u, vals in units.items():
        if len(set(vals)) > 1:
            out.append({"doc_id": u[0], "category": u[1], "subcategory": u[2], "values": vals})
    return out


def compare_coders(coder_codes: dict[str, set[Unit]], universe: set[Unit] | None = None) -> dict:
    names = list(coder_codes.keys())
    if len(names) < 2:
        raise ValueError("至少需要两名编码员的编码结果才能计算信度")
    units = build_units(coder_codes, universe)
    result = {
        "coders": names,
        "units": int(len(units)),
        "universe_supplied": universe is not None,
        "metrics": [
            percent_agreement(units).as_dict(),
            krippendorff_alpha_nominal(units).as_dict(),
        ],
        "disagreements": disagreement_units(units)[:50],
    }
    if len(names) == 2:
        result["metrics"].append(cohen_kappa(units).as_dict())
    result["pairwise"] = {}
    for a, b in combinations(names, 2):
        pair_units = build_units({a: coder_codes[a], b: coder_codes[b]}, universe)
        result["pairwise"][f"{a} vs {b}"] = krippendorff_alpha_nominal(pair_units).as_dict()
    return result


def units_from_rows(rows, coder: str | None = None) -> set[Unit]:
    return {(r["doc_id"], r["category"], r["subcategory"]) for r in rows if coder is None or r["coder"] == coder}


def summarize_reliability(result: dict) -> str:
    lines = [f"编码员: {', '.join(result['coders'])}", f"编码单元: {result['units']}"]
    for m in result["metrics"]:
        if m["value"] == m["value"]:  # not NaN
            lines.append(f"  {m['metric']} = {m['value']:.3f}  ({m['note'] or 'n=' + str(m['n_units'])})")
    if result.get("disagreements"):
        lines.append(f"分歧单元: {len(result['disagreements'])} 个（见 CSV 导出）")
    return "\n".join(lines)


def by_category(rows) -> dict[str, set[Unit]]:
    """按一级类目分组统计分歧，便于定位手册中定义模糊的部分。"""
    out: dict[str, set[Unit]] = defaultdict(set)
    for r in rows:
        out[r["category"]].add((r["doc_id"], r["category"], r["subcategory"]))
    return dict(out)
