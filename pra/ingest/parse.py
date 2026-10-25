"""文件解析：把 PDF / HTML / DOCX / TXT 变成纯文本。"""

from __future__ import annotations

import re
from pathlib import Path

SUPPORTED = {".txt", ".md", ".html", ".htm", ".pdf", ".docx"}


def _clean(text: str) -> str:
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def from_txt(path: Path) -> str:
    for enc in ("utf-8", "gb18030", "utf-16"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_bytes().decode("utf-8", errors="ignore")


def from_html(path: Path) -> tuple[str, str]:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("解析 HTML 需要 beautifulsoup4：pip install '.[ingest]'") from exc
    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    for tag in soup(["script", "style", "noscript", "nav", "footer"]):
        tag.decompose()
    body = soup.find("body") or soup
    return title, body.get_text("\n", strip=True)


def from_pdf(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("解析 PDF 需要 pdfplumber：pip install '.[ingest]'") from exc
    pages = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return "\n".join(pages)


def from_docx(path: Path) -> str:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("解析 DOCX 需要 python-docx：pip install '.[ingest]'") from exc
    d = docx.Document(str(path))
    return "\n".join(p.text for p in d.paragraphs)


def parse_file(path: str | Path) -> tuple[str, str]:
    """返回 (标题, 正文)。"""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(f"不支持的文件类型: {suffix}（支持 {sorted(SUPPORTED)}）")
    if suffix in {".txt", ".md"}:
        return "", _clean(from_txt(path))
    if suffix in {".html", ".htm"}:
        title, body = from_html(path)
        return title, _clean(body)
    if suffix == ".pdf":
        return "", _clean(from_pdf(path))
    return "", _clean(from_docx(path))


def iter_files(root: str | Path, recursive: bool = True) -> list[Path]:
    root = Path(root)
    if root.is_file():
        return [root]
    pattern = "**/*" if recursive else "*"
    return sorted(
        p for p in root.glob(pattern)
        if p.is_file()
        and p.suffix.lower() in SUPPORTED
        and not p.name.lower().startswith(("readme", "_", "."))
    )
