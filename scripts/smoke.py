"""无需 pytest 的冒烟测试：只用标准库 + pyyaml，验证核心链路。

用途：在没有测试依赖（或 pip 受限）的机器上快速自检。
运行：python scripts/smoke.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pra.analyze.descriptive import summarize  # noqa: E402
from pra.codebook import load_codebook, validate  # noqa: E402
from pra.coder.reliability import build_units, compare_coders, krippendorff_alpha_nominal, percent_agreement  # noqa: E402
from pra.coder.rules import code_document, normalize  # noqa: E402
from pra.ingest import parse_file  # noqa: E402
from pra.report.html import render_report  # noqa: E402
from pra.schema import Document  # noqa: E402
from pra.store import connect, get_codes, init_db, replace_codes, stats, upsert_document  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{'  ' + detail if detail and not cond else ''}")


def main() -> int:
    print("[1] 编码手册")
    meta, entries = load_codebook()
    check("手册可加载", bool(entries), f"entries={len(entries)}")
    check("三个一级类目", {e.category for e in entries} == {"供给型", "需求型", "环境型"})
    problems = validate(entries)
    check("手册校验通过", not problems, "; ".join(problems[:3]))
    print(f"      框架: {meta.get('framework', '')} v{meta.get('version')}, {len(entries)} 个二级类目")

    print("[2] 规则编码")
    doc = Document(
        doc_id="smoke1",
        title="测试政策",
        text="中央财政安排专项资金，支持人才培养与关键技术研发。制定管理办法，加强监督管理，"
             "开展试点示范。通过政府采购和政府购买服务扩大供给。严禁以设立基金名义变相举债。",
        date="2024-01-01",
        domain="医疗卫生",
    )
    codes = code_document(doc, entries, coder="rules")
    subs = {c.subcategory for c in codes}
    check("识别到编码", len(codes) >= 4, f"codes={len(codes)}")
    check("资金投入", "资金投入" in subs)
    check("人才培养", "人才培养" in subs)
    check("法规管制", "法规管制" in subs)
    check("政府采购", "政府采购" in subs)
    check("归一化去空白", normalize("财 政\n拨款") == "财政拨款")
    check("置信度在合理区间", all(0.0 < c.confidence <= 1.0 for c in codes))
    print(f"      命中: {', '.join(sorted(subs))}")

    print("[3] 信度计算")
    perfect = build_units({"a": {("d1", "供给型", "资金投入")}, "b": {("d1", "供给型", "资金投入")}})
    check("完全一致 alpha=1", abs(krippendorff_alpha_nominal(perfect).value - 1.0) < 1e-9)
    check("完全一致 一致率=1", percent_agreement(perfect).value == 1.0)
    disagree = build_units({"a": {("d1", "供给型", "资金投入")}, "b": {("d1", "环境型", "法规管制")}})
    check("完全分歧 alpha<0.2", krippendorff_alpha_nominal(disagree).value < 0.2)
    # 完整判定空间：两人都未编码的单元必须计入，否则 κ 会被高估或失真
    uni = {("d1", "供给型", "资金投入"), ("d1", "需求型", "政府采购"), ("d1", "环境型", "法规管制")}
    subset = build_units({"a": {("d1", "供给型", "资金投入")}, "b": {("d1", "供给型", "资金投入")}}, uni)
    check("判定空间补齐缺席单元", len(subset) == 3)
    r = compare_coders({"a": {("d1", "供给型", "资金投入")}, "b": {("d1", "供给型", "资金投入")}}, uni)
    kappa = [m["value"] for m in r["metrics"] if m["metric"] == "cohen_kappa"][0]
    check("一致时 kappa 正常", abs(kappa - 1.0) < 1e-9, f"kappa={kappa}")
    try:
        compare_coders({"a": {("d1", "供给型", "资金投入")}})
        check("单编码员应报错", False)
    except ValueError:
        check("单编码员应报错", True)

    print("[4] 存储与统计")
    tmp = Path(ROOT) / "data" / "_smoke"
    tmp.mkdir(parents=True, exist_ok=True)
    conn = connect(tmp / "smoke.sqlite3")
    init_db(conn)
    docs = [
        doc,
        Document(doc_id="smoke2", title="第二篇", text="制定规划纲要，明确发展目标。加强财政拨款和经费保障。",
                 date="2023-06-01", domain="医疗卫生", level="规范性文件", region="国家"),
    ]
    for d in docs:
        upsert_document(conn, d)
        replace_codes(conn, d.doc_id, "rules", code_document(d, entries, "rules"))
    s = stats(conn)
    check("文档入库", s["documents"] == 2, json.dumps(s, ensure_ascii=False))
    check("编码入库", s["codes"] > 0)
    check("幂等重编码", replace_codes(conn, doc.doc_id, "rules", code_document(doc, entries, "rules")) == len(codes))

    print("[5] 分析与报告")
    strict = [c for c in code_document(doc, entries, "strict") if c.confidence >= 0.6]
    replace_codes(conn, doc.doc_id, "strict", strict)
    summary = summarize(conn)
    check("汇总有编码", summary["n_codes"] > 0)
    check("政策组合已计算", summary["policy_mix"]["avg_tools_per_doc"] > 0)
    check("按年份分组", "2024" in summary["by_year"] or "2023" in summary["by_year"])
    html = render_report(summary, None, title="冒烟测试报告")
    check("报告含 HTML 结构", "<html" in html and "政策工具" in html)
    check("报告含 SVG 图表", "<svg" in html)
    out = tmp / "report.html"
    out.write_text(html, encoding="utf-8")
    check("报告可写入磁盘", out.stat().st_size > 3000, f"{out.stat().st_size} bytes")
    print(f"      报告大小: {out.stat().st_size} bytes")

    print("[6] 真实文本解析")
    sample = ROOT / "data" / "sample" / "人工智能_生成式人工智能服务管理暂行办法.txt"
    if sample.exists():
        title, text = parse_file(sample)
        check("样例文本可解析", len(text) > 3000, f"{len(text)} 字")
        real_doc = Document(doc_id="real", title=title or sample.stem, text=text, date="2023-07-13", domain="人工智能")
        real_codes = code_document(real_doc, entries, "rules")
        check("真实文本可编码", len(real_codes) >= 5, f"{len(real_codes)} 条")
        print(f"      真实文本命中: {', '.join(sorted({c.subcategory for c in real_codes}))}")
    else:
        check("样例文本存在", False, str(sample))

    print()
    print(f"结果: {len(PASS)} 通过, {len(FAIL)} 失败")
    if FAIL:
        print("失败项: " + ", ".join(FAIL))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
