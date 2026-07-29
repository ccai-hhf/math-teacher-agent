// AI 批改作业 — 前端主逻辑
// 上传 → POST /api/grade → 渲染原图 + Canvas 标注 + 报告卡片

const $ = (id) => document.getElementById(id);

const state = {
  sheetFile: null,
  keyImageFile: null,
  report: null,
  imgNaturalW: 0,
  imgNaturalH: 0,
};

// ============ 上传交互 ============
const dropZone = $("dropZone");
const sheetInput = $("sheetInput");
const sheetPreview = $("sheetPreview");
const startBtn = $("startBtn");
const uploadError = $("uploadError");

function pickSheet(file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) {
    showError("请上传图片文件");
    return;
  }
  state.sheetFile = file;
  const reader = new FileReader();
  reader.onload = (e) => {
    sheetPreview.src = e.target.result;
    dropZone.classList.add("has-image");
  };
  reader.readAsDataURL(file);
  startBtn.disabled = false;
  hideError();
}

dropZone.addEventListener("click", () => sheetInput.click());
sheetInput.addEventListener("change", (e) => pickSheet(e.target.files[0]));
["dragenter", "dragover"].forEach((ev) =>
  dropZone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropZone.classList.add("drag");
  })
);
["dragleave", "drop"].forEach((ev) =>
  dropZone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag");
  })
);
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  pickSheet(e.dataTransfer.files[0]);
});

// 标准答案图
const keyImageInput = $("keyImageInput");
const keyImageLabel = $("keyImageLabel");
document.querySelector(".mini-drop").addEventListener("click", () => keyImageInput.click());
keyImageInput.addEventListener("change", (e) => {
  const f = e.target.files[0];
  if (!f) return;
  state.keyImageFile = f;
  keyImageLabel.textContent = `已选：${f.name}`;
});

function showError(msg) {
  uploadError.textContent = msg;
  uploadError.hidden = false;
}
function hideError() { uploadError.hidden = true; }

function showToast(msg) {
  let toast = document.getElementById("globalToast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "globalToast";
    toast.className = "toast-error";
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.hidden = false;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => {
    toast.hidden = true;
  }, 8000);
}

// ============ 发起批改 ============
const GRADE_TIMEOUT_MS = 420000; // 客户端最长等待 7 分钟（多题卷子生成耗时较长）

startBtn.addEventListener("click", async () => {
  if (!state.sheetFile) return;
  hideError();
  $("uploader").hidden = true;
  $("loading").hidden = false;
  setStatus("批改中…");

  const fd = new FormData();
  fd.append("answer_sheet", state.sheetFile);
  if (state.keyImageFile) fd.append("answer_key_image", state.keyImageFile);
  const keyText = $("keyTextInput").value.trim();
  if (keyText) fd.append("answer_key_text", keyText);
  fd.append("subject", $("subjectSelect").value);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), GRADE_TIMEOUT_MS);

  try {
    const res = await fetch("/api/grade", {
      method: "POST",
      body: fd,
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    state.report = await res.json();
    renderResult();
  } catch (e) {
    clearTimeout(timeoutId);
    $("loading").hidden = true;
    $("uploader").hidden = false;
    const msg = e.name === "AbortError"
      ? "请求超时（90 秒未响应），请检查网络或后端服务"
      : `批改失败：${e.message}`;
    showError(msg);
    setStatus("失败");
    showToast(msg);
  }
});

function setStatus(s) { $("status").textContent = s; }

