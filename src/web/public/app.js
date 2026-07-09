const SOURCE_FOLDER_ORDER = ["developer_trends", "market_discussion", "consumer_attention", "reference_feed", "future", "uncategorized"];
const CATEGORY_LABELS = {
  developer_trends: "开源开发",
  market_discussion: "中文趋势",
  consumer_attention: "视频趋势",
  reference_feed: "参考源",
  future: "未来扩展",
  founder_research: "创始人研究",
  uncategorized: "未分类"
};
const SOURCE_VISUALS = {
  github: { logo: "GH", logoSrc: "assets/brand-logos/github.svg", logoBg: "#24292f", logoFg: "#ffffff" },
  zhihu: { logo: "知", logoSrc: "assets/brand-logos/zhihu.svg", logoBg: "#e9f1ff", logoFg: "#1769ff" },
  bilibili: { logo: "B", logoSrc: "assets/brand-logos/bilibili.svg", logoBg: "#e9f7ff", logoFg: "#00a1d6" },
  wechat: { logo: "微", logoSrc: "assets/brand-logos/wechat.svg", logoBg: "#e9f7ec", logoFg: "#15b35f" },
  xiaohongshu: { logo: "红", logoSrc: "assets/brand-logos/xiaohongshu.svg", logoBg: "#fff0f0", logoFg: "#ff2442" },
  rss: { logo: "RSS", logoSrc: "assets/brand-logos/rss.svg", logoBg: "#fff5e7", logoFg: "#d66b00" }
};

let state = {
  payload: null,
  sources: [],
  sourcePath: "config/sources.yml",
  sourcesContent: "",
  sourceEditorOpen: false,
  profilePath: "config/user-profile.yml",
  selectedId: "",
  cluster: "全部",
  openFolder: "",
  error: ""
};

const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;"
}[char]));

async function fetchJson(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      headers: { "content-type": "application/json" },
      ...options
    });
  } catch (error) {
    throw new Error(`无法连接本地 API：${error.message}`);
  }

  let payload;
  try {
    payload = await response.json();
  } catch (_error) {
    throw new Error(`本地 API 返回了非 JSON 响应：${path}`);
  }

  if (!response.ok) {
    throw new Error(payload.message || `${path} failed with HTTP ${response.status}`);
  }
  return payload;
}

async function loadData() {
  try {
    const [signals, refreshStatus, sources] = await Promise.all([
      fetchJson("/api/signals/latest"),
      fetchJson("/api/refresh/status"),
      fetchJson("/api/sources")
    ]);
    state.error = "";
    state.payload = signals;
    applySourcesPayload(sources);
    syncSelectedSignal();
    render(refreshStatus);
  } catch (error) {
    renderError(error.message);
  }
}

async function loadSources() {
  const payload = await fetchJson("/api/sources");
  applySourcesPayload(payload);
  render();
}

function applySourcesPayload(payload) {
  state.sourcePath = payload.path || "config/sources.yml";
  state.sourcesContent = payload.content || "";
  state.sources = payload.sources || [];
}

function signals() {
  return Array.isArray(state.payload?.signals) ? state.payload.signals : [];
}

function clusters() {
  return ["全部", ...new Set(signals().flatMap((signal) => signal.tags || []).filter(Boolean))].slice(0, 9);
}

function signalCluster(signal) {
  return signal.tags?.[0] || signal.source?.provider || signal.source?.type || "rss";
}

function visibleSignals() {
  if (state.cluster === "全部") return signals();
  return signals().filter((signal) => (signal.tags || []).includes(state.cluster));
}

function selectedSignal() {
  return signals().find((signal) => signal.id === state.selectedId) || visibleSignals()[0] || signals()[0] || null;
}

function syncSelectedSignal() {
  const visible = visibleSignals();
  if (!signals().some((signal) => signal.id === state.selectedId)) {
    state.selectedId = signals()[0]?.id || "";
  }
  if (visible.length && !visible.some((signal) => signal.id === state.selectedId)) {
    state.selectedId = visible[0].id;
  }
}

function statusText(status) {
  if (!status || status.status === "idle") return "读取最近一次成功信号。";
  if (status.status === "running") return `正在刷新：${status.current_step || "refresh"}`;
  if (status.status === "failed" || status.status === "failed_stale_lock") return `刷新失败：${status.last_error || status.status}`;
  if (status.status === "succeeded_empty") return `刷新完成，但暂无可展示信号。${refreshSummaryText(status)}`;
  if (status.status === "succeeded") return `刷新完成。${refreshSummaryText(status)}`;
  return status.status;
}

