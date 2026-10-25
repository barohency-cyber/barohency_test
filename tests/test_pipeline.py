"""端到端测试：解析 → 编码 → 信度 → 报告。"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pra.analyze.descriptive import summarize  # noqa: E402
from pra.codebook import load_codebook, validate  # noqa: E402
from pra.coder.reliability import (  # noqa: E402
    build_units, compare_coders, krippendorff_alpha_nominal, percent_agreement,
)
from pra.coder.rules import code_document, normalize  # noqa: E402
from pra.report.html import render_report  # noqa: E402
from pra.schema import Document  # noqa: E402
from pra.store import connect, init_db, replace_codes, upsert_document  # noqa: E402


@pytest.fixture()
def codebook():
    return load_codebook()


def make_doc(text: str, doc_id: str = "d1") -> Document:
    return Document(doc_id=doc_id, title="测试政策", text=text, date="2024-01-01", domain="医疗卫生")


def test_codebook_loads(codebook):
    meta, entries = codebook
    assert entries, "编码手册不应为空"
    assert {e.category for e in entries} == {"供给型", "需求型", "环境型"}
    assert validate(entries) == []


def test_rules_detect_supply_instruments(codebook):
    _, entries = codebook
    doc = make_doc("中央财政安排专项资金支持人才培养，并加强关键技术研发和平台建设。")
    codes = code_document(doc, entries)
    subs = {c.subcategory for c in codes}
    assert "资金投入" in subs
    assert "人才培养" in subs
    assert "技术支持" in subs
    assert all(c.method == "rules" for c in codes)


def test_rules_negation_lowers_confidence(codebook):
    _, entries = codebook
    plain = code_document(make_doc("鼓励社会资本参与，设立产业基金。"), entries)
    negated = code_document(make_doc("严禁以设立基金名义变相举债。"), entries)
    plain_conf = max(c.confidence for c in plain)
    neg_conf = max(c.confidence for c in negated) if negated else 0.0
    assert neg_conf < plain_conf


def test_normalize_removes_whitespace():
    assert normalize("财 政\n拨款") == "财政拨款"


def test_reliability_perfect_agreement():
    units = build_units({"a": {("d1", "供给型", "资金投入")}, "b": {("d1", "供给型", "资金投入")}})
    assert percent_agreement(units).value == 1.0
    assert krippendorff_alpha_nominal(units).value == pytest.approx(1.0)


def test_reliability_total_disagreement():
    units = build_units({"a": {("d1", "供给型", "资金投入")}, "b": {("d1", "环境型", "法规管制")}})
    alpha = krippendorff_alpha_nominal(units).value
    assert alpha < 0.2


def test_compare_coders_requires_two():
    with pytest.raises(ValueError):
        compare_coders({"a": {("d1", "供给型", "资金投入")}})


@pytest.fixture()
def workspace_tmp():
    """在仓库内建临时目录：某些受限环境（如 DSH 沙箱）不允许写系统临时目录。"""
    path = ROOT / "data" / "_pytest"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_pipeline_end_to_end(workspace_tmp, codebook):
    _, entries = codebook
    db = workspace_tmp / "test.sqlite3"
    if db.exists():
        db.unlink()
    conn = connect(db)
    init_db(conn)

    docs = [
        make_doc("中央财政安排专项资金，支持人才培养与关键技术研发。", "d1"),
        make_doc("制定管理办法，加强监督管理和执法检查，开展试点示范。", "d2"),
        make_doc("通过政府采购和政府购买服务，扩大服务供给。", "d3"),
    ]
    for d in docs:
        upsert_document(conn, d)
        replace_codes(conn, d.doc_id, "rules", code_document(d, entries, "rules"))

    summary = summarize(conn)
    assert summary["n_documents"] == 3
    assert summary["n_codes"] > 0
    assert summary["categories"]
    assert summary["policy_mix"]["avg_tools_per_doc"] > 0

    html = render_report(summary, None, title="测试报告")
    assert "<html" in html
    assert "测试报告" in html
    assert "政策工具" in html


def test_report_handles_empty():
    summary = {
        "n_codes": 0, "n_documents": 0, "categories": {}, "subcategories": [],
        "by_year": {}, "by_domain": {}, "by_region": {}, "by_level": {},
        "policy_mix": {"n_documents": 0, "avg_tools_per_doc": 0, "min_tools": 0,
                       "max_tools": 0, "top_pairs": []},
        "coverage": {}, "documents": {}, "coder": "x",
    }
    html = render_report(summary, None)
    assert "暂无数据" in html
