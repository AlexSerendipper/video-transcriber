const dropZone = document.getElementById("dropZone");
const fileInput = document.getElementById("fileInput");
const fileName = document.getElementById("fileName");
const startBtn = document.getElementById("startBtn");
const copyBtn = document.getElementById("copyBtn");
const preset = document.getElementById("preset");
const cancelBtn = document.getElementById("cancelBtn");
const statusText = document.getElementById("statusText");
const progressBar = document.getElementById("progressBar");
const video = document.getElementById("video");
const transcript = document.getElementById("transcript");
const wordCount = document.getElementById("wordCount");
const workspace = document.querySelector(".workspace");
const splitter = document.getElementById("splitter");
const historyList = document.getElementById("historyList");
const refreshHistoryBtn = document.getElementById("refreshHistoryBtn");

let selectedFile = null;
let pollTimer = null;
let segments = [];
let activeHash = null;
let isResizing = false;
let pointerDownPosition = null;

init();

function init() {
  bindUploadEvents();
  bindWorkspaceEvents();
  refreshHistoryBtn.addEventListener("click", loadHistory);
  loadHistory();
}

function setStatus(message, progress = null) {
  statusText.textContent = message;
  if (progress !== null) {
    progressBar.style.width = `${Math.max(0, Math.min(100, progress))}%`;
  }
}

function setSelectedFile(file) {
  selectedFile = file;
  fileName.textContent = file ? file.name : "支持 mp4、mov、mkv、mp3、m4a 等常见媒体文件";
  startBtn.disabled = !file;
  copyBtn.disabled = true;
  segments = [];
  activeHash = null;
  renderTranscript([]);
  if (file) {
    video.src = URL.createObjectURL(file);
    setStatus("视频已选择，点击开始转写", 0);
  }
}

function bindUploadEvents() {
  dropZone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropZone.classList.add("dragover");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("dragover");
  });

  dropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragover");
    const file = event.dataTransfer.files[0];
    if (file) setSelectedFile(file);
  });

  fileInput.addEventListener("change", () => {
    const file = fileInput.files[0];
    if (file) setSelectedFile(file);
  });

  startBtn.addEventListener("click", () => {
    if (selectedFile) uploadAndTranscribe(false);
  });

  cancelBtn.addEventListener("click", cancelTranscription);

  copyBtn.addEventListener("click", async () => {
    const text = segments.map((item) => item.text).join("\n\n");
    await navigator.clipboard.writeText(text);
    setStatus("已复制纯文字稿", Number.parseInt(progressBar.style.width, 10) || 100);
  });
}

function bindWorkspaceEvents() {
  video.addEventListener("timeupdate", () => {
    if (!segments.length) return;
    const current = video.currentTime;
    const activeIndex = segments.findIndex((item) => current >= item.start && current <= item.end + 0.7);
    document.querySelectorAll(".segment").forEach((node, index) => {
      node.classList.toggle("active", index === activeIndex);
    });
  });

  splitter.addEventListener("pointerdown", (event) => {
    isResizing = true;
    splitter.setPointerCapture(event.pointerId);
    document.body.classList.add("resizing");
  });

  splitter.addEventListener("pointermove", (event) => {
    if (!isResizing) return;
    const bounds = workspace.getBoundingClientRect();
    const splitterWidth = splitter.offsetWidth;
    const minPanelWidth = Math.min(420, Math.floor((bounds.width - splitterWidth) * 0.42));
    const maxLeft = bounds.width - splitterWidth - minPanelWidth;
    const rawLeft = event.clientX - bounds.left;
    const leftWidth = Math.max(minPanelWidth, Math.min(maxLeft, rawLeft));
    workspace.style.setProperty("--player-width", `${leftWidth}px`);
  });

  splitter.addEventListener("pointerup", stopResizing);
  splitter.addEventListener("pointercancel", stopResizing);
}

async function uploadAndTranscribe(force) {
  startBtn.disabled = true;
  copyBtn.disabled = true;
  setStatus(force ? "正在覆盖历史并重新转写" : "正在上传视频", 2);

  const formData = new FormData();
  formData.append("file", selectedFile);
  formData.append("preset", preset.value);
  formData.append("force", force ? "true" : "false");

  try {
    const response = await fetch("/api/transcribe", {
      method: "POST",
      body: formData,
    });
    if (!response.ok) throw new Error(await response.text());

    const data = await response.json();
    if (data.exists) {
      startBtn.disabled = false;
      const overwrite = window.confirm("这个视频已有历史转写结果。点击“确定”覆盖并重新转写，点击“取消”打开历史结果。");
      if (overwrite) {
        await retranscribeExisting(data.hash);
      } else {
        await openHistory(data.hash);
      }
      return;
    }

    activeHash = data.hash;
    video.src = "/api/video";
    cancelBtn.disabled = false;
    pollStatus();
  } catch (error) {
    setStatus(`启动失败：${error.message}`, 100);
    startBtn.disabled = false;
  }
}

async function retranscribeExisting(hash) {
  startBtn.disabled = true;
  const formData = new FormData();
  formData.append("preset", preset.value);

  const response = await fetch(`/api/history/${hash}/retranscribe`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    setStatus(`重新转写失败：${await response.text()}`, 100);
    startBtn.disabled = false;
    return;
  }

  const data = await response.json();
  activeHash = data.hash;
  video.src = "/api/video";
  cancelBtn.disabled = false;
  pollStatus();
}

