const fileInput = document.getElementById("fileInput");
const importBtn = document.getElementById("importBtn");
const startBtn = document.getElementById("startBtn");
const preset = document.getElementById("preset");
const cancelBtn = document.getElementById("cancelBtn");
const statusText = document.getElementById("statusText");
const progressBar = document.getElementById("progressBar");
const progressValue = document.getElementById("progressValue");
const transcriptionProgress = document.getElementById("transcriptionProgress");
const video = document.getElementById("video");
const transcript = document.getElementById("transcript");
const wordCount = document.getElementById("wordCount");
const workspace = document.querySelector(".workspace");
const splitter = document.getElementById("splitter");
const historyList = document.getElementById("historyList");
const refreshHistoryBtn = document.getElementById("refreshHistoryBtn");
const appShell = document.querySelector(".app-shell");
const historyPanel = document.getElementById("historyPanel");
const historyBackdrop = document.getElementById("historyBackdrop");
const openHistoryBtn = document.getElementById("openHistoryBtn");
const closeHistoryBtn = document.getElementById("closeHistoryBtn");
const historySearchInput = document.getElementById("historySearchInput");

const STORAGE_KEYS = {
  activeHash: "videoTranscriber.activeHash",
  playbackPrefix: "videoTranscriber.playback.",
};
const EXPECTED_API_VERSION = 2;
const ACTIVE_STATUSES = new Set(["queued", "running", "cancelling"]);
const BUSY_STATUSES = new Set(["checking", "importing", "version_mismatch", ...ACTIVE_STATUSES]);

let pollTimer = null;
let segments = [];
let activeHash = null;
let currentStatus = "checking";
let currentItemStatus = null;
let isResizing = false;
let pointerDownPosition = null;
let historyCollapsed = true;
let historyItems = [];

init();

function init() {
  bindActionEvents();
  bindWorkspaceEvents();
  bindHistoryEvents();
  renderHistoryPanel();
  renderTranscript([], "请先导入视频");
  updateControls();
  restoreSession();
}

function bindActionEvents() {
  importBtn.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    fileInput.value = "";
    if (file) await importVideo(file);
  });
  startBtn.addEventListener("click", startTranscription);
  cancelBtn.addEventListener("click", cancelTranscription);
}

function bindHistoryEvents() {
  openHistoryBtn.addEventListener("click", () => setHistoryCollapsed(false));
  closeHistoryBtn.addEventListener("click", () => setHistoryCollapsed(true));
  historyBackdrop.addEventListener("click", () => setHistoryCollapsed(true));
  historySearchInput.addEventListener("input", renderHistory);
  refreshHistoryBtn.addEventListener("click", loadHistory);
  window.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || historyCollapsed) return;
    event.preventDefault();
    setHistoryCollapsed(true);
  });
}

