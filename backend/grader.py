"""调 LLM 视觉 API 完成批改。

支持两种 provider：
- anthropic: 原 Claude 系列（Anthropic 官方或代理）。
- openai: 任意 OpenAI 兼容 API，例如 Moonshot Kimi、OpenAI、Azure 等。

通过环境变量自动选择：
- 若设置了 KIMI_API_KEY 或 OPENAI_API_KEY，使用 openai provider。
- 否则回退到 anthropic provider（需 ANTHROPIC_API_KEY）。
"""
from __future__ import annotations

import base64
import io
import json
import os
from typing import Any, Optional

from PIL import Image

from prompts import GRADING_TOOL, SYSTEM_PROMPT, build_user_prompt
from schema import GradeReport, ReportMeta

# 首选 Sonnet 4.5（Claude 5 Sonnet 尚未 GA；4.5 已具备高质量视觉 + tool_use）。
MODEL_ID = os.environ.get("GRADER_MODEL", "claude-sonnet-4-5-20250929")
MAX_TOKENS = int(os.environ.get("GRADER_MAX_TOKENS", "16000"))
MAX_EDGE = 2048  # 图片最长边限制，防止 token 超限


def _shrink_and_encode(image_bytes: bytes) -> tuple[str, str, int, int]:
    """把图片限制到最长边 MAX_EDGE，返回 (base64, media_type, w, h)。"""
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_EDGE:
        scale = MAX_EDGE / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    data = buf.getvalue()
    return (
        base64.standard_b64encode(data).decode("ascii"),
        "image/jpeg",
        img.size[0],
        img.size[1],
    )


def _image_block_anthropic(b64: str, media_type: str) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": b64,
        },
    }


def _image_block_openai(b64: str, media_type: str) -> dict:
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{media_type};base64,{b64}"},
    }


def _detect_provider() -> tuple[str, str, Optional[str], str]:
    """返回 (provider, api_key, base_url, model)。"""
    if os.environ.get("DEEPSEEK_API_KEY"):
        return (
            "openai",
            os.environ["DEEPSEEK_API_KEY"],
            os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        )
    if os.environ.get("KIMI_API_KEY"):
        return (
            "openai",
            os.environ["KIMI_API_KEY"],
            os.environ.get("KIMI_BASE_URL", "https://api.moonshot.cn/v1"),
            os.environ.get("KIMI_MODEL", "kimi-k2.6"),
        )
    if os.environ.get("OPENAI_API_KEY"):
        return (
            "openai",
            os.environ["OPENAI_API_KEY"],
            os.environ.get("OPENAI_BASE_URL"),
            os.environ.get("OPENAI_MODEL", "gpt-4o"),
        )
    if os.environ.get("ANTHROPIC_API_KEY"):
        return (
            "anthropic",
            os.environ["ANTHROPIC_API_KEY"],
            os.environ.get("ANTHROPIC_BASE_URL"),
            os.environ.get("GRADER_MODEL", "claude-sonnet-4-5-20250929"),
        )
    raise RuntimeError(
        "未配置任何 API Key。请在 .env 中填写 "
        "DEEPSEEK_API_KEY / KIMI_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY 之一后重启服务。"
    )


def _extract_tool_input_anthropic(response) -> Optional[dict]:
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_grading":
            return block.input
    return None


def _extract_tool_input_openai(response) -> Optional[dict]:
    tool_calls = getattr(response.choices[0].message, "tool_calls", None)
    if not tool_calls:
        return None
    for tc in tool_calls:
        if tc.function.name == "submit_grading":
            return json.loads(tc.function.arguments)
    return None


def _coerce_json(value: Any) -> Any:
    """网关有时会把嵌套结构塞成 JSON 字符串。递归解一次。"""
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("{") or s.startswith("["):
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return value
    return value


def _normalize_tool_input(tool_input: Any) -> dict:
    """把 LLM 返回的 tool input 归一到 {meta:{}, questions:[...]}。"""
    data = _coerce_json(tool_input)
    if not isinstance(data, dict):
        raise RuntimeError(f"submit_grading 返回不是对象：{type(data).__name__}")

    # questions 有时是 str
    if "questions" in data:
        data["questions"] = _coerce_json(data["questions"])
    # meta 有时是 str
    if "meta" in data:
        data["meta"] = _coerce_json(data["meta"])

    # 每道题里的 answer_bbox / options 也可能是 str
    if isinstance(data.get("questions"), list):
        for q in data["questions"]:
            if not isinstance(q, dict):
                continue
            if "answer_bbox" in q:
                q["answer_bbox"] = _coerce_json(q["answer_bbox"])
            if "options" in q:
                opts = _coerce_json(q["options"])
                if opts is None:
                    opts = []
                q["options"] = opts
    return data


def _build_messages(provider: str, user_content: list[dict]) -> list[dict]:
    if provider == "anthropic":
        return [{"role": "user", "content": user_content}]
    # OpenAI 兼容：系统 prompt 单独放 system 角色
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _grade_with_anthropic(
    api_key: str,
    base_url: Optional[str],
    user_content: list[dict],
) -> dict:
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key, base_url=base_url) if base_url else Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL_ID,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[GRADING_TOOL],
        tool_choice={"type": "tool", "name": "submit_grading"},
        messages=[{"role": "user", "content": user_content}],
    )
    tool_input = _extract_tool_input_anthropic(response)
    if tool_input is None:
        raise RuntimeError(
            "Claude 未按预期调用 submit_grading 工具。stop_reason="
            f"{response.stop_reason}"
        )
    return tool_input


