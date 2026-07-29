"""FastAPI 入口。/api/grade 接收学生答卷 + 可选标准答案，返回 GradeReport JSON。
同时挂载 frontend/ 作为静态资源。"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# 加载项目根目录 .env
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from grader import grade_paper  # noqa: E402  (在 load_dotenv 之后 import 才能读到 key)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("check")

app = FastAPI(title="AI 批改作业系统")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_IMAGE_BYTES = 15 * 1024 * 1024  # 15 MB
ALLOWED_MIME = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


def _provider_info() -> dict:
    if os.environ.get("DEEPSEEK_API_KEY"):
        return {
            "provider": "deepseek",
            "base_url": os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
            "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        }
    if os.environ.get("KIMI_API_KEY"):
        return {
            "provider": "kimi",
            "base_url": os.environ.get("KIMI_BASE_URL") or "https://api.moonshot.cn/v1",
            "model": os.environ.get("KIMI_MODEL", "moonshot-v1-8k-vision-preview"),
        }
    if os.environ.get("OPENAI_API_KEY"):
        return {
            "provider": "openai",
            "base_url": os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1",
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o"),
        }
    return {
        "provider": "anthropic",
        "base_url": os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com",
        "model": os.environ.get("GRADER_MODEL", "claude-sonnet-4-5-20250929"),
    }


@app.get("/api/health")
def health() -> dict:
    info = _provider_info()
    return {
        "ok": True,
        "has_api_key": bool(
            os.environ.get("KIMI_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
        ),
        **info,
    }


@app.post("/api/grade")
async def api_grade(
    answer_sheet: UploadFile = File(...),
    answer_key_image: Optional[UploadFile] = File(None),
    answer_key_text: Optional[str] = Form(None),
    subject: str = Form("高中数学"),
) -> JSONResponse:
    if answer_sheet.content_type not in ALLOWED_MIME:
        raise HTTPException(400, f"不支持的图片格式：{answer_sheet.content_type}")
    sheet_bytes = await answer_sheet.read()
    if len(sheet_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(400, "答卷图过大（>15 MB）")

    key_bytes = None
    if answer_key_image is not None and answer_key_image.filename:
        if answer_key_image.content_type not in ALLOWED_MIME:
            raise HTTPException(400, f"标准答案图格式不支持：{answer_key_image.content_type}")
        key_bytes = await answer_key_image.read()
        if len(key_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(400, "标准答案图过大（>15 MB）")

    try:
        report = await grade_paper(
            sheet_bytes=sheet_bytes,
            key_bytes=key_bytes,
            key_text=answer_key_text,
            subject=subject,
        )
    except RuntimeError as e:
        log.exception("grade failed")
        raise HTTPException(500, str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("grade unexpected")
        raise HTTPException(500, f"批改失败：{e}")

    return JSONResponse(report.model_dump())


# 挂载前端静态文件（放最后，避免 catch-all 覆盖 /api/*）
FRONTEND_DIR = ROOT / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