function bindWorkspaceEvents() {
  video.addEventListener("timeupdate", () => {
    savePlaybackTime();
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

async function importVideo(file) {
  if (isBusy()) return;
  const previousStatus = currentStatus;
  currentStatus = "importing";
  updateControls();

  const formData = new FormData();
  formData.append("file", file);
  try {
    const response = await fetch("/api/import", { method: "POST", body: formData });
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    activeHash = data.hash;
    currentItemStatus = data.item.status;
    currentStatus = currentItemStatus;
    saveActiveHash(activeHash);
    setVideoSource(`/api/video?t=${Date.now()}`, activeHash);
    if (currentItemStatus === "done") {
      await loadResult();
    } else {
      renderTranscript([], "未转写");
    }
    await loadHistory();
  } catch (error) {
    currentStatus = previousStatus;
    window.alert(`导入失败：${error.message}`);
  } finally {
    updateControls();
  }
}

async function startTranscription() {
  if (!activeHash || isBusy()) return;
  if (currentItemStatus === "done") {
    const confirmed = window.confirm("重新转写会覆盖现有文字稿，确定继续吗？");
    if (!confirmed) return;
  }

  const previousItemStatus = currentItemStatus;
  currentStatus = "queued";
  currentItemStatus = "queued";
  renderProgress("正在准备转写", 3);
  updateControls();

  const formData = new FormData();
  formData.append("preset", preset.value);
  try {
    const response = await fetch(`/api/history/${activeHash}/transcribe`, {
      method: "POST",
      body: formData,
    });
    if (!response.ok) throw new Error(await response.text());
    await loadHistory();
    pollStatus();
  } catch (error) {
    currentStatus = previousItemStatus || "untranscribed";
    currentItemStatus = previousItemStatus || "untranscribed";
    if (currentItemStatus === "done") {
      await loadResult();
    } else {
      renderTranscript([], "未转写");
    }
    window.alert(`启动转写失败：${error.message}`);
    updateControls();
  }
}

function pollStatus() {
  clearInterval(pollTimer);
  pollTaskStatus();
  pollTimer = setInterval(pollTaskStatus, 1000);
}

async function pollTaskStatus() {
  try {
    const response = await fetch("/api/status");
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    if (data.api_version !== EXPECTED_API_VERSION) {
      showVersionMismatch();
      return;
    }
    if (data.hash) {
      activeHash = data.hash;
      saveActiveHash(activeHash);
    }
    currentStatus = data.status;
    currentItemStatus = data.status;

    if (ACTIVE_STATUSES.has(data.status)) {
      renderProgress(formatStatusMessage(data), data.progress);
      updateControls();
      await loadHistory();
      return;
    }

    clearInterval(pollTimer);
    pollTimer = null;
    if (data.status === "done") {
      currentItemStatus = "done";
      await loadResult();
    } else if (data.status === "untranscribed") {
      currentItemStatus = "untranscribed";
      renderTranscript([], data.error ? `转写失败：${data.error}` : "未转写");
    }
    await loadHistory();
    updateControls();
  } catch (error) {
    clearInterval(pollTimer);
    pollTimer = null;
    currentStatus = currentItemStatus || "idle";
    window.alert(`读取转写状态失败：${error.message}`);
    updateControls();
  }
}

async function cancelTranscription() {
  if (!ACTIVE_STATUSES.has(currentStatus) || currentStatus === "cancelling") return;
  currentStatus = "cancelling";
  renderProgress("正在终止，当前片段结束后会停止", Number.parseInt(progressValue.textContent, 10) || 0);
  updateControls();
  const response = await fetch("/api/cancel", { method: "POST" });
  if (!response.ok) window.alert(`终止失败：${await response.text()}`);
}

async function loadResult() {
  const response = await fetch("/api/result");
  if (!response.ok) throw new Error(await response.text());
  const data = await response.json();
  activeHash = data.hash;
  currentStatus = "done";
  currentItemStatus = "done";
  saveActiveHash(activeHash);
  renderTranscript(data.segments || [], "转写完成，但没有识别到文字");
}

function renderTranscript(nextSegments, emptyMessage = "未转写") {
  transcriptionProgress.hidden = true;
  transcript.hidden = false;
  segments = nextSegments;
  transcript.className = segments.length ? "transcript" : "transcript empty";
  transcript.textContent = "";
  const totalChars = segments.reduce((sum, item) => sum + item.text.length, 0);
  wordCount.textContent = `${totalChars} 字`;
  if (!segments.length) {
    transcript.textContent = emptyMessage;
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
      const moved = pointerDownPosition && Math.hypot(
        event.clientX - pointerDownPosition.x,
        event.clientY - pointerDownPosition.y,
      ) > 5;
      if (hasSelection || moved) return;
      video.currentTime = Number(item.start);
      video.play();
    });
    transcript.appendChild(paragraph);
  });
}

function renderProgress(message, progress) {
  transcript.hidden = true;
  transcriptionProgress.hidden = false;
  const value = Math.max(0, Math.min(100, Number(progress) || 0));
  statusText.textContent = message;
  progressBar.style.width = `${value}%`;
  progressValue.textContent = `${Math.round(value)}%`;
  wordCount.textContent = "转写中";
}