def _grade_with_openai(
    api_key: str,
    base_url: Optional[str],
    model: str,
    user_content: list[dict],
    extra_body: Optional[dict] = None,
) -> dict:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)

    openai_tool = {
        "type": "function",
        "function": {
            "name": GRADING_TOOL["name"],
            "description": GRADING_TOOL["description"],
            "parameters": GRADING_TOOL["input_schema"],
        },
    }

    kwargs = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "messages": _build_messages("openai", user_content),
        "tools": [openai_tool],
        "tool_choice": {"type": "function", "function": {"name": "submit_grading"}},
    }
    if extra_body:
        kwargs["extra_body"] = extra_body

    response = client.chat.completions.create(**kwargs)
    tool_input = _extract_tool_input_openai(response)
    if tool_input is None:
        raise RuntimeError(
            "模型未按预期调用 submit_grading 工具。finish_reason="
            f"{response.choices[0].finish_reason}"
        )
    return tool_input


async def grade_paper(
    sheet_bytes: bytes,
    key_bytes: Optional[bytes],
    key_text: Optional[str],
    subject: str,
) -> GradeReport:
    provider, api_key, base_url, model = _detect_provider()

    sheet_b64, sheet_mime, w, h = _shrink_and_encode(sheet_bytes)

    has_key = bool(key_bytes) or bool(key_text and key_text.strip())

    if provider == "anthropic":
        user_content: list[dict] = [_image_block_anthropic(sheet_b64, sheet_mime)]
        image_block_fn = _image_block_anthropic
    else:
        user_content = [_image_block_openai(sheet_b64, sheet_mime)]
        image_block_fn = _image_block_openai

    if key_bytes:
        k_b64, k_mime, _, _ = _shrink_and_encode(key_bytes)
        user_content.append({"type": "text", "text": "以下是【标准答案】图："})
        user_content.append(image_block_fn(k_b64, k_mime))
    if key_text and key_text.strip():
        user_content.append(
            {"type": "text", "text": f"以下是【标准答案】文本：\n{key_text.strip()}"}
        )

    user_content.append({"type": "text", "text": build_user_prompt(subject, has_key)})

    if provider == "anthropic":
        tool_input = _grade_with_anthropic(api_key, base_url, user_content)
    else:
        # Kimi K2.x 默认开启 thinking，与 tool_choice 冲突，需要显式关闭
        extra_body = None
        if base_url and "moonshot" in base_url:
            extra_body = {"thinking": {"type": "disabled"}}
        tool_input = _grade_with_openai(api_key, base_url, model, user_content, extra_body)

    tool_input = _normalize_tool_input(tool_input)

    # 若被 max_tokens 截断导致 questions 缺失/为空 → 再要一次"精简版"（缩短 solution）。
    questions = tool_input.get("questions")
    if not isinstance(questions, list) or len(questions) == 0:
        stop = "unknown"
        retry_hint = (
            "上一次响应被截断了。请**精简每题的 solution（≤80 字）与 comment（≤20 字）**，"
            "然后再次调用 submit_grading，务必把 questions 数组完整给出。"
        )
        retry_content = list(user_content) + [{"type": "text", "text": retry_hint}]

        if provider == "anthropic":
            from anthropic import Anthropic

            client = Anthropic(api_key=api_key, base_url=base_url) if base_url else Anthropic(api_key=api_key)
            response2 = client.messages.create(
                model=MODEL_ID,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=[GRADING_TOOL],
                tool_choice={"type": "tool", "name": "submit_grading"},
                messages=[{"role": "user", "content": retry_content}],
            )
            tool_input2 = _extract_tool_input_anthropic(response2)
        else:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, base_url=base_url)
            openai_tool = {
                "type": "function",
                "function": {
                    "name": GRADING_TOOL["name"],
                    "description": GRADING_TOOL["description"],
                    "parameters": GRADING_TOOL["input_schema"],
                },
            }
            kwargs2 = {
                "model": model,
                "max_tokens": MAX_TOKENS,
                "messages": _build_messages("openai", retry_content),
                "tools": [openai_tool],
                "tool_choice": {"type": "function", "function": {"name": "submit_grading"}},
            }
            if base_url and "moonshot" in base_url:
                kwargs2["extra_body"] = {"thinking": {"type": "disabled"}}
            response2 = client.chat.completions.create(**kwargs2)
            tool_input2 = _extract_tool_input_openai(response2)

        if tool_input2 is not None:
            tool_input = _normalize_tool_input(tool_input2)
            questions = tool_input.get("questions")

    if not isinstance(questions, list) or len(questions) == 0:
        raise RuntimeError(
            "模型返回中未包含 questions（可能被 max_tokens 截断）。"
            "可以试着把 .env 里加 GRADER_MAX_TOKENS=24000 后重启。"
        )

    # 后端填充图片实际尺寸（模型不填这两个）
    meta = tool_input.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}
    meta.setdefault("subject", subject)
    meta["image_width"] = w
    meta["image_height"] = h
    tool_input["meta"] = meta

    report = GradeReport.model_validate(tool_input)

    # 自校验：若模型汇总的分数与逐题不一致，以逐题为准，覆盖 meta
    total_full = sum(q.score_full for q in report.questions)
    total_got = sum(q.score_got for q in report.questions)
    wrong = sum(1 for q in report.questions if not q.is_correct)
    report.meta.total_score_possible = total_full
    report.meta.total_score_got = total_got
    report.meta.wrong_count = wrong
    if not report.meta.subject:
        report.meta.subject = subject
    return report