function refreshSummaryText(status) {
  return [adapterSummaryText(status), storeSummaryText(status)].filter(Boolean).join(" ");
}

function adapterSummaryText(status) {
  const summary = status?.adapter_summary;
  if (!summary) return "";
  const total = summary.total_sources ?? "-";
  const ok = summary.ok_sources ?? "-";
  const failed = summary.failed_sources ?? "-";
  const items = summary.items ?? "-";
  const failedSources = (summary.source_results || []).filter((source) => source.status !== "ok");
  const failedText = failedSources.length
    ? `失败源：${failedSources.map((source) => {
      const message = source.errors?.[0]?.message;
      return message ? `${source.source_id}（${message}）` : source.source_id;
    }).join("；")}。`
    : "";
  return `抓取 ${total} 个源，成功 ${ok} 个，失败 ${failed} 个，入站 ${items} 条。${failedText}`;
}

function storeSummaryText(status) {
  const summary = status?.store_summary;
  const diff = status?.signal_diff;
  const diffText = diff ? (diff.changed ? "推荐队列已变化。" : "推荐队列未变化。") : "";
  if (!summary) return diffText;
  const input = summary.input_items ?? "-";
  const appended = summary.appended_items ?? "-";
  const skipped = summary.skipped_duplicates ?? "-";
  return `本次处理 ${input} 条，新增 ${appended} 条，重复 ${skipped} 条。${diffText}`;
}

function render(refreshStatus = { status: "idle" }) {
  syncSelectedSignal();
  renderStats();
  renderFilters();
  renderSignals();
  renderSourceFolders();
  renderExpandedFolder();
  renderDetail();
  document.getElementById("refresh-status").textContent = statusText(refreshStatus);
  document.getElementById("generated-at").textContent = state.payload?.generated_at || state.payload?.message || "-";
  document.getElementById("input-run-id").textContent = state.payload?.input_run_id || "-";
}

function renderError(message) {
  state.error = message;
  document.getElementById("refresh-status").textContent = `本地 API 错误：${message}`;
  document.getElementById("signal-grid").innerHTML = `<div class="sources-empty">本地 API 错误：${esc(message)}</div>`;
}

function renderStats() {
  const payload = state.payload || {};
  document.getElementById("stat-total").textContent = payload.summary?.input_items ?? "-";
  document.getElementById("stat-high").textContent = signals().length || "-";
  document.getElementById("stat-sources").textContent = state.sources.filter((source) => source.runnable).length;
}

function renderFilters() {
  const filters = clusters();
  document.getElementById("filters").innerHTML = filters.map((cluster) => `
    <button class="filter${cluster === state.cluster ? " is-active" : ""}" type="button" data-cluster="${esc(cluster)}">
      ${esc(cluster)}
    </button>
  `).join("");
  document.querySelectorAll("[data-cluster]").forEach((button) => {
    button.addEventListener("click", () => {
      state.cluster = button.dataset.cluster;
      syncSelectedSignal();
      render();
    });
  });
}

function renderSignals() {
  const container = document.getElementById("signal-grid");
  if (state.payload?.status === "empty") {
    container.innerHTML = `<div class="sources-empty">${esc(state.payload.message)}</div>`;
    return;
  }
  if (state.payload?.status === "error") {
    container.innerHTML = `<div class="sources-empty">本地 signal 文件损坏或不可读。</div>`;
    return;
  }

  const items = visibleSignals();
  if (!items.length) {
    container.innerHTML = `<div class="sources-empty">当前筛选下暂无可展示信号。</div>`;
    return;
  }

  container.innerHTML = items.map((signal) => {
    const score = scorePercent(signal.total_score);
    const active = selectedSignal()?.id === signal.id;
    return `
      <button class="signal${active ? " is-active" : ""}" type="button" data-signal="${esc(signal.id)}">
        <div class="signal-top"><span>${esc(signal.source?.name || signal.source?.provider || "RSS")}</span><span>${esc(signalCluster(signal))}</span></div>
        <h3 class="signal-title">${esc(signal.title)}</h3>
        <p class="signal-summary">${esc(signal.what_happened || signal.why_relevant || "")}</p>
        <div class="signal-bottom">
          <div class="score-rail">
            <span class="score-label">Signal score / 100</span>
            <span class="score-line"><i style="--score:${score}%; --score-color:${scoreColor(score)}"></i></span>
          </div>
          <span class="score-number">${score}</span>
        </div>
      </button>
    `;
  }).join("");

  document.querySelectorAll("[data-signal]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedId = button.dataset.signal;
      render();
    });
  });
}