async function pollStatus() {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const response = await fetch("/api/status");
      const data = await response.json();
      setStatus(formatStatusMessage(data), data.progress);
      cancelBtn.disabled = !["queued", "running", "cancelling"].includes(data.status);
      await loadHistory();

      if (data.status === "done") {
        clearInterval(pollTimer);
        activeHash = data.hash;
        await loadResult();
        await loadHistory();
        startBtn.disabled = false;
        cancelBtn.disabled = true;
      }

      if (data.status === "error") {
        clearInterval(pollTimer);
        startBtn.disabled = false;
        cancelBtn.disabled = true;
      }

      if (data.status === "cancelled") {
        clearInterval(pollTimer);
        startBtn.disabled = false;
        cancelBtn.disabled = true;
        video.removeAttribute("src");
        video.load();
        renderTranscript([]);
      }
    } catch (error) {
      clearInterval(pollTimer);
      setStatus(`读取状态失败：${error.message}`, 100);
      startBtn.disabled = false;
      cancelBtn.disabled = true;
    }
  }, 1000);
}

async function cancelTranscription() {
  cancelBtn.disabled = true;
  setStatus("正在请求终止", Number.parseInt(progressBar.style.width, 10) || 0);
  await fetch("/api/cancel", { method: "POST" });
}

async function loadResult() {
  const response = await fetch("/api/result");
  if (!response.ok) throw new Error(await response.text());
  const data = await response.json();
  activeHash = data.hash;
  renderTranscript(data.segments || []);
}

function renderTranscript(nextSegments) {
  segments = nextSegments;
  transcript.className = segments.length ? "transcript" : "transcript empty";
  transcript.textContent = "";
  const totalChars = segments.reduce((sum, item) => sum + item.text.length, 0);
  wordCount.textContent = `${totalChars} 字`;
  copyBtn.disabled = segments.length === 0;

  if (!segments.length) {
    transcript.textContent = "转写完成后，文字会显示在这里。点击句子可以跳到视频对应位置。";
    return;
  }

  segments.forEach((item) => {
    const paragraph = document.createElement("p");
    paragraph.className = "segment";
    paragraph.textContent = item.text;
    paragraph.dataset.start = item.start;

    paragraph.addEventListener("pointerdown", (event) => {
      pointerDownPosition = { x: event.clientX, y: event.clientY };
    });

    paragraph.addEventListener("click", (event) => {
      const selection = window.getSelection();
      const hasSelection = selection && selection.toString().trim().length > 0;
      const moved = pointerDownPosition && Math.hypot(event.clientX - pointerDownPosition.x, event.clientY - pointerDownPosition.y) > 5;
      if (hasSelection || moved) return;
      video.currentTime = Number(item.start);
      video.play();
    });

    transcript.appendChild(paragraph);
  });
}

async function loadHistory() {
  const response = await fetch("/api/history");
  if (!response.ok) return;
  const data = await response.json();
  renderHistory(data.items || []);
}

function renderHistory(items) {
  historyList.className = items.length ? "history-list" : "history-list empty";
  historyList.textContent = "";

  if (!items.length) {
    historyList.textContent = "暂无历史文件";
    return;
  }

  items.forEach((item) => {
    const wrapper = document.createElement("div");
    wrapper.className = `history-item${item.hash === activeHash ? " active" : ""}`;

    const title = document.createElement("button");
    title.type = "button";
    title.className = "history-open";
    title.innerHTML = `<span class="history-title"></span><span class="history-meta"></span>`;
    title.querySelector(".history-title").textContent = item.video_name;
    const meta = title.querySelector(".history-meta");
    meta.textContent = item.status && item.status !== "done" ? `${formatDuration(item.duration)} · 转写中` : formatDuration(item.duration);
    if (item.status && item.status !== "done") meta.classList.add("history-status");
    title.addEventListener("click", () => openHistory(item.hash));

    const actions = document.createElement("div");
    actions.className = "history-actions";
    const del = document.createElement("button");
    del.type = "button";
    del.textContent = "删除";
    del.addEventListener("click", async (event) => {
      event.stopPropagation();
      const ok = window.confirm("确定删除这个历史记录和工具保存的视频副本吗？原始视频文件不会被删除。");
      if (!ok) return;
      await deleteHistory(item.hash);
    });

    actions.appendChild(del);
    wrapper.appendChild(title);
    wrapper.appendChild(actions);
    historyList.appendChild(wrapper);
  });
}

async function openHistory(hash) {
  const response = await fetch(`/api/history/${hash}/open`, { method: "POST" });
  if (!response.ok) {
    setStatus(`打开历史失败：${await response.text()}`, 100);
    return;
  }
  activeHash = hash;
  video.src = `/api/video?t=${Date.now()}`;
  await loadResult();
  await loadHistory();
  setStatus("已打开历史记录", 100);
}

async function deleteHistory(hash) {
  const response = await fetch(`/api/history/${hash}`, { method: "DELETE" });
  if (!response.ok) {
    setStatus(`删除失败：${await response.text()}`, 100);
    return;
  }
  if (hash === activeHash) {
    activeHash = null;
    video.removeAttribute("src");
    video.load();
    renderTranscript([]);
    setStatus("已删除当前历史记录", 0);
  }
  await loadHistory();
}

function stopResizing(event) {
  if (!isResizing) return;
  isResizing = false;
  document.body.classList.remove("resizing");
  if (event && splitter.hasPointerCapture(event.pointerId)) {
    splitter.releasePointerCapture(event.pointerId);
  }
}

function formatDuration(value) {
  const total = Math.max(0, Math.round(Number(value) || 0));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function formatStatusMessage(data) {
  if (data.error) return `${data.message}：${data.error}`;
  const parts = [data.message];
  if (data.engine && !data.message.includes(data.engine)) {
    parts.push(`引擎：${data.engine}`);
  }
  if (data.fallback_reason) {
    parts.push(`自动降级原因：${data.fallback_reason}`);
  }
  return parts.join(" | ");
}
