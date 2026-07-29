"""批改结果的 Pydantic schema。同时作为 Claude tool_use 的输入 schema。"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

QuestionType = Literal[
    "single_choice",  # 单选
    "multi_choice",   # 多选
    "fill",           # 填空
    "solution",       # 解答题
    "proof",          # 证明题
]


class BBox(BaseModel):
    """相对坐标 (0~1)，以图片左上角为原点。指向学生答案在原图中的位置。"""
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    w: float = Field(ge=0.0, le=1.0)
    h: float = Field(ge=0.0, le=1.0)


class GradedQuestion(BaseModel):
    id: int
    type: QuestionType
    stem: str
    options: list[str] = Field(default_factory=list)
    student_answer: str
    correct_answer: str
    is_correct: bool
    score_got: float
    score_full: float
    comment: str
    solution: str
    answer_bbox: Optional[BBox] = None


class ReportMeta(BaseModel):
    title: str = ""
    subject: str = ""
    total_score_possible: float = 0
    total_score_got: float = 0
    wrong_count: int = 0
    image_width: int = 0
    image_height: int = 0


class GradeReport(BaseModel):
    meta: ReportMeta
    questions: list[GradedQuestion]
