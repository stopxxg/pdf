"""Multi-provider LLM client for PDF proofreading.

Supports OpenAI-compatible APIs: Claude, DeepSeek, Doubao, Kimi, OpenAI.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AIReviewResult:
    issues: list[dict[str, Any]]
    raw: str


@dataclass
class ModelConfig:
    provider: str
    model_name: str
    base_url: str
    api_key: str
    temperature: float = 0.7
    top_p: float = 1.0
    max_tokens: int = 4096
    timeout: int = 120
    stream: bool = False
    enable_prompt_cache: bool = False


def _resolve_api_key(provider: str) -> str:
    env_map = {
        "claude": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "doubao": "ARK_API_KEY",
        "kimi": "KIMI_API_KEY",
    }
    key = env_map.get(provider, "").upper()
    val = os.environ.get(key, "").strip()
    if not val and provider == "kimi":
        val = os.environ.get("MOONSHOT_API_KEY", "").strip()
    if not val:
        raise RuntimeError(f"请在 .env 中设置 {key}")
    return val


def _resolve_base_url(provider: str, override: str = "") -> str:
    if override.strip():
        return override.strip()
    defaults = {
        "claude": "https://api.anthropic.com/v1",
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "doubao": "https://ark.cn-beijing.volces.com/api/v3",
        "kimi": "https://api.moonshot.cn/v1",
    }
    return defaults.get(provider, "")


def _resolve_model_name(provider: str, override: str = "") -> str:
    if override.strip():
        return override.strip()
    defaults = {
        "claude": "claude-sonnet-4-6",
        "openai": "gpt-4o",
        "deepseek": "deepseek-chat",
        "doubao": "doubao-lite-4k",
        "kimi": "moonshot-v1-8k",
    }
    return defaults.get(provider, "")


def _load_prompt(path: Path | None = None) -> str:
    if path is None:
        path = Path(__file__).resolve().parent.parent.parent / "prompt.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("full_doc_prompt", ""))
    return ""


DEFAULT_PROMPT = """你是专业的科技期刊学术编辑，擅长大农业、水土保持、生态水文、土壤侵蚀、土地利用、农田水利等学科论文校对。

【关键规则：页码必须严格正确】
- 你在输出的每一条问题里，必须填写正确的 page（整数，从 1 开始）。
- page 的判定依据只能是：该问题对应原文所在段落前最近出现的 [[PAGE=N]] 标记。
- 禁止输出 page=0、空字符串、或凭感觉猜测页码。

【你的任务】
对整篇学术论文进行全局规范性检查，重点包括：
1) 专业术语统一、规范、前后一致
2) 单位格式统一，符合科技期刊标准
3) 图表编号、公式编号、引用编号前后统一
4) 章节结构、逻辑层次、学术表达规范
5) 水土保持相关名词、方法、指标规范准确
6) 标点符号规范（无全角冒号在URL中，无0. 05等多余空格）
7) 统计符号规范（p/P/z/q/I 等应为斜体，与文字间无空格）
8) 参考文献格式（et al. 后加句点，卷期号完整，≤30条）

【输出格式】
输出必须是严格 JSON 数组，只能输出 JSON，不要输出任何解释/说明/Markdown。
每个对象字段：
- page: 整数页码
- paragraph: 段落标题/首句（可选，可为空）
- original: 原文片段（10~60字，连续原文）
- error: 错误描述
- fix: 推荐修改（可为空）
- comment: 批注内容（1~3行）

如果未发现问题，返回 []。
"""


def _extract_json(raw: str) -> list[dict[str, Any]]:
    """Extract JSON array from model response."""
    raw = raw.strip()
    # Try to find JSON array in markdown code block
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if m:
        raw = m.group(1).strip()
    # Find outermost array
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end <= start:
        # Maybe the model returned an object wrapped in something
        return []
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        # Fallback: try to fix common JSON issues
        try:
            # Remove trailing commas
            cleaned = re.sub(r",\s*([\}\]])", r"\1", raw[start : end + 1])
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return []


def review_markdown(
    md_text: str,
    cfg: ModelConfig,
    prompt: str = "",
) -> AIReviewResult:
    """Send Markdown text to LLM and return parsed issues."""
    if not prompt:
        prompt = _load_prompt() or DEFAULT_PROMPT

    # Trim if too long (most APIs have context limits)
    max_chars = 80000
    if len(md_text) > max_chars:
        md_text = md_text[:max_chars] + "\n\n... [内容截断，仅审读前部]"

    messages: list[dict[str, str]] = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"请审读以下论文（Markdown格式）：\n\n{md_text}"},
    ]

    raw = ""
    try:
        if cfg.provider == "claude" and cfg.enable_prompt_cache:
            raw = _call_anthropic(messages, cfg)
        else:
            raw = _call_openai_compatible(messages, cfg)
    except Exception as exc:
        raw = f"[API Error] {exc}"
        return AIReviewResult(issues=[], raw=raw)

    issues = _extract_json(raw)
    # Normalize issues
    normalized: list[dict[str, Any]] = []
    for item in issues:
        if not isinstance(item, dict):
            continue
        page = item.get("page", 0)
        try:
            page = int(page)
        except Exception:
            page = 0
        normalized.append({
            "page": page,
            "paragraph": str(item.get("paragraph", "")),
            "original": str(item.get("original", "")),
            "error": str(item.get("error", "")),
            "fix": str(item.get("fix", "")),
            "comment": str(item.get("comment", "")),
        })
    return AIReviewResult(issues=normalized, raw=raw)


def _call_openai_compatible(messages: list[dict[str, str]], cfg: ModelConfig) -> str:
    try:
        import openai  # type: ignore
    except ModuleNotFoundError:
        raise RuntimeError("请安装 openai: pip install openai")

    client = openai.OpenAI(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        timeout=cfg.timeout,
    )
    resp = client.chat.completions.create(
        model=cfg.model_name,
        messages=messages,  # type: ignore[arg-type]
        temperature=cfg.temperature,
        top_p=cfg.top_p,
        max_tokens=cfg.max_tokens,
        stream=cfg.stream,
    )
    if cfg.stream:
        parts: list[str] = []
        for chunk in resp:
            delta = chunk.choices[0].delta.content or "" if chunk.choices else ""
            parts.append(delta)
        return "".join(parts)
    return str(resp.choices[0].message.content or "")


def _call_anthropic(messages: list[dict[str, str]], cfg: ModelConfig) -> str:
    try:
        import anthropic  # type: ignore
    except ModuleNotFoundError:
        raise RuntimeError("请安装 anthropic: pip install anthropic")

    system = ""
    user_messages: list[dict[str, str]] = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            user_messages.append(m)

    client = anthropic.Anthropic(api_key=cfg.api_key, timeout=cfg.timeout)
    kwargs: dict[str, Any] = {
        "model": cfg.model_name,
        "max_tokens": cfg.max_tokens,
        "temperature": cfg.temperature,
        "top_p": cfg.top_p,
        "messages": user_messages,  # type: ignore[arg-type]
    }
    if system:
        kwargs["system"] = system

    resp = client.messages.create(**kwargs)
    blocks = getattr(resp, "content", [])
    return "".join(str(b.text) for b in blocks if hasattr(b, "text"))
