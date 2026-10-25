"""LLM 辅助编码（可选）。

设计原则：
  - 默认不启用：没有 API key 时整个工具链仍可运行（规则基线兜底）
  - 输出必须结构化，且记录 model / prompt 版本，便于写方法学附录
  - 一次一篇文档，返回 JSON 数组，禁止自由发挥
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass

from ..schema import Code, CodebookEntry, Document, now_iso

DEFAULT_BASE_URL = os.environ.get("PRA_LLM_BASE_URL", "https://api.deepseek.com/chat/completions")
DEFAULT_MODEL = os.environ.get("PRA_LLM_MODEL", "deepseek-chat")
API_KEY_ENV = ("PRA_LLM_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")

SYSTEM_PROMPT = """你是公共政策文本编码员。你只做一件事：根据给定的政策工具编码手册，
判断一段政策文本中出现了哪些政策工具。

要求：
1. 只使用手册中列出的二级类目，不得自创类目。
2. 对每个类目，从原文中摘录一段能支撑判断的原文片段（不超过60字）。
3. 输出严格的 JSON 数组，不要输出任何解释性文字。
4. 格式：[{"category":"供给型","subcategory":"资金投入","evidence":"原文片段","confidence":0.0-1.0}]
5. 若某类目没有把握，不要输出。"""


def api_key() -> str:
    for name in API_KEY_ENV:
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def available() -> bool:
    return bool(api_key())


def _build_user_prompt(doc: Document, entries: list[CodebookEntry], max_chars: int) -> str:
    lines = ["【编码手册】"]
    for e in entries:
        lines.append(f"- {e.category} / {e.subcategory}：{e.definition}")
    lines.append("")
    lines.append("【待编码文本】")
    lines.append(doc.text[:max_chars])
    return "\n".join(lines)


@dataclass
class LLMConfig:
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    temperature: float = 0.0
    max_chars: int = 6000
    timeout: int = 90


def code_document_llm(
    doc: Document,
    entries: list[CodebookEntry],
    coder: str = "llm",
    config: LLMConfig | None = None,
) -> list[Code]:
    cfg = config or LLMConfig()
    key = api_key()
    if not key:
        raise RuntimeError(
            "未检测到 API key。请设置 PRA_LLM_API_KEY（或 DEEPSEEK_API_KEY），"
            "或改用规则基线：pra code --method rules"
        )

    payload = {
        "model": cfg.model,
        "temperature": cfg.temperature,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(doc, entries, cfg.max_chars)},
        ],
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        cfg.base_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=cfg.timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    content = body["choices"][0]["message"]["content"]
    items = _parse_items(content)

    valid = {(e.category, e.subcategory) for e in entries}
    codes: list[Code] = []
    for item in items:
        cat = str(item.get("category", "")).strip()
        sub = str(item.get("subcategory", "")).strip()
        if (cat, sub) not in valid:
            continue
        codes.append(
            Code(
                doc_id=doc.doc_id,
                category=cat,
                subcategory=sub,
                evidence=str(item.get("evidence", ""))[:200],
                method="llm",
                model=cfg.model,
                confidence=float(item.get("confidence", 0.7) or 0.7),
                coder=coder,
                note=f"temperature={cfg.temperature}; prompt=v1",
                created_at=now_iso(),
            )
        )
    return codes


def _parse_items(content: str) -> list[dict]:
    content = content.strip()
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            for key in ("items", "codes", "results", "data"):
                if isinstance(parsed.get(key), list):
                    return parsed[key]
            return []
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        start, end = content.find("["), content.rfind("]")
        if 0 <= start < end:
            try:
                return json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                return []
        return []
