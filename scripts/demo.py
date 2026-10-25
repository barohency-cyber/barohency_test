"""一键演示：导入示例语料 → 规则编码 → 二次编码（模拟第二编码员）→ 信度 → 报告。

运行：
    python scripts/demo.py

产物：
    exports/demo_report.html
    exports/demo_reliability.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pra.analyze.descriptive import summarize  # noqa: E402
from pra.cli import infer_domain  # noqa: E402
from pra.codebook import load_codebook  # noqa: E402
from pra.coder import code_document  # noqa: E402
from pra.coder.reliability import compare_coders, units_from_rows, universe_from_docs  # noqa: E402
from pra.ingest import iter_files, parse_file  # noqa: E402
from pra.ingest import meta as meta_mod  # noqa: E402
from pra.report.html import write_report  # noqa: E402
from pra.schema import Document  # noqa: E402
from pra.store import connect, get_codes, init_db, replace_codes, stats, upsert_document  # noqa: E402


def main() -> int:
    db = ROOT / "data" / "demo.sqlite3"
    if db.exists():
        db.unlink()
    conn = connect(db)
    init_db(conn)
    _, entries = load_codebook()

    files = iter_files(ROOT / "data" / "sample")
    if not files:
        print("data/sample 为空。先运行 python scripts/fetch_samples.py，或放入自己的政策文件。")
        return 1

    print(f"1/4 导入 {len(files)} 个文件")
    for f in files:
        title, text = parse_file(f)
        if len(text) < 50:
            continue
        doc = Document(
            doc_id=Document.make_id(text[:2000] + f.name),
            title=title or meta_mod.extract_title(text, fallback=f.stem),
            text=text,
            path=str(f),
            issuer=meta_mod.extract_issuer(text, title),
            doc_number=meta_mod.extract_doc_number(text),
            date=meta_mod.extract_date(text),
            level=meta_mod.extract_level(text, title),
            region=meta_mod.extract_region(text),
            domain=infer_domain(str(f), title, text[:800]),
        )
        upsert_document(conn, doc)
        print(f"   {doc.title[:44]:<46} {doc.date or '日期未知'}  {doc.issuer[:16]}")

    print("2/4 编码员 A（规则基线）")
    for row in conn.execute("SELECT doc_id, title FROM documents").fetchall():
        doc = Document(
            doc_id=row["doc_id"],
            title=row["title"],
            text=conn.execute("SELECT text FROM documents WHERE doc_id=?", (row["doc_id"],)).fetchone()[0],
        )
        codes = code_document(doc, entries, coder="rules")
        replace_codes(conn, doc.doc_id, "rules", codes)
        print(f"   {doc.title[:40]:<42} {len(codes):>3} 条")

    print("3/4 编码员 B（规则基线，剔除每篇置信度最低的一条，模拟编码员分歧）")
    for row in conn.execute("SELECT doc_id, title FROM documents").fetchall():
        doc = Document(
            doc_id=row["doc_id"],
            title=row["title"],
            text=conn.execute("SELECT text FROM documents WHERE doc_id=?", (row["doc_id"],)).fetchone()[0],
        )
        codes_b = sorted(code_document(doc, entries, coder="coder_b"), key=lambda c: c.confidence)
        if len(codes_b) > 1:
            codes_b = codes_b[1:]
        replace_codes(conn, doc.doc_id, "coder_b", codes_b)

    rows = conn.execute("SELECT doc_id, category, subcategory, coder FROM codes").fetchall()
    doc_ids = [r[0] for r in conn.execute("SELECT doc_id FROM documents")]
    result = compare_coders(
        {c: units_from_rows(rows, c) for c in ("rules", "coder_b")},
        universe_from_docs(doc_ids, entries),
    )
    exports = ROOT / "exports"
    exports.mkdir(exist_ok=True)
    (exports / "demo_reliability.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for m in result["metrics"]:
        if m["value"] == m["value"]:
            print(f"   {m['metric']}: {m['value']:.3f}")

    print("4/4 生成报告")
    summary = summarize(conn, coder=None)
    meta_, _ = load_codebook()
    out = write_report(
        summary, result, exports / "demo_report.html",
        method="规则基线 (keyword-v1) + 双编码员一致性检验",
        codebook_version=str(meta_.get("version", "0.1.0")),
        title="政策工具分析报告（示例）",
    )
    print(f"   报告: {out}")
    print(f"   统计: {json.dumps(stats(conn), ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
