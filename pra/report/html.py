"""HTML 报告导出：单文件、无外部依赖，可直接投稿附录或转 PDF。

刻意不用 matplotlib/plotly：图表用内联 SVG 手绘，
报告在任何机器上打开都一样，也方便截图进论文。
"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

CATEGORY_COLORS = {
    "供给型": "#2f6f9f",
    "需求型": "#c9722f",
    "环境型": "#4d8b62",
}
DEFAULT_COLOR = "#7a7a7a"

CSS = """
:root { --ink:#1c1c1c; --muted:#6b6b6b; --line:#e3e3e3; --bg:#ffffff; }
* { box-sizing: border-box; }
body { margin:0; padding:48px 24px; background:var(--bg); color:var(--ink);
       font-family:"Source Han Sans SC","Noto Sans CJK SC","Microsoft YaHei",system-ui,sans-serif;
       line-height:1.7; font-size:15px; }
.wrap { max-width: 860px; margin: 0 auto; }
h1 { font-size:30px; margin:0 0 6px; letter-spacing:.5px; }
h2 { font-size:19px; margin:44px 0 12px; padding-bottom:6px; border-bottom:2px solid var(--ink); }
h3 { font-size:15px; margin:24px 0 8px; color:var(--muted); font-weight:600; }
.sub { color:var(--muted); font-size:13px; margin-bottom:32px; }
.kpis { display:flex; gap:14px; flex-wrap:wrap; margin:24px 0 8px; }
.kpi { flex:1 1 150px; border:1px solid var(--line); border-radius:8px; padding:14px 16px; }
.kpi b { display:block; font-size:26px; line-height:1.2; }
.kpi span { color:var(--muted); font-size:12px; }
table { width:100%; border-collapse:collapse; margin:12px 0; font-size:13.5px; }
th,td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); }
th { color:var(--muted); font-weight:600; font-size:12.5px; }
td.num { text-align:right; font-variant-numeric: tabular-nums; }
.note { background:#f7f7f5; border-left:3px solid #c9c9c2; padding:12px 16px;
        font-size:13px; color:#444; margin:16px 0; }
.foot { margin-top:56px; padding-top:16px; border-top:1px solid var(--line);
        color:var(--muted); font-size:12px; }
code { background:#f2f2ef; padding:1px 5px; border-radius:3px; font-size:12.5px; }
"""


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def svg_bars(data: list[tuple[str, float]], width: int = 760, bar_height: int = 26, gap: int = 10,
             colors: dict[str, str] | None = None, unit: str = "") -> str:
    """横向条形图（内联 SVG）。"""
    if not data:
        return '<p class="note">暂无数据</p>'
    colors = colors or {}
    label_w = 190
    value_w = 90
    height = len(data) * (bar_height + gap) + 10
    max_v = max(v for _, v in data) or 1
    plot_w = width - label_w - value_w
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
             f'xmlns="http://www.w3.org/2000/svg" font-family="inherit">']
    for i, (label, value) in enumerate(data):
        y = i * (bar_height + gap) + 5
        w = max(2, plot_w * (value / max_v))
        color = colors.get(label, DEFAULT_COLOR)
        parts.append(
            f'<text x="0" y="{y + bar_height * 0.7}" font-size="12.5" fill="#333">{_esc(label)}</text>'
        )
        parts.append(
            f'<rect x="{label_w}" y="{y}" width="{w:.1f}" height="{bar_height}" rx="3" fill="{color}" opacity="0.85"/>'
        )
        parts.append(
            f'<text x="{label_w + w + 8:.1f}" y="{y + bar_height * 0.7}" font-size="12.5" fill="#555">'
            f'{value:g}{_esc(unit)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def svg_grouped_by_year(by_year: dict[str, dict[str, int]], width: int = 760, height: int = 260) -> str:
    """按年份的分组柱状图。"""
    years = [y for y in by_year if y != "未知"]
    if not years:
        return '<p class="note">暂无年份数据</p>'
    years.sort()
    cats = sorted({c for v in by_year.values() for c in v})
    pad_l, pad_b, pad_t = 44, 34, 10
    plot_w = width - pad_l - 12
    plot_h = height - pad_b - pad_t
    max_v = max((by_year[y].get(c, 0) for y in years for c in cats), default=1) or 1
    step = plot_w / max(1, len(years))
    bar_w = min(26, step / (len(cats) + 1))
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" xmlns="http://www.w3.org/2000/svg">']
    for g in range(4):
        y = pad_t + plot_h * g / 3
        val = max_v * (3 - g) / 3
        parts.append(f'<line x1="{pad_l}" y1="{y:.0f}" x2="{width - 8}" y2="{y:.0f}" stroke="#ececec"/>')
        parts.append(f'<text x="0" y="{y + 4:.0f}" font-size="10.5" fill="#888">{val:.0f}</text>')
    for i, year in enumerate(years):
        base_x = pad_l + step * i + step / 2 - (len(cats) * bar_w) / 2
        for j, cat in enumerate(cats):
            v = by_year[year].get(cat, 0)
            h = plot_h * (v / max_v)
            x = base_x + j * bar_w
            parts.append(
                f'<rect x="{x:.1f}" y="{pad_t + plot_h - h:.1f}" width="{bar_w * 0.82:.1f}" height="{h:.1f}" '
                f'fill="{CATEGORY_COLORS.get(cat, DEFAULT_COLOR)}" opacity="0.85" rx="2"/>'
            )
        parts.append(
            f'<text x="{pad_l + step * i + step / 2:.0f}" y="{height - 12}" font-size="11" '
            f'fill="#666" text-anchor="middle">{_esc(year)}</text>'
        )
    legend_x = pad_l
    for k, cat in enumerate(cats):
        parts.append(
            f'<rect x="{legend_x + k * 96}" y="{pad_t - 4}" width="9" height="9" fill="{CATEGORY_COLORS.get(cat, DEFAULT_COLOR)}"/>'
            f'<text x="{legend_x + k * 96 + 14}" y="{pad_t + 5}" font-size="11" fill="#555">{_esc(cat)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _table(headers: list[str], rows: list[list], numeric_cols: set[int] | None = None) -> str:
    numeric_cols = numeric_cols or set()
    out = ["<table><thead><tr>"]
    for h in headers:
        out.append(f"<th>{_esc(h)}</th>")
    out.append("</tr></thead><tbody>")
    for row in rows:
        out.append("<tr>")
        for i, cell in enumerate(row):
            cls = ' class="num"' if i in numeric_cols else ""
            out.append(f"<td{cls}>{_esc(cell)}</td>")
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


METHOD_TEXT = """
<p>本报告由 <code>policy-research-assistant</code> 自动生成。政策文本按
Rothwell &amp; Zegveld（1985）政策工具三分法编码为供给型、需求型与环境型，
下设二级类目。编码方式为<strong>{method}</strong>，编码时间为 {ts}。</p>
<p>建议在论文方法部分报告以下信息：编码手册版本（<code>{cb_version}</code>）、
编码员数量与身份、是否双人独立编码、分歧解决流程、信度指标
（Krippendorff's α 或 Cohen's κ）、以及编码结果的复核比例。</p>
<p><strong>可复现性声明</strong>：本报告对应的数据库文件、编码手册与全部脚本随仓库提供，
执行 <code>pra report</code> 可逐字节复现本报告。</p>
"""


def render_report(summary: dict, reliability: dict | None = None, *, method: str = "规则基线 (keyword-v1)",
                  codebook_version: str = "0.1.0", title: str = "政策工具分析报告") -> str:
    cats = summary["categories"]
    total = sum(cats.values()) or 1
    sub_rows = [[c, s, n, f"{n / total * 100:.1f}%"] for c, s, n in summary["subcategories"]]
    cat_data = [(k, v) for k, v in sorted(cats.items(), key=lambda kv: -kv[1])]
    mix = summary["policy_mix"]

    region_rows = []
    for region, counter in summary["by_region"].items():
        region_rows.append([region] + [counter.get(c, 0) for c in ("供给型", "需求型", "环境型")] + [sum(counter.values())])

    year_table = []
    for year, counter in summary["by_year"].items():
        year_table.append([year] + [counter.get(c, 0) for c in ("供给型", "需求型", "环境型")] + [sum(counter.values())])

    pair_rows = [[p["a"], p["b"], p["count"], f"{p['share'] * 100:.0f}%"] for p in mix["top_pairs"]]

    doc_rows = []
    for doc_id, m in list(summary["documents"].items())[:60]:
        doc_rows.append([m.get("date", ""), m.get("title", "")[:48], m.get("issuer", ""), m.get("level", ""), m.get("region", "")])

    reliability_html = '<p class="note">尚未做双人编码，暂无可报告的信度指标。建议对 20% 样本做双人独立编码后重跑 <code>pra reliability</code>。</p>'
    if reliability:
        m_rows = []
        for metric in reliability["metrics"]:
            if metric["value"] == metric["value"]:
                m_rows.append([metric["metric"], f"{metric['value']:.3f}", metric["n_units"], metric["note"]])
        reliability_html = _table(["指标", "取值", "单元数", "备注"], m_rows) + (
            f'<p class="note">存在 {len(reliability.get("disagreements", []))} 个分歧单元，'
            "建议逐条复核并在论文中说明处理方式。</p>"
        )

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>{_esc(title)}</h1>
<div class="sub">生成时间 {datetime.now().strftime('%Y-%m-%d %H:%M')} · policy-research-assistant · 编码方式：{_esc(method)}</div>

<div class="kpis">
  <div class="kpi"><b>{summary['n_documents']}</b><span>已编码政策文本</span></div>
  <div class="kpi"><b>{summary['n_codes']}</b><span>编码条目</span></div>
  <div class="kpi"><b>{mix['avg_tools_per_doc']}</b><span>篇均政策工具数</span></div>
  <div class="kpi"><b>{len(cats)}</b><span>一级类目</span></div>
</div>

<h2>一、政策工具总体分布</h2>
{svg_bars(cat_data, colors=CATEGORY_COLORS)}
{_table(["一级类目", "编码数", "占比"], [[k, v, f"{v / total * 100:.1f}%"] for k, v in cat_data], {1, 2})}

<h3>二级类目明细</h3>
{_table(["一级类目", "二级类目", "编码数", "占比"], sub_rows, {2, 3})}

<h2>二、时间趋势</h2>
{svg_grouped_by_year(summary["by_year"])}
{_table(["年份", "供给型", "需求型", "环境型", "合计"], year_table, {1, 2, 3, 4})}

<h2>三、地区与层级差异</h2>
{_table(["地区", "供给型", "需求型", "环境型", "合计"], region_rows, {1, 2, 3, 4})}

<h2>四、政策组合（Policy Mix）</h2>
<p>篇均使用 <strong>{mix['avg_tools_per_doc']}</strong> 类政策工具（最少 {mix['min_tools']} 类，最多 {mix['max_tools']} 类）。
下表为共现频次最高的工具对，可用于讨论政策工具之间的互补或替代关系。</p>
{_table(["工具 A", "工具 B", "共现文档数", "占比"], pair_rows, {2, 3})}

<h2>五、编码信度</h2>
{reliability_html}

<h2>六、方法学附录（可直接改写进论文）</h2>
{METHOD_TEXT.format(method=_esc(method), ts=datetime.now().strftime("%Y-%m-%d"), cb_version=_esc(codebook_version))}

<h2>七、样本清单</h2>
{_table(["发文日期", "标题", "发文机关", "效力层级", "地区"], doc_rows)}

<div class="foot">
本报告由 policy-research-assistant 生成 · 数据库与编码手册随仓库提供 · 数据仅含公开政策文本
</div>
</div></body></html>"""


def write_report(summary: dict, reliability: dict | None, out: str | Path, **kwargs) -> Path:
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(summary, reliability, **kwargs), encoding="utf-8")
    return path
