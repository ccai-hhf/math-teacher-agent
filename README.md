# AI 批改作业系统

上传一张学生答卷图，浏览器里立刻拿到：
- 左侧原图 + √/× 标注、正确答案、老师点评
- 右侧每题详细报告（学生答案 / 正确答案 / 得分 / 点评 / 完整解析）

支持题型：单选、多选、填空、解答题、证明题。

## 快速开始

### 1. 配置 API Key

```bash
cd 数学批改agent
cp .env.example .env         # 首次运行 run.sh 也会自动做
# 编辑 .env，填入以下四种之一：
#   DEEPSEEK_API_KEY （推荐，性价比高，默认 https://api.deepseek.com）
#   KIMI_API_KEY     （默认 https://api.moonshot.cn/v1）
#   OPENAI_API_KEY   （OpenAI 或任意兼容接口）
#   ANTHROPIC_API_KEY（Claude 官方或代理）
```

- DeepSeek key：<https://platform.deepseek.com>
- Kimi key：<https://platform.moonshot.cn>
- Anthropic key：<https://console.anthropic.com/settings/keys>

### 2. 一键启动

```bash
./run.sh
```

首次会自动：
- 建 `.venv` 虚拟环境
- 装 `backend/requirements.txt`
- 起 FastAPI (端口 8000)
- 自动打开浏览器 <http://localhost:8000>

### 3. 使用

1. 拖拽或点击上传学生答卷图（PNG / JPG / WEBP，≤15 MB）
2. 可选：上传标准答案图，或在文本框里粘贴答案（如 `1.C 2.B 3.D`）
3. 选学科（默认高中数学）
4. 点【开始批改】，等 15~40 秒（Claude Sonnet 视觉阅卷）
5. 结果页：左看标注图，右看每题报告；顶部三个开关可切换标注层显示

## 项目结构

```
check/
├── backend/
│   ├── main.py          # FastAPI 入口
│   ├── grader.py        # Claude 调用 + tool_use 解析
│   ├── prompts.py       # 系统提示词 + 工具 schema
│   ├── schema.py        # Pydantic 数据模型
│   └── requirements.txt
├── frontend/
│   ├── index.html       # 单页
│   ├── app.js           # 上传/请求/Canvas 标注
│   └── styles.css
├── run.sh               # 一键启动脚本
├── .env.example
└── README.md
```

## 常见问题

**Q: 顶栏提示"未配置 ANTHROPIC_API_KEY"？**  
A: 编辑 `.env` 填入 key 后重启 `./run.sh`。

**Q: 批改结果里 bbox 位置不太准？**  
A: 视觉模型给的 bbox 是近似值。点击右侧对应题目卡片仍可看到完整信息，标注位置不影响判分正确性。

**Q: 图太大？**  
A: 单张 ≤15 MB；后端会自动把最长边压缩到 2048px 后再送模型，无需手动处理。

**Q: 想换模型？**  
A: `.env` 中设置 `GRADER_MODEL=claude-opus-4-5-XXXX` 之类，或改 `backend/grader.py` 里的 `MODEL_ID`。

## 已知限制（v1）

- 单图输入，暂不支持 PDF / 多页拼接
- 不做本地历史记录
- Canvas 标注是近似位置（±5% 误差），以右侧报告卡片为准
- 一次批改一份，请求耗时约 15~40 秒（同步调用，无流式）
