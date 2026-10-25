"""抽样抓取公开政策文本，生成 data/sample 语料。

用途：让仓库开箱即用，不依赖手工下载。只抓公开页面的正文文本。
运行：python scripts/fetch_samples.py --domain all --limit 20
"""

from __future__ import annotations

import argparse
import re
import ssl
import sys
import urllib.request
from pathlib import Path
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "sample"

# 公开政策文本来源（政府门户与部委网站）。可按需增删。
SOURCES = {
    "医疗卫生": [
        ("https://www.gov.cn/zhengce/zhengceku/2022-05/20/content_5691424.htm", "十四五国民健康规划"),
        ("https://www.gov.cn/zhengce/zhengceku/2021-06/04/content_5615473.htm", "关于推动公立医院高质量发展的意见"),
        ("https://www.gov.cn/zhengce/zhengceku/2020-12/31/content_5575804.htm", "关于促进中医药传承创新发展的意见"),
        ("https://www.gov.cn/zhengce/content/2022-02/21/content_5674844.htm", "十四五国家老龄事业发展和养老服务体系规划"),
    ],
    "人工智能": [
        ("https://www.cac.gov.cn/2023-07/13/c_1690898327029107.htm", "生成式人工智能服务管理暂行办法"),
        ("https://www.cac.gov.cn/2022-01/04/c_1642894606364259.htm", "互联网信息服务算法推荐管理规定"),
    ],
}


class TextExtractor(HTMLParser):
    """极简正文抽取：去掉脚本样式，保留段落换行。"""

    SKIP = {"script", "style", "noscript", "nav", "footer", "header", "form"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth:
            return
        data = data.strip()
        if data:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t\u3000\xa0]+", "", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def fetch(url: str, timeout: int = 30) -> str:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        raw = resp.read()
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def extract(html_text: str) -> str:
    parser = TextExtractor()
    parser.feed(html_text)
    return parser.text()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="all", choices=["all", *SOURCES.keys()])
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    domains = list(SOURCES) if args.domain == "all" else [args.domain]
    saved = 0
    for domain in domains:
        for url, name in SOURCES[domain]:
            if saved >= args.limit:
                break
            try:
                body = extract(fetch(url))
            except Exception as exc:
                print(f"  [失败] {name}: {exc}", file=sys.stderr)
                continue
            if len(body) < 200:
                print(f"  [跳过] {name}: 正文过短（可能页面结构变化）", file=sys.stderr)
                continue
            safe = re.sub(r"[\\/:*?\"<>|]", "_", name)[:60]
            target = OUT / f"{domain}_{safe}.txt"
            target.write_text(body, encoding="utf-8")
            print(f"  [保存] {target.name}  {len(body)} 字")
            saved += 1
    print(f"共保存 {saved} 篇到 {OUT}")
    return 0 if saved else 1


if __name__ == "__main__":
    raise SystemExit(main())
