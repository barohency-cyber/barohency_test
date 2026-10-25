"""公共政策研究助手 · Streamlit 界面

启动：
    pra serve
    # 或
    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pra.analyze.descriptive import summarize  # noqa: E402
from pra.codebook import load_codebook, validate  # noqa: E402
from pra.coder import code_document, code_document_llm, available as llm_available  # noqa: E402
from pra.coder.reliability import compare_coders, units_from_rows, universe_from_docs  # noqa: E402
from pra.ingest import parse_file  # noqa: E402
from pra.ingest import meta as meta_mod  # noqa: E402
from pra.report.html import render_report  # noqa: E402
from pra.schema import Code, Document  # noqa: E402
from pra.store import (  # noqa: E402
    DEFAULT_DB, coders, connect, get_codes, get_document, init_db, list_documents,
    replace_codes, stats, upsert_document,
)

st.set_page_config(page_title="公共政策研究助手", page_icon="📑", layout="wide")

CATEGORY_COLORS = {"供给型": "#2f6f9f", "需求型": "#c9722f", "环境型": "#4d8b62"}


@st.cache_resource
def get_conn(db_path: str):
    conn = connect(db_path)
    init_db(conn)
    return conn


def doc_from_row(conn, doc_id: str) -> Document:
    r = get_document(conn, doc_id)
    return Document(
        doc_id=r["doc_id"], title=r["title"], text=r["text"], path=r["path"] or "",
        issuer=r["issuer"] or "", doc_number=r["doc_number"] or "", date=r["date"] or "",
        level=r["level"] or "", region=r["region"] or "", domain=r["domain"] or "",
        url=r["url"] or "",
    )


def page_overview(conn) -> None:
    s = stats(conn)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("政策文本", s["documents"])
    c2.metric("已编码文本", s["coded_documents"])
    c3.metric("编码条目", s["codes"])
    c4.metric("编码员", len(coders(conn)) or 1)

    rows = list_documents(conn)
    if not rows:
        st.info("还没有语料。到「导入」页添加政策文件，或运行 `pra import data/sample`。")
        return

    st.subheader("语料清单")
    st.dataframe(
        [dict(r) for r in rows],
        use_container_width=True,
        hide_index=True,
        column_config={
            "doc_id": st.column_config.TextColumn("ID", width="small"),
            "title": st.column_config.TextColumn("标题", width="large"),
            "n_chars": st.column_config.NumberColumn("字数", width="small"),
        },
    )

    summary = summarize(conn)
    if summary["n_codes"]:
        st.subheader("政策工具分布")
        cats = summary["categories"]
        st.bar_chart(cats, color="#2f6f9f", height=260)


def page_import(conn) -> None:
    st.subheader("导入政策文本")
    st.caption("支持 PDF / HTML / DOCX / TXT / MD。元数据（机关、文号、日期）自动抽取，可在导入后修正。")

    tab_dir, tab_upload = st.tabs(["从目录导入", "上传文件"])
    with tab_dir:
        path = st.text_input("目录或文件路径", value="data/sample")
        domain = st.text_input("政策领域（留空自动推断）", value="")
        if st.button("扫描并导入", type="primary"):
            from pra.ingest import iter_files

            files = iter_files(ROOT / path) if not Path(path).is_absolute() else iter_files(path)
            if not files:
                st.warning("没有找到可解析的文件")
                return
            added, skipped = 0, []
            progress = st.progress(0.0)
            for i, f in enumerate(files):
                try:
                    title, text = parse_file(f)
                    if len(text) < 50:
                        skipped.append((f.name, "正文过短"))
                        continue
                    doc_id = Document.make_id(text[:2000] + f.name)
                    title = title or meta_mod.extract_title(text, fallback=f.stem)
                    doc = Document(
                        doc_id=doc_id, title=title, text=text, path=str(f),
                        issuer=meta_mod.extract_issuer(text, title),
                        doc_number=meta_mod.extract_doc_number(text),
                        date=meta_mod.extract_date(text),
                        level=meta_mod.extract_level(text, title),
                        region=meta_mod.extract_region(text),
                        domain=domain,
                    )
                    if not doc.domain:
                        from pra.cli import infer_domain

                        doc.domain = infer_domain(str(f), title, text[:800])
                    upsert_document(conn, doc)
                    added += 1
                except Exception as exc:
                    skipped.append((f.name, str(exc)))
                progress.progress((i + 1) / len(files))
            st.success(f"导入 {added} 篇" + (f"，跳过 {len(skipped)} 个" if skipped else ""))
            for name, why in skipped[:8]:
                st.caption(f"跳过 {name}: {why}")
            st.rerun()

    with tab_upload:
        uploads = st.file_uploader("选择文件", accept_multiple_files=True,
                                   type=["pdf", "html", "htm", "docx", "txt", "md"])
        if uploads and st.button("导入上传的文件", type="primary"):
            corpus = ROOT / "data" / "corpus"
            corpus.mkdir(parents=True, exist_ok=True)
            added = 0
            for up in uploads:
                target = corpus / up.name
                target.write_bytes(up.getbuffer())
                try:
                    title, text = parse_file(target)
                except Exception as exc:
                    st.error(f"{up.name}: {exc}")
                    continue
                doc_id = Document.make_id(text[:2000] + up.name)
                doc = Document(
                    doc_id=doc_id, title=title or meta_mod.extract_title(text, fallback=up.name),
                    text=text, path=str(target),
                    issuer=meta_mod.extract_issuer(text, title),
                    doc_number=meta_mod.extract_doc_number(text),
                    date=meta_mod.extract_date(text),
                    level=meta_mod.extract_level(text, title),
                    region=meta_mod.extract_region(text),
                )
                upsert_document(conn, doc)
                added += 1
            st.success(f"导入 {added} 篇")
            st.rerun()


def page_code(conn) -> None:
    st.subheader("政策工具编码")
    docs = list_documents(conn)
    if not docs:
        st.info("先导入语料。")
        return

    col1, col2 = st.columns(2)
    coder = col1.text_input("编码员标识（写入 provenance）", value="rules")
    method = col2.selectbox(
        "编码方法",
        ["rules", "llm"],
        help="规则基线无需联网、完全可复现；LLM 需要 API key。",
    )
    if method == "llm" and not llm_available():
        st.warning("未配置 PRA_LLM_API_KEY，将自动回退到规则基线。")

    target = st.selectbox("范围", ["全部未编码", "全部文档"] + [f"{d['title'][:40]}" for d in docs])
    if st.button("开始编码", type="primary"):
        _, entries = load_codebook()
        problems = validate(entries)
        if problems:
            st.warning("编码手册存在问题：" + "；".join(problems[:5]))

        selected = docs
        if target.startswith("全部未编码"):
            coded = {r[0] for r in conn.execute("SELECT DISTINCT doc_id FROM codes")}
            selected = [d for d in docs if d["doc_id"] not in coded]
        elif target not in ("全部文档", "全部未编码"):
            selected = [d for d in docs if f"{d['title'][:40]}" == target]

        progress = st.progress(0.0)
        total = 0
        for i, row in enumerate(selected):
            doc = doc_from_row(conn, row["doc_id"])
            try:
                use_llm = method == "llm" and llm_available()
                codes = (
                    code_document_llm(doc, entries, coder=coder)
                    if use_llm
                    else code_document(doc, entries, coder=coder)
                )
                total += replace_codes(conn, doc.doc_id, coder, codes)
            except Exception as exc:
                st.error(f"{doc.title[:30]}: {exc}")
            progress.progress((i + 1) / max(1, len(selected)))
        st.success(f"完成：{len(selected)} 篇，{total} 条编码")
        st.rerun()


def page_review(conn) -> None:
    st.subheader("人工复核")
    docs = list_documents(conn)
    if not docs:
        st.info("先导入语料并编码。")
        return

    options = {f"{d['title'][:50]}": d["doc_id"] for d in docs}
    label = st.selectbox("选择文档", list(options.keys()))
    doc_id = options[label]
    doc = doc_from_row(conn, doc_id)

    with st.expander("查看原文", expanded=False):
        st.text_area("正文", doc.text, height=260, disabled=True, label_visibility="collapsed")

    machine_codes = get_codes(conn, doc_id=doc_id, coder="rules")
    if not machine_codes:
        machine_codes = get_codes(conn, doc_id=doc_id)
    if not machine_codes:
        st.info("这篇还没有编码结果，先去「编码」页跑一次。")
        return

    st.caption("勾选保留的编码；取消勾选即视为人工判定「误报」。保存后以 coder=human 写入，用于信度计算。")
    keep: dict[int, bool] = {}
    for row in machine_codes:
        with st.container(border=True):
            c1, c2 = st.columns([1, 4])
            keep[row["id"]] = c1.checkbox("保留", value=True, key=f"keep_{row['id']}")
            c2.markdown(
                f"**{row['category']} / {row['subcategory']}**  ·  置信度 {row['confidence']:.2f}  \n"
                f"证据：{row['evidence'] or '（无）'}"
            )

    if st.button("保存复核结果", type="primary"):
        _, entries = load_codebook()
        valid = {(e.category, e.subcategory) for e in entries}
        kept: list[Code] = []
        for row in machine_codes:
            if not keep.get(row["id"]):
                continue
            if (row["category"], row["subcategory"]) not in valid:
                continue
            kept.append(
                Code(
                    doc_id=doc_id, category=row["category"], subcategory=row["subcategory"],
                    evidence=row["evidence"] or "", method="human", model="",
                    confidence=1.0, coder="human", note=f"复核自 {row['coder']}",
                )
            )
        n = replace_codes(conn, doc_id, "human", kept)
        st.success(f"已保存 {n} 条人工编码")
        st.rerun()


def page_reliability(conn) -> None:
    st.subheader("编码信度")
    names = coders(conn)
    if len(names) < 2:
        st.info("需要至少两名编码员的结果。做法：换一个 `--coder` 再跑一次编码（可用不同方法），或做人工复核生成 `human`。")
        st.caption(f"当前编码员：{', '.join(names) or '无'}")
        return

    c1, c2 = st.columns(2)
    a = c1.selectbox("编码员 A", names, index=0)
    b = c2.selectbox("编码员 B", names, index=1)
    if a == b:
        st.warning("请选择两个不同的编码员")
        return

    rows = conn.execute("SELECT doc_id, category, subcategory, coder FROM codes").fetchall()
    _, entries = load_codebook()
    doc_ids = [r[0] for r in conn.execute("SELECT doc_id FROM documents")]
    result = compare_coders(
        {a: units_from_rows(rows, a), b: units_from_rows(rows, b)},
        universe_from_docs(doc_ids, entries),
    )

    cols = st.columns(len(result["metrics"]))
    for col, metric in zip(cols, result["metrics"]):
        val = metric["value"]
        col.metric(metric["metric"], "—" if val != val else f"{val:.3f}")

    st.caption("Krippendorff's α ≥ 0.80 通常视为可靠；0.67–0.80 仅可用于探索性结论。")

    if result["disagreements"]:
        st.subheader(f"分歧单元（{len(result['disagreements'])}）")
        st.dataframe(result["disagreements"], use_container_width=True, hide_index=True)


def page_export(conn) -> None:
    st.subheader("导出")
    title = st.text_input("报告标题", value="政策工具分析报告")
    method_label = st.text_input("方法说明", value="规则基线 (keyword-v1)")
    if st.button("生成 HTML 报告", type="primary"):
        summary = summarize(conn)
        if not summary["n_codes"]:
            st.error("还没有编码结果")
            return
        names = coders(conn)
        reliability = None
        meta, entries = load_codebook()
        if len(names) >= 2:
            rows = conn.execute("SELECT doc_id, category, subcategory, coder FROM codes").fetchall()
            doc_ids = [r[0] for r in conn.execute("SELECT doc_id FROM documents")]
            reliability = compare_coders(
                {n: units_from_rows(rows, n) for n in names[:2]},
                universe_from_docs(doc_ids, entries),
            )
        html = render_report(
            summary, reliability, method=method_label,
            codebook_version=str(meta.get("version", "0.1.0")), title=title,
        )
        st.download_button("下载报告 HTML", html, file_name="report.html", mime="text/html")
        st.success("报告已生成，点击上方按钮下载（可直接打印为 PDF）。")


def main() -> None:
    st.sidebar.title("📑 公共政策研究助手")
    st.sidebar.caption("政策文本 → 可发表的分析结果")
    db = st.sidebar.text_input("数据库", value=str(DEFAULT_DB))
    conn = get_conn(db)

    meta, entries = load_codebook()
    st.sidebar.markdown(
        f"**编码手册** v{meta.get('version', '?')}  \n"
        f"{meta.get('framework', '')}  \n"
        f"类目数：{len(entries)}"
    )
    if st.sidebar.button("校验手册"):
        problems = validate(entries)
        if problems:
            st.sidebar.warning("；".join(problems[:6]))
        else:
            st.sidebar.success("手册校验通过")
    st.sidebar.divider()
    st.sidebar.caption("数据与编码全部保存在本地 SQLite，不上传任何内容。")

    tabs = st.tabs(["概览", "导入", "编码", "复核", "信度", "导出"])
    with tabs[0]:
        page_overview(conn)
    with tabs[1]:
        page_import(conn)
    with tabs[2]:
        page_code(conn)
    with tabs[3]:
        page_review(conn)
    with tabs[4]:
        page_reliability(conn)
    with tabs[5]:
        page_export(conn)


if __name__ == "__main__":
    main()