async function loadHistory() {
  const response = await fetch("/api/history");
  if (!response.ok) return;
  const data = await response.json();
  historyItems = data.items || [];
  renderHistory();
}

function renderHistory() {
  const query = historySearchInput.value.trim().toLocaleLowerCase();
  const items = query
    ? historyItems.filter((item) => (item.video_name || "").toLocaleLowerCase().includes(query))
    : historyItems;
  historyList.className = items.length ? "history-list" : "history-list empty";
  historyList.textContent = "";
  if (!items.length) {
    historyList.textContent = historyItems.length ? "没有匹配的历史记录" : "暂无历史文件";
    return;
  }

  items.forEach((item) => {
    const wrapper = document.createElement("div");
    wrapper.className = `history-item${item.hash === activeHash ? " active" : ""}`;

    const title = document.createElement("button");
    title.type = "button";
    title.className = "history-open";
    title.disabled = isBusy();
    title.innerHTML = `<span class="history-title"></span><span class="history-meta"></span>`;
    title.querySelector(".history-title").textContent = item.video_name;
    const meta = title.querySelector(".history-meta");
    meta.textContent = formatHistoryMeta(item);
    if (ACTIVE_STATUSES.has(item.status)) meta.classList.add("history-status");
    title.addEventListener("click", () => openHistory(item.hash));

    const actions = document.createElement("div");
    actions.className = "history-actions";
    const del = document.createElement("button");
    del.type = "button";
    del.disabled = isBusy();
    del.textContent = "删除";
    del.addEventListener("click", async (event) => {
      event.stopPropagation();
      if (isBusy()) return;
      const confirmed = window.confirm("确定删除这个历史记录和工具保存的视频副本吗？原始视频文件不会被删除。");
      if (confirmed) await deleteHistory(item.hash);
    });
    actions.appendChild(del);
    wrapper.appendChild(title);
    wrapper.appendChild(actions);
    historyList.appendChild(wrapper);
  });
}

async function openHistory(hash) {
  if (isBusy()) return;
  const response = await fetch(`/api/history/${hash}/open`, { method: "POST" });
  if (!response.ok) {
    window.alert(`打开历史失败：${await response.text()}`);
    return;
  }
  const data = await response.json();
  activeHash = hash;
  currentItemStatus = data.item.status;
  currentStatus = currentItemStatus;
  saveActiveHash(activeHash);
  setVideoSource(`/api/video?t=${Date.now()}`, activeHash);
  if (currentItemStatus === "done") {
    await loadResult();
  } else {
    renderTranscript([], "未转写");
  }
  await loadHistory();
  updateControls();
}

async function deleteHistory(hash) {
  const response = await fetch(`/api/history/${hash}`, { method: "DELETE" });
  if (!response.ok) {
    window.alert(`删除失败：${await response.text()}`);
    return;
  }
  if (hash === activeHash) {
    activeHash = null;
    currentStatus = "idle";
    currentItemStatus = null;
    segments = [];
    video.removeAttribute("src");
    video.load();
    clearStoredActiveHash();
    renderTranscript([], "请先导入视频");
  }
  await loadHistory();
  updateControls();
}

async function restoreSession() {
  let statusData = null;
  try {
    const response = await fetch("/api/status");
    if (response.ok) statusData = await response.json();
  } catch {
    statusData = null;
  }

  if (statusData && statusData.api_version !== EXPECTED_API_VERSION) {
    showVersionMismatch();
    return;
  }

  currentStatus = statusData?.status || "idle";
  await loadHistory();

  if (statusData?.hash) {
    activeHash = statusData.hash;
    currentStatus = statusData.status;
    currentItemStatus = statusData.status;
    saveActiveHash(activeHash);
    setVideoSource(`/api/video?t=${Date.now()}`, activeHash);
    if (ACTIVE_STATUSES.has(statusData.status)) {
      renderProgress(formatStatusMessage(statusData), statusData.progress);
      updateControls();
      pollStatus();
      return;
    }
    if (statusData.status === "done") {
      await loadResult();
    } else {
      renderTranscript([], statusData.error ? `转写失败：${statusData.error}` : "未转写");
    }
    updateControls();
    return;
  }

  const storedHash = getStoredActiveHash();
  if (storedHash) {
    await openHistory(storedHash);
  } else {
    updateControls();
  }
}

