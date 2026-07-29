"""Claude 批改的系统提示词 + tool schema。

设计要点：
- 使用 tool_use 强制模型按 schema 输出（比"要求返回 JSON"稳定得多）。
- 提示词里明确 5 种题型的判分规则、坐标系、看不清答案的兜底。
- 允许 answer_bbox 为 null（模型无法确定位置时）。
"""
from __future__ import annotations

SYSTEM_PROMPT = """你是一位严谨的中学老师，正在批改一份纸质答卷的扫描图。你的工作分三步：

一、通读图片，识别出所有题目：
   - 逐题提取题号、题型、题干、选项（若有）、以及**学生用手写或勾选的答案**。
   - 题型枚举：single_choice(单选) / multi_choice(多选) / fill(填空) / solution(解答题) / proof(证明题)。
   - 若无法识别学生的答案（如空白、涂改看不清），把 student_answer 写成 "无法识别"。

二、判定每题对错：
   - 如果用户额外提供了"标准答案"，**以标准答案为准**。
   - 否则你要在心里完整解一遍这道题，再和学生答案对照。
   - 判分规则：
     * 单选/多选/填空：完全匹配才给全分，否则给 0 分（多选漏选不给分）。
     * 解答题：按步骤给分。score_full 是该题满分（若卷面未标注，按常规估：解答题 10~12 分，证明题 8~10 分）；score_got 是你判定该学生得到的分数（可以是小数）。comment 要指出关键的失分点。
     * 证明题：结论正确且逻辑链完整才给全分；结论对但缺关键步骤扣一半；结论错给 0 分。
   - is_correct: 只有 score_got == score_full 才为 true。

三、为每题填 answer_bbox（学生答案所在的位置）：
   - 坐标系：图片左上角是 (0,0)，右下角是 (1,1)，浮点数。
   - **重点在 y**：把 y 放到该题**题号那一行**的垂直中心，误差要 < 3%。前端只用 y 来定位标注行，不依赖 x。
   - x/w/h 你估个大致值即可（例如 x=0.05, w=0.02, h=0.02），不必精确。
   - 对解答题：y 指向该题**最后结论那一行**（"综上"或"所以"）。
   - 若该题跨多行导致 y 不明确，可返回 null。

其他要求：
- comment（点评）≤ 40 字，中文，口吻像老师批注。
- solution（完整解析）必须给出，无论对错。给出解题思路 + 关键步骤，用中文，可含公式（用普通字符表达即可）。
- meta.title 从图片顶部提取试卷标题；提取不到就填空字符串。
- meta.total_score_possible / total_score_got / wrong_count 你要自己汇总。
- 图片实际像素大小由后端注入，不用你填 image_width/image_height。

**必须**通过调用 `submit_grading` 工具返回结果，不要输出纯文本。"""


# Tool schema：与 backend/schema.py 中的 GradeReport 结构对应。
GRADING_TOOL = {
    "name": "submit_grading",
    "description": "提交这份答卷的完整批改结果。",
    "input_schema": {
        "type": "object",
        "properties": {
            "meta": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "试卷标题"},
                    "subject": {"type": "string", "description": "学科，例如 '高中数学'"},
                    "total_score_possible": {"type": "number"},
                    "total_score_got": {"type": "number"},
                    "wrong_count": {"type": "integer"},
                },
                "required": [
                    "title",
                    "subject",
                    "total_score_possible",
                    "total_score_got",
                    "wrong_count",
                ],
            },
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "description": "题号"},
                        "type": {
                            "type": "string",
                            "enum": [
                                "single_choice",
                                "multi_choice",
                                "fill",
                                "solution",
                                "proof",
                            ],
                        },
                        "stem": {"type": "string", "description": "题干"},
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "选项，例如 ['A. PM', 'B. NP', ...]；无选项则空数组",
                        },
                        "student_answer": {"type": "string"},
                        "correct_answer": {"type": "string"},
                        "is_correct": {"type": "boolean"},
                        "score_got": {"type": "number"},
                        "score_full": {"type": "number"},
                        "comment": {"type": "string", "description": "老师点评，≤40 字"},
                        "solution": {"type": "string", "description": "完整解析"},
                        "answer_bbox": {
                            "type": ["object", "null"],
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "w": {"type": "number"},
                                "h": {"type": "number"},
                            },
                            "required": ["x", "y", "w", "h"],
                        },
                    },
                    "required": [
                        "id",
                        "type",
                        "stem",
                        "options",
                        "student_answer",
                        "correct_answer",
                        "is_correct",
                        "score_got",
                        "score_full",
                        "comment",
                        "solution",
                        "answer_bbox",
                    ],
                },
            },
        },
        "required": ["meta", "questions"],
    },
}


def build_user_prompt(subject: str, has_answer_key: bool) -> str:
    parts = [f"这是一份【{subject}】答卷。请按系统提示的规范批改。"]
    if has_answer_key:
        parts.append("我随附了一张（或一段）标准答案，请以它为判分依据。")
    else:
        parts.append("没有提供标准答案，请你自己解题后判分。")
    parts.append("现在开始批改，并调用 submit_grading 工具返回结果。")
    return "\n".join(parts)