function scorePercent(score) {
  const value = Number(score || 0);
  const percent = value <= 5 ? value * 20 : value;
  return Math.max(0, Math.min(100, Math.round(percent)));
}

function scoreColor(score) {
  if (score >= 80) return "var(--green)";
  if (score >= 60) return "var(--amber)";
  return "var(--rust)";
}

function renderDetail() {
  const signal = selectedSignal();
  const container = document.getElementById("detail-body");
  if (!signal) {
    container.innerHTML = `<div class="sources-empty">选择一个信号后，这里会显示信号追踪。</div>`;
    return;
  }

  container.innerHTML = `
    <section class="selected-title">
      <small>${esc(signalCluster(signal))} / ${esc(signal.source?.type || "rss")}</small>
      <h3>${esc(signal.title)}</h3>
    </section>
    <section class="detail-score">
      <div><b>${scorePercent(signal.total_score)}</b><span>信号分 /100</span></div>
      <div><b>${esc(signal.importance_score || "-")}</b><span>重要性</span></div>
      <div><b>${esc(signal.relevance_score || "-")}</b><span>相关性</span></div>
    </section>
    <section class="trace">
      <div class="trace-row"><time>${esc(state.payload?.generated_at || "-")}</time><span>抓取来源：${esc(signal.source?.name || "")}</span></div>
      <div class="trace-row"><time>API</time><span>来自 /api/signals/latest 的最近一次成功 signals</span></div>
      <div class="trace-row"><time>RUN</time><span>输入批次：${esc(state.payload?.input_run_id || "-")}</span></div>
    </section>
    <section class="detail-section">
      <h4>为什么重要</h4>
      <p>${esc(signal.why_important || signal.why_relevant || "")}</p>
    </section>
    <section class="detail-section">
      <h4>为什么相关</h4>
      <p>${esc(signal.why_relevant || "")}</p>
    </section>
    <section class="detail-section action-box">
      <h4>建议动作</h4>
      <p>${esc((signal.recommended_questions || []).join("；") || "暂无建议动作。")}</p>
    </section>
    <section class="detail-section">
      <h4>风险/反例</h4>
      <p>${esc((signal.risks || []).join("；") || "暂无风险记录。")}</p>
    </section>
    <section class="detail-section">
      <h4>分数口径</h4>
      <p>信号分是把后端 1-5 规则分换算成 0-100 展示；重要性和相关性保留 1-5 原始分。</p>
    </section>
    <section class="tag-line">
      ${(signal.tags || []).map((tag) => `<span>${esc(tag)}</span>`).join("")}
    </section>
  `;
}

function groupedSources(sources) {
  return sources.reduce((groups, source) => {
    const key = source.category || "uncategorized";
    if (!groups[key]) groups[key] = [];
    groups[key].push(source);
    return groups;
  }, {});
}

function orderedCategories(groups) {
  const known = SOURCE_FOLDER_ORDER.filter((category) => groups[category]);
  const unknown = Object.keys(groups).filter((category) => !SOURCE_FOLDER_ORDER.includes(category)).sort();
  return [...known, ...unknown];
}

function categoryLabel(category) {
  return CATEGORY_LABELS[category] || category;
}

function sourceVisual(source) {
  return SOURCE_VISUALS[source.provider] || SOURCE_VISUALS[source.type] || SOURCE_VISUALS.rss;
}

function renderSourceLogo(source, extraClass = "") {
  const visual = sourceVisual(source);
  const fallback = `<span${visual.logoSrc ? " hidden" : ""}>${esc(visual.logo)}</span>`;
  const image = visual.logoSrc
    ? `<img src="${esc(visual.logoSrc)}" alt="" onerror="this.hidden=true;this.nextElementSibling.hidden=false" />`
    : "";
  return `
    <div
      class="source-app-logo${extraClass ? ` ${esc(extraClass)}` : ""}"
      style="--logo-bg:${esc(visual.logoBg)}; --logo-fg:${esc(visual.logoFg)}"
    >${image}${fallback}</div>
  `;
}

