"""命令行入口：pra import / code / reliability / report / serve / info"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .analyze.descriptive import summarize
from .codebook import load_codebook, validate
from .coder import code_document, code_document_llm, available as llm_available
from .coder.reliability import compare_coders, units_from_rows, universe_from_docs
from .ingest import iter_files, parse_file
from .ingest import meta as meta_mod
from .report.html import write_report
from .schema import Document
from .store import DEFAULT_DB, coders, connect, get_document, init_db, list_documents, log_run, replace_codes, stats, upsert_document

DOMAIN_KEYWORDS = {
    "医疗卫生": ["医疗", "卫生", "健康", "医院", "医保", "药品", "疾病", "公共卫生"],
    "人工智能": ["人工智能", "智能", "算法", "大模型", "算力", "数据要素", "数字化", "机器人"],
    "养老服务": ["养老", "老龄", "老年", "照护"],
    "生态环保": ["生态", "环境", "污染", "碳", "绿色"],
}


def infer_domain(*parts: str) -> str:
    text = " ".join(p for p in parts if p)
    scores = {d: sum(k in text for k in kws) for d, kws in DOMAIN_KEYWORDS.items()}
    best = max(scores, key=scores.get) if scores else ""
    return best if scores.get(best, 0) > 0 else ""


def cmd_import(args) -> int:
    conn = connect(args.db)
    init_db(conn)
    files = iter_files(args.path, recursive=not args.no_recursive)
    if not files:
        print(f"没有找到可解析的文件: {args.path}")
        return 1
    added = 0
    for f in files:
        try:
            title, text = parse_file(f)
        except Exception as exc:
            print(f"  [跳过] {f.name}: {exc}")
            continue
        if len(text) < 50:
            print(f"  [跳过] {f.name}: 正文过短 ({len(text)} 字符)")
            continue
        doc_id = Document.make_id(text[:2000] + str(f.name))
        title = title or meta_mod.extract_title(text, fallback=f.stem)
        doc = Document(
            doc_id=doc_id,
            title=title,
            text=text,
            path=str(f),
            issuer=args.issuer or meta_mod.extract_issuer(text, title),
            doc_number=meta_mod.extract_doc_number(text),
            date=args.date or meta_mod.extract_date(text),
            level=args.level or meta_mod.extract_level(text, title),
            region=args.region or meta_mod.extract_region(text),
            domain=args.domain or infer_domain(str(f), title, text[:800]),
            url="",
        )
        upsert_document(conn, doc)
        added += 1
    print(f"导入完成：{added} 篇（数据库 {args.db}）")
    print(json.dumps(stats(conn), ensure_ascii=False))
    return 0


def _documents(conn, doc_id: str | None) -> list[Document]:
    rows = list_documents(conn)
    docs = []
    for row in rows:
        if doc_id and row["doc_id"] != doc_id:
            continue
        full = get_document(conn, row["doc_id"])
        docs.append(
            Document(
                doc_id=full["doc_id"], title=full["title"], text=full["text"], path=full["path"] or "",
                issuer=full["issuer"] or "", doc_number=full["doc_number"] or "", date=full["date"] or "",
                level=full["level"] or "", region=full["region"] or "", domain=full["domain"] or "",
                url=full["url"] or "",
            )
        )
    return docs


def cmd_code(args) -> int:
    conn = connect(args.db)
    init_db(conn)
    _, entries = load_codebook(args.codebook)
    problems = validate(entries)
    if problems:
        print("编码手册存在以下问题（建议修复）：")
        for p in problems:
            print("  -", p)
    docs = _documents(conn, args.doc)
    if not docs:
        print("数据库中没有文档，先运行 pra import <目录>")
        return 1

    method = args.method
    if method == "llm" and not llm_available():
        print("未检测到 API key，回退到规则基线。设置 PRA_LLM_API_KEY 可启用 LLM 编码。")
        method = "rules"

    total = 0
    for doc in docs:
        try:
            if method == "llm":
                codes = code_document_llm(doc, entries, coder=args.coder)
            else:
                codes = code_document(doc, entries, coder=args.coder)
        except Exception as exc:
            print(f"  [失败] {doc.title[:30]}: {exc}")
            continue
        n = replace_codes(conn, doc.doc_id, args.coder, codes)
        if hasattr(sys.stdout, "reconfigure"):
            pass
        print(f"  {doc.title[:40]:<42} {n:>3} 条")
        total += n
    log_run(conn, coder=args.coder, method=method, model="keyword-v1" if method == "rules" else "llm")
    print(f"编码完成：{len(docs)} 篇，共 {total} 条（coder={args.coder}, method={method}）")
    return 0


def cmd_reliability(args) -> int:
    conn = connect(args.db)
    init_db(conn)
    rows = conn.execute("SELECT doc_id, category, subcategory, coder FROM codes").fetchall()
    names = coders(conn)
    if len(names) < 2:
        print(f"当前只有一个编码员（{names or '无'}），无法计算信度。")
        print("提示：用 --coder 参数区分两次编码，例如：")
        print("  pra code --coder alice")
        print("  pra code --coder bob --method llm")
        return 1
    a = args.coder_a or names[0]
    b = args.coder_b or names[1]
    coded = {a: units_from_rows(rows, a), b: units_from_rows(rows, b)}
    _, entries = load_codebook(args.codebook)
    doc_ids = [r[0] for r in conn.execute("SELECT doc_id FROM documents")]
    result = compare_coders(coded, universe_from_docs(doc_ids, entries))
    print(json.dumps({k: v for k, v in result.items() if k != "disagreements"}, ensure_ascii=False, indent=2))
    print(f"分歧单元: {len(result['disagreements'])} 个")
    if args.export:
        out = Path(args.export)
        out.parent.mkdir(parents=True, exist_ok=True)
        import csv

        with out.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=["doc_id", "category", "subcategory", "values"])
            writer.writeheader()
            for d in result["disagreements"]:
                writer.writerow({**d, "values": "|".join(d["values"])})
        print(f"分歧明细已导出: {out}")
    return 0


def cmd_report(args) -> int:
    conn = connect(args.db)
    init_db(conn)
    summary = summarize(conn, coder=args.coder)
    if not summary["n_codes"]:
        print("没有编码结果，先运行 pra code")
        return 1
    meta, entries = load_codebook(args.codebook)
    reliability = None
    names = coders(conn)
    if len(names) >= 2:
        rows = conn.execute("SELECT doc_id, category, subcategory, coder FROM codes").fetchall()
        doc_ids = [r[0] for r in conn.execute("SELECT doc_id FROM documents")]
        reliability = compare_coders(
            {n: units_from_rows(rows, n) for n in names[:2]},
            universe_from_docs(doc_ids, entries),
        )
    out = write_report(
        summary, reliability, args.out,
        method=args.method_label, codebook_version=str(meta.get("version", "0.1.0")),
        title=args.title,
    )
    print(f"报告已生成: {out}")
    return 0


def cmd_serve(args) -> int:
    app_path = Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py"
    try:
        import streamlit.web.cli as stcli
    except ImportError:
        print("未安装 streamlit：pip install '.[ui]'")
        return 1
    sys.argv = ["streamlit", "run", str(app_path), "--server.port", str(args.port)]
    return stcli.main()


def cmd_info(args) -> int:
    print(f"policy-research-assistant v{__version__}")
    meta, entries = load_codebook(args.codebook)
    print(f"编码手册: {meta.get('framework', '')} (v{meta.get('version')})")
    print(f"类目数: {len(entries)}")
    for cat in {e.category for e in entries}:
        subs = [e.subcategory for e in entries if e.category == cat]
        print(f"  {cat}: {len(subs)} 个二级类目 → {', '.join(subs)}")
    problems = validate(entries)
    print("手册校验:", "通过" if not problems else f"{len(problems)} 个问题")
    for p in problems:
        print("  -", p)
    conn = connect(args.db)
    init_db(conn)
    print("数据库:", json.dumps(stats(conn), ensure_ascii=False))
    print("LLM:", "可用" if llm_available() else "不可用（仅规则基线）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pra", description="公共政策研究助手：从政策文本到可发表的分析结果")
    p.add_argument("--db", default=str(DEFAULT_DB), help=f"SQLite 路径（默认 {DEFAULT_DB}）")
    p.add_argument("--codebook", default=None, help="自定义编码手册 YAML")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("import", help="导入并解析政策文件")
    s.add_argument("path")
    s.add_argument("--domain", default="")
    s.add_argument("--issuer", default="")
    s.add_argument("--date", default="")
    s.add_argument("--level", default="")
    s.add_argument("--region", default="")
    s.add_argument("--no-recursive", action="store_true")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("code", help="按编码手册编码")
    s.add_argument("--method", choices=["rules", "llm"], default="rules")
    s.add_argument("--coder", default="rules")
    s.add_argument("--doc", default=None, help="只编码指定 doc_id")
    s.set_defaults(func=cmd_code)

    s = sub.add_parser("reliability", help="计算编码信度")
    s.add_argument("--coder-a", default=None)
    s.add_argument("--coder-b", default=None)
    s.add_argument("--export", default="", help="分歧明细 CSV 输出路径")
    s.set_defaults(func=cmd_reliability)

    s = sub.add_parser("report", help="导出 HTML 报告")
    s.add_argument("-o", "--out", default="exports/report.html")
    s.add_argument("--coder", default=None)
    s.add_argument("--title", default="政策工具分析报告")
    s.add_argument("--method-label", default="规则基线 (keyword-v1)")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("serve", help="启动 Streamlit 界面")
    s.add_argument("--port", type=int, default=8501)
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("info", help="查看配置与统计")
    s.set_defaults(func=cmd_info)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