function showVersionMismatch() {
  clearInterval(pollTimer);
  pollTimer = null;
  currentStatus = "version_mismatch";
  currentItemStatus = null;
  renderTranscript([], "前后端版本不匹配，请通过启动快捷方式重新启动应用");
  updateControls();
}

function updateControls() {
  const busy = isBusy();
  importBtn.disabled = busy;
  if (currentStatus === "checking") {
    importBtn.textContent = "正在连接";
  } else if (currentStatus === "importing") {
    importBtn.textContent = "正在导入";
  } else if (currentStatus === "version_mismatch") {
    importBtn.textContent = "请重启应用";
  } else {
    importBtn.textContent = "导入视频";
  }
  preset.disabled = busy;
  startBtn.disabled = busy || !activeHash;
  startBtn.textContent = currentItemStatus === "done" ? "重新转写" : "开始转写";
  cancelBtn.disabled = currentStatus === "cancelling";
  renderHistory();
}

function isBusy() {
  return BUSY_STATUSES.has(currentStatus);
}

function setHistoryCollapsed(collapsed) {
  historyCollapsed = collapsed;
  renderHistoryPanel();
}

function renderHistoryPanel() {
  appShell.classList.toggle("history-collapsed", historyCollapsed);
  historyPanel.setAttribute("aria-hidden", String(historyCollapsed));
  historyPanel.inert = historyCollapsed;
  historyBackdrop.hidden = historyCollapsed;
  openHistoryBtn.setAttribute("aria-expanded", String(!historyCollapsed));
}

function stopResizing(event) {
  if (!isResizing) return;
  isResizing = false;
  document.body.classList.remove("resizing");
  if (event && splitter.hasPointerCapture(event.pointerId)) {
    splitter.releasePointerCapture(event.pointerId);
  }
}

function setVideoSource(source, hash) {
  video.src = source;
  restorePlaybackTime(hash);
}

function saveActiveHash(hash) {
  if (hash) localStorage.setItem(STORAGE_KEYS.activeHash, hash);
}

function getStoredActiveHash() {
  return localStorage.getItem(STORAGE_KEYS.activeHash);
}

function clearStoredActiveHash() {
  localStorage.removeItem(STORAGE_KEYS.activeHash);
}

function playbackKey(hash) {
  return `${STORAGE_KEYS.playbackPrefix}${hash}`;
}

function savePlaybackTime() {
  if (!activeHash || !Number.isFinite(video.currentTime)) return;
  localStorage.setItem(playbackKey(activeHash), String(video.currentTime));
}

function restorePlaybackTime(hash) {
  if (!hash) return;
  const stored = Number(localStorage.getItem(playbackKey(hash)));
  if (!Number.isFinite(stored) || stored <= 0) return;
  const applyTime = () => {
    const duration = Number.isFinite(video.duration) ? video.duration : stored;
    video.currentTime = Math.min(stored, Math.max(0, duration - 0.25));
  };
  if (video.readyState >= 1) {
    applyTime();
  } else {
    video.addEventListener("loadedmetadata", applyTime, { once: true });
  }
}

function formatHistoryMeta(item) {
  if (ACTIVE_STATUSES.has(item.status)) return "转写中";
  if (item.status === "untranscribed") return "未转写";
  return formatDuration(item.duration);
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
  if (data.engine && !data.message.includes(data.engine)) parts.push(`引擎：${data.engine}`);
  if (data.fallback_reason) parts.push(`自动降级原因：${data.fallback_reason}`);
  return parts.join(" | ");
}