// ============ 结果渲染 ============
function renderResult() {
  $("loading").hidden = true;
  $("result").hidden = false;

  const { meta, questions } = state.report;
  setStatus(`完成 · 得分 ${meta.total_score_got}/${meta.total_score_possible}`);

  $("paperTitle").textContent = meta.title || "（无标题）";
  $("scoreBig").textContent = `${meta.total_score_got} / ${meta.total_score_possible}`;
  $("wrongPill").textContent = `错 ${meta.wrong_count} 题`;
  $("wrongPill").style.display = meta.wrong_count > 0 ? "" : "none";

  // 加载原图
  const img = $("paperImg");
  img.onload = () => {
    state.imgNaturalW = img.naturalWidth;
    state.imgNaturalH = img.naturalHeight;
    drawAnnotations();
  };
  img.src = URL.createObjectURL(state.sheetFile);

  renderQuestionList(questions);

  // 图层 toggle
  ["tgMark", "tgAnswer", "tgComment"].forEach((id) => {
    $(id).addEventListener("change", drawAnnotations);
  });
  // 窗口 resize 重画
  window.addEventListener("resize", drawAnnotations);
  // 图片 wrap 滚动时不用重画（canvas 跟 img 同层）
}

// ============ 题目卡片 ============
function renderQuestionList(questions) {
  const list = $("questionList");
  list.innerHTML = "";
  const TYPE_LABEL = {
    single_choice: "单选",
    multi_choice: "多选",
    fill: "填空",
    solution: "解答",
    proof: "证明",
  };
  questions.forEach((q) => {
    const card = document.createElement("div");
    card.className = "q-card " + (q.is_correct ? "correct" : "wrong");
    card.dataset.qid = q.id;

    const scoreCls = q.is_correct ? "ok" : "bad";
    const stuCls = q.is_correct ? "ok" : "wrong";
    card.innerHTML = `
      <div class="q-head">
        <span class="q-num">第 ${q.id} 题</span>
        <span class="q-tag">${TYPE_LABEL[q.type] || q.type}</span>
        <span class="q-score ${scoreCls}">${q.score_got} / ${q.score_full} 分</span>
      </div>
      <div class="q-stem">${escapeHtml(q.stem)}</div>
      ${q.options && q.options.length
        ? `<div class="q-row"><span class="q-label">选项</span><span class="q-value">${q.options.map(escapeHtml).join(" · ")}</span></div>`
        : ""}
      <div class="q-row">
        <span class="q-label">学生答案</span>
        <span class="q-value student ${stuCls}">${escapeHtml(q.student_answer || "—")}</span>
      </div>
      <div class="q-row">
        <span class="q-label">正确答案</span>
        <span class="q-value correct">${escapeHtml(q.correct_answer || "—")}</span>
      </div>
      <div class="q-comment">${escapeHtml(q.comment || "")}</div>
      <details class="q-solution">
        <summary>查看完整解析</summary>
        <div class="q-solution-body">${escapeHtml(q.solution || "")}</div>
      </details>
    `;
    card.addEventListener("mouseenter", () => flashBBox(q.id));
    list.appendChild(card);
  });
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

// ============ Canvas 标注 ============
function drawAnnotations() {
  const canvas = $("annCanvas");
  const img = $("paperImg");
  if (!img.complete || !img.naturalWidth) return;

  // 让 canvas 与 img 同尺寸同位置
  const rect = img.getBoundingClientRect();
  const wrapRect = $("canvasWrap").getBoundingClientRect();
  canvas.style.width = rect.width + "px";
  canvas.style.height = rect.height + "px";
  canvas.style.left = (img.offsetLeft) + "px";
  canvas.style.top = (img.offsetTop) + "px";
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, rect.width, rect.height);

  const showMark = $("tgMark").checked;
  const showAns = $("tgAnswer").checked;
  const showCmt = $("tgComment").checked;

  const W = rect.width;
  const H = rect.height;

  // 策略：像老师批卷一样，√/× 放"左边距"固定列；正确答案 + 点评放"右边距"固定列。
  // 只用模型 bbox 的 y 方向定位行（y 相对稳），x 忽略掉（避免模型 x 飘导致的错位）。
  const LEFT_COL_X = W * 0.025;       // √/× 在图片左侧 2.5% 处
  const RIGHT_COL_X = W * 0.72;       // 正解 / 点评 在图片右侧 72% 处
  const ROW_STEP_MIN = 24;            // 若两行标注太挤，允许微调

  // 先算所有行的 y（像素）
  const rows = state.report.questions.map((q, idx) => {
    let ry;
    if (q.answer_bbox && typeof q.answer_bbox.y === "number") {
      ry = (q.answer_bbox.y + (q.answer_bbox.h || 0) / 2) * H;
    } else {
      // 无 bbox：均匀分布在图上
      ry = (H / (state.report.questions.length + 1)) * (idx + 1);
    }
    return { q, y: Math.max(16, Math.min(H - 16, ry)) };
  });

  rows.forEach(({ q, y }) => {
    if (showMark) {
      drawMark(ctx, q.is_correct, LEFT_COL_X, y);
    }
    if (!q.is_correct) {
      let curY = y;
      if (showAns && q.correct_answer) {
        drawCorrectAnswer(ctx, q.correct_answer, RIGHT_COL_X, curY);
        curY += 18;
      }
      if (showCmt && q.comment) {
        drawComment(ctx, q.comment, RIGHT_COL_X, curY, W - RIGHT_COL_X - 8);
      }
    }
    q._screenY = y;
  });
}