function renderSourceFolders() {
  const groups = groupedSources(state.sources);
  document.getElementById("source-folders").innerHTML = `
    <div class="source-folders-head"><h3>来源文件夹</h3><span>config/sources.yml</span></div>
    <div class="source-folder-list">
      ${orderedCategories(groups).map((category) => {
        const folderSources = groups[category];
        return `
          <button class="source-folder" type="button" data-folder="${esc(category)}">
            <div class="source-folder-title">
              <b>${esc(categoryLabel(category))}</b>
              <span>${folderSources.length} 个来源</span>
            </div>
            <div class="folder-preview-grid">
              ${folderSources.slice(0, 6).map((source) => `
                <div class="source-app${source.runnable ? "" : " is-muted"}" title="${esc(source.signal)}">
                  ${renderSourceLogo(source)}
                  <div class="source-app-name">${esc(source.name)}</div>
                </div>
              `).join("")}
            </div>
          </button>
        `;
      }).join("")}
    </div>
  `;
  document.querySelectorAll("[data-folder]").forEach((folder) => {
    folder.addEventListener("click", () => {
      state.openFolder = folder.dataset.folder;
      renderExpandedFolder();
    });
  });
}

function sourcesInOpenFolder() {
  return state.sources.filter((source) => source.category === state.openFolder);
}

function closeSourceFolder() {
  state.openFolder = "";
  state.sourceEditorOpen = false;
  renderExpandedFolder();
}

async function resetSourceLibrary() {
  try {
    await loadSources();
    document.getElementById("folder-status").textContent = "已重新读取 config/sources.yml";
  } catch (error) {
    document.getElementById("folder-status").textContent = `读取失败：${error.message}`;
  }
}

function renderExpandedFolder() {
  const overlay = document.getElementById("folder-overlay");
  if (!state.openFolder) {
    overlay.hidden = true;
    return;
  }

  const sources = sourcesInOpenFolder();
  if (!sources.length) {
    overlay.hidden = true;
    state.openFolder = "";
    return;
  }

  overlay.hidden = false;
  document.getElementById("folder-title").textContent = categoryLabel(state.openFolder);
  document.getElementById("folder-subtitle").textContent =
    "启用状态会写入 config/sources.yml；未实现来源不可运行";
  document.getElementById("source-config-panel").hidden = !state.sourceEditorOpen;
  document.getElementById("save-source-config").hidden = !state.sourceEditorOpen;
  document.getElementById("edit-source-config").textContent = state.sourceEditorOpen ? "收起编辑器" : "编辑 sources.yml";
  if (state.sourceEditorOpen && document.activeElement?.id !== "source-config-text") {
    document.getElementById("source-config-text").value = state.sourcesContent;
  }
  document.getElementById("expanded-source-grid").innerHTML = sources.map((source) => `
    <article class="expanded-source${source.runnable ? "" : " is-muted"}">
      ${renderSourceLogo(source, "expanded-logo")}
      <div class="expanded-source-name">${esc(source.name)}</div>
      <div class="expanded-source-meta">${esc(source.type)} / ${esc(source.cadence)} / ${source.enabled ? "enabled" : "disabled"}</div>
      <div class="source-control-row">
        <button
          class="source-control primary"
          type="button"
          data-source-toggle="${esc(source.id)}"
          ${source.toggleable ? "" : "disabled"}
        >${source.toggleable ? (source.enabled ? "停用" : "启用") : "不可运行"}</button>
      </div>
    </article>
  `).join("");

  document.querySelectorAll("[data-source-toggle]").forEach((button) => {
    button.addEventListener("click", () => toggleSource(button.dataset.sourceToggle));
  });
}

async function toggleSource(id) {
  const source = state.sources.find((candidate) => candidate.id === id);
  if (!source || !source.toggleable) return;

  const nextEnabled = !source.enabled;
  try {
    const result = await fetchJson(`/api/sources/${encodeURIComponent(id)}`, {
      method: "POST",
      body: JSON.stringify({ enabled: nextEnabled })
    });
    await loadSources();
    document.getElementById("folder-status").textContent =
      `${result.source?.name || source.name} 已${nextEnabled ? "启用" : "停用"}；下次刷新生效`;
  } catch (error) {
    document.getElementById("folder-status").textContent = `保存失败：${error.message}`;
  }
}

function toggleSourceConfigEditor() {
  state.sourceEditorOpen = !state.sourceEditorOpen;
  renderExpandedFolder();
  if (state.sourceEditorOpen) {
    const editor = document.getElementById("source-config-text");
    editor.focus();
    editor.setSelectionRange(0, 0);
    document.getElementById("folder-status").textContent = `正在编辑 ${state.sourcePath}`;
  } else {
    document.getElementById("folder-status").textContent = "刷新会读取 config/sources.yml 中 enabled=true 的 RSS 来源";
  }
}