function drawMark(ctx, isCorrect, cx, cy) {
  const r = 10;
  ctx.lineWidth = 3;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  if (isCorrect) {
    ctx.strokeStyle = "#22c55e";
    ctx.beginPath();
    ctx.moveTo(cx - r, cy);
    ctx.lineTo(cx - r / 3, cy + r * 0.7);
    ctx.lineTo(cx + r, cy - r * 0.9);
    ctx.stroke();
  } else {
    ctx.strokeStyle = "#ef4444";
    ctx.beginPath();
    ctx.moveTo(cx - r, cy - r);
    ctx.lineTo(cx + r, cy + r);
    ctx.moveTo(cx + r, cy - r);
    ctx.lineTo(cx - r, cy + r);
    ctx.stroke();
  }
}

function drawCorrectAnswer(ctx, text, x, y) {
  if (!text) return;
  ctx.font = "bold 14px -apple-system, 'PingFang SC', sans-serif";
  ctx.fillStyle = "#ef4444";
  ctx.textBaseline = "middle";
  const t = text.length > 20 ? text.slice(0, 19) + "…" : text;
  ctx.fillText(`正解: ${t}`, x, y);
}

function drawComment(ctx, text, x, y, maxWidth) {
  ctx.font = "12px -apple-system, 'PingFang SC', sans-serif";
  ctx.fillStyle = "#0ea5e9";
  ctx.textBaseline = "middle";
  const t = text.length > 24 ? text.slice(0, 23) + "…" : text;
  ctx.fillText(t, x, y);
}

function flashBBox(qid) {
  // 未来：找到对应 canvas 位置闪烁。v1 先不做，卡片本身已高亮。
}

// ============ 顶部按钮 ============
$("copyJsonBtn").addEventListener("click", async () => {
  if (!state.report) return;
  try {
    await navigator.clipboard.writeText(JSON.stringify(state.report, null, 2));
    $("copyJsonBtn").textContent = "已复制";
    setTimeout(() => ($("copyJsonBtn").textContent = "复制 JSON"), 1500);
  } catch {
    alert("复制失败，请手动打开控制台复制。");
    console.log(state.report);
  }
});

$("restartBtn").addEventListener("click", () => {
  state.report = null;
  state.sheetFile = null;
  state.keyImageFile = null;
  dropZone.classList.remove("has-image");
  sheetPreview.src = "";
  sheetInput.value = "";
  keyImageInput.value = "";
  keyImageLabel.textContent = "选择答案图（可选）";
  $("keyTextInput").value = "";
  startBtn.disabled = true;
  $("result").hidden = true;
  $("uploader").hidden = false;
  setStatus("就绪");
});

// 启动时检查 key 是否配置
fetch("/api/health").then(async (r) => {
  if (!r.ok) return;
  const data = await r.json();
  if (!data.has_api_key) {
    setStatus("⚠ 未配置 ANTHROPIC_API_KEY");
    showError("后端未检测到 ANTHROPIC_API_KEY，请在项目根目录创建 .env 并填写后重启服务。");
  }
});