async function saveSourceConfig() {
  const content = document.getElementById("source-config-text").value;
  try {
    const result = await fetchJson("/api/sources", {
      method: "PUT",
      body: JSON.stringify({ content })
    });
    applySourcesPayload(result);
    state.sourceEditorOpen = false;
    if (!sourcesInOpenFolder().length) {
      state.openFolder = state.sources[0]?.category || "";
    }
    render();
    document.getElementById("folder-status").textContent = `已保存 ${result.path}；下次刷新生效`;
  } catch (error) {
    document.getElementById("folder-status").textContent = `保存失败：${error.message}`;
  }
}

async function refresh() {
  document.getElementById("refresh-status").textContent = "正在刷新...";
  try {
    const result = await fetchJson("/api/refresh", { method: "POST", body: "{}" });
    render(result);
    await loadData();
  } catch (error) {
    renderError(error.message);
  }
}

function updateProfileStatus(message) {
  document.getElementById("user-profile-status").textContent = message;
}

async function loadProfileIntoEditor() {
  const profile = await fetchJson("/api/profile");
  state.profilePath = profile.path || "config/user-profile.yml";
  document.getElementById("user-profile-text").value = profile.content || "";
  updateProfileStatus(`已读取 ${state.profilePath}`);
}

async function openUserProfile() {
  document.getElementById("user-profile-modal").hidden = false;
  const editor = document.getElementById("user-profile-text");
  editor.value = "正在读取 config/user-profile.yml...";
  updateProfileStatus("读取中");
  try {
    await loadProfileIntoEditor();
    editor.focus();
    editor.setSelectionRange(0, 0);
    editor.scrollTop = 0;
  } catch (error) {
    editor.value = "";
    updateProfileStatus(`读取失败：${error.message}`);
  }
}

function closeUserProfile() {
  document.getElementById("user-profile-modal").hidden = true;
}

async function saveUserProfile() {
  try {
    const content = document.getElementById("user-profile-text").value;
    const result = await fetchJson("/api/profile", {
      method: "PUT",
      body: JSON.stringify({ content })
    });
    updateProfileStatus(`已保存 ${result.path}；下次刷新生效`);
  } catch (error) {
    updateProfileStatus(`保存失败：${error.message}`);
  }
}

async function reloadUserProfile() {
  try {
    await loadProfileIntoEditor();
  } catch (error) {
    updateProfileStatus(`重新读取失败：${error.message}`);
  }
}

function downloadUserProfile() {
  const text = document.getElementById("user-profile-text").value;
  const blob = new Blob([text], { type: "text/yaml;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "user-profile.yml";
  link.click();
  URL.revokeObjectURL(link.href);
  updateProfileStatus("已生成下载文件");
}

async function importUserProfile(event) {
  const file = event.target.files[0];
  if (!file) return;
  document.getElementById("user-profile-text").value = await file.text();
  updateProfileStatus(`已导入 ${file.name}；保存后生效`);
  event.target.value = "";
}

function bindControls() {
  document.getElementById("refresh-button").addEventListener("click", refresh);
  document.getElementById("open-user-profile").addEventListener("click", openUserProfile);
  document.getElementById("close-user-profile").addEventListener("click", closeUserProfile);
  document.getElementById("save-user-profile").addEventListener("click", saveUserProfile);
  document.getElementById("reload-user-profile").addEventListener("click", reloadUserProfile);
  document.getElementById("download-user-profile").addEventListener("click", downloadUserProfile);
  document.getElementById("user-profile-file").addEventListener("change", importUserProfile);
  document.getElementById("user-profile-modal").addEventListener("click", (event) => {
    if (event.target.id === "user-profile-modal") closeUserProfile();
  });
  document.getElementById("close-folder").addEventListener("click", closeSourceFolder);
  document.getElementById("edit-source-config").addEventListener("click", toggleSourceConfigEditor);
  document.getElementById("save-source-config").addEventListener("click", saveSourceConfig);
  document.getElementById("reset-source-library").addEventListener("click", resetSourceLibrary);
  document.getElementById("folder-overlay").addEventListener("click", (event) => {
    if (event.target.id === "folder-overlay") closeSourceFolder();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !document.getElementById("user-profile-modal").hidden) closeUserProfile();
    if (event.key === "Escape" && !document.getElementById("folder-overlay").hidden) closeSourceFolder();
  });
}

bindControls();
loadData();
