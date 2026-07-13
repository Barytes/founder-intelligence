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
const TAG_LABELS = {
  "ai-agent": "AI 智能体",
  "ai-coding": "AI 编程",
  "china-market": "中国市场",
  context: "上下文",
  "creator-economy": "创作者经济",
  "developer-tools": "开发者工具",
  github: "GitHub",
  "long-form": "长内容",
  mcp: "MCP 协议",
  "open-source": "开源",
  "public-opinion": "公众讨论",
  reference: "参考源",
  "social-signal": "社交信号",
  "startup-signals": "创业信号",
  trending: "趋势热点",
  video: "视频内容",
  wechat: "微信",
  xiaohongshu: "小红书",
  rss: "RSS 来源"
};
const SOURCE_NAME_LABELS = {
  "github-trending-daily": "GitHub 今日趋势",
  "zhihu-hot": "知乎热榜",
  "bilibili-popular-all": "B 站综合热门",
  "github-activity-diygod": "GitHub 活动参考"
};
const SOURCE_TYPE_LABELS = {
  rss: "RSS 来源",
  mcp: "MCP 来源",
  api: "API 来源",
  html: "网页来源",
  file: "文件来源"
};
const STEP_LABELS = {
  fetch_rss: "抓取 RSS",
  ingest_adapter_output: "标准化资讯",
  store_canonical_jsonl: "写入本地库",
  build_signals: "生成信号"
};
const SCORE_DIMENSIONS = [
  { key: "career", label: "职业", sectionTitle: "职业栏目", color: "var(--green)", description: "与你的工作目标、技术栈和创业判断最相关" },
  { key: "interest", label: "兴趣", sectionTitle: "兴趣栏目", color: "var(--blue)", description: "命中你的长期关注主题和画像关键词" },
  { key: "freshness", label: "新鲜", sectionTitle: "新鲜栏目", color: "var(--amber)", description: "最近出现或刚被抓取，适合快速扫一眼" },
  { key: "explore", label: "探索", sectionTitle: "探索栏目", color: "var(--rust)", description: "不完全贴合旧画像，但可能打开新方向" }
];
const SECTION_LIMIT = 8;
const PROFILE_TERM_LABELS = {
  "ai agents": "AI 智能体",
  "ai agent": "AI 智能体",
  agent: "智能体",
  "ai coding": "AI 编程",
  "coding agent": "编程智能体",
  mcp: "MCP 协议",
  openai: "OpenAI",
  anthropic: "Anthropic",
  claude: "Claude",
  chatgpt: "ChatGPT"
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
  sourceOfTruth: "yaml",
  profile: null,
  profilePath: "config/user-profile.yml",
  selectedId: "",
  cluster: "全部",
  previewId: "",
  previewSection: "",
  previewRect: null,
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
    throw new Error(payload.message || (Array.isArray(payload.errors) ? payload.errors.join("；") : "") || `${path} 请求失败（HTTP ${response.status}）`);
  }
  return payload;
}

async function loadData() {
  try {
    const [signals, refreshStatus, sources, profile] = await Promise.all([
      fetchJson("/api/signals/latest"),
      fetchJson("/api/refresh/status"),
      fetchJson("/api/sources"),
      fetchJson("/api/profile/current")
    ]);
    state.error = "";
    state.payload = signals;
    applySourcesPayload(sources);
    state.profile = profile;
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
  state.sourceOfTruth = payload.source_of_truth || "yaml";
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

function tagLabel(tag) {
  return TAG_LABELS[tag] || tag || "未分类";
}

function sourceDisplayName(source = {}) {
  source = source || {};
  return SOURCE_NAME_LABELS[source.id] || SOURCE_NAME_LABELS[source.source_id] || source.name || source.provider || "RSS 来源";
}

function sourceTypeLabel(type) {
  return SOURCE_TYPE_LABELS[type] || type || "来源";
}

function stepLabel(step) {
  return STEP_LABELS[step] || step || "刷新";
}

function friendlyMessage(message) {
  if (message === "No successful signals have been generated yet.") return "还没有生成成功的信号。";
  if (message === "No store runs have been recorded yet.") return "还没有记录成功的抓取批次。";
  return message || "";
}

function cleanDisplayText(value) {
  return String(value || "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();
}

function truncateDisplayText(value, maxLength) {
  const text = cleanDisplayText(value);
  if (text.length <= maxLength) return text;
  return `${text.slice(0, Math.max(0, maxLength - 1)).trim()}…`;
}

function firstSentence(value) {
  const text = cleanDisplayText(value);
  if (!text) return "";
  return text.split(/(?<=[。！？.!?])\s+/)[0] || text;
}

function removeSourceIntro(value) {
  return cleanDisplayText(value)
    .replace(/^(据|来自).{1,18}(报道|消息|称)[，,:：]\s*/u, "")
    .replace(/^(IT之家|新华社|红星新闻|环球网|新华网|中国新闻周刊)[\s\d月日号]*(消息|报道)?[，,:：]\s*/u, "")
    .replace(/^[【\[][^】\]]{1,24}[】\]]\s*/u, "");
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
  if (status.status === "running") return `正在刷新：${stepLabel(status.current_step)}`;
  if (status.status === "failed" || status.status === "failed_stale_lock") return `刷新失败：${status.last_error || status.status}`;
  if (status.status === "succeeded_empty") return `刷新完成，但暂无可展示信号。${refreshSummaryText(status)}`;
  if (status.status === "succeeded") return `刷新完成。${refreshSummaryText(status)}`;
  if (status.status === "succeeded_partial") return `刷新完成，但部分能力已降级：${(status.degraded_reasons || []).join("；") || "部分来源或智能评分失败"}。${refreshSummaryText(status)}`;
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
  renderNewsPreview();
  document.getElementById("refresh-status").textContent = statusText(refreshStatus);
  document.getElementById("generated-at").textContent = state.payload?.generated_at || friendlyMessage(state.payload?.message) || "-";
  document.getElementById("input-run-id").textContent = state.payload?.input_run_id || "-";
  const profileStatus = state.profile?.profile_status === "active"
    ? `画像已更新：${state.profile?.snapshot?.profile_id || "active"}`
    : "画像未初始化；当前使用中性画像";
  document.getElementById("profile-live-status").textContent = profileStatus;
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
      ${esc(tagLabel(cluster))}
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
    container.innerHTML = `<div class="sources-empty">${esc(friendlyMessage(state.payload.message))}</div>`;
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

  const sections = recommendationSections(items);
  if (state.previewId && !items.some((signal) => signal.id === state.previewId)) {
    state.previewId = "";
    state.previewSection = "";
    state.previewRect = null;
  }

  container.innerHTML = sections.map((section) => `
    <section class="signal-section">
      <article class="signal-section-card" data-section="${esc(section.key)}" style="--section-color:${esc(section.color)}">
        <header class="signal-section-head">
          <div>
            <h3>${esc(section.sectionTitle || section.label)}</h3>
            <p>${esc(section.description)}</p>
          </div>
          <span>${section.items.length} 条</span>
        </header>
        <div class="section-preview-list">
          ${section.items.map((signal) => renderSectionPreview(signal, section.key)).join("")}
        </div>
        <div class="section-card-foot">
          <span>悬停滚动浏览</span>
          <b>${section.items.length}</b>
        </div>
      </article>
    </section>
  `).join("");

  document.querySelectorAll("[data-preview-signal]").forEach((button) => {
    button.addEventListener("click", (event) => {
      const nextPreviewId = button.dataset.previewSignal;
      if (state.previewId === nextPreviewId) {
        state.previewId = "";
        state.previewSection = "";
        state.previewRect = null;
        render();
        return;
      }

      const rect = event.currentTarget.getBoundingClientRect();
      state.previewId = nextPreviewId;
      state.previewRect = {
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
        left: rect.left,
        width: rect.width,
        height: rect.height
      };
      state.previewSection = button.dataset.previewSection || "";
      state.selectedId = button.dataset.previewSignal;
      render();
    });
  });
}

function renderSectionPreview(signal, sectionKey) {
  const active = state.previewId === signal.id && state.previewSection === sectionKey;
  return `
    <div class="section-preview-wrap">
      <button class="section-preview-item${active ? " is-active" : ""}" type="button" data-preview-signal="${esc(signal.id)}" data-preview-section="${esc(sectionKey)}">
        <div class="section-preview-meta">
          <span>${esc(sourceDisplayName(signal.source))}</span>
          <span>${esc(tagLabel(signalCluster(signal)))}</span>
        </div>
        <h4>${esc(displayTitle(signal))}</h4>
        <p>${esc(displaySummary(signal))}</p>
      </button>
    </div>
  `;
}

function renderNewsPreview() {
  const layer = document.getElementById("news-preview-layer");
  if (!layer) return;
  const signal = signals().find((candidate) => candidate.id === state.previewId);
  if (!signal || !state.previewRect) {
    layer.innerHTML = "";
    layer.hidden = true;
    return;
  }

  const width = Math.min(390, Math.max(320, window.innerWidth - 24));
  const gap = 12;
  const canOpenRight = state.previewRect.right + gap + width <= window.innerWidth - 12;
  const left = canOpenRight
    ? state.previewRect.right + gap
    : Math.max(12, state.previewRect.left - width - gap);
  const top = Math.max(12, Math.min(state.previewRect.top - 8, window.innerHeight - 430));

  layer.hidden = false;
  layer.innerHTML = `
    <aside class="signal-popover" role="dialog" aria-label="新闻预览" style="--popover-left:${left}px; --popover-top:${top}px; --popover-width:${width}px">
      <div class="popover-kicker">${esc(sourceDisplayName(signal.source))} / ${esc(tagLabel(signalCluster(signal)))}</div>
      <h4>${esc(displayTitle(signal))}</h4>
      <p>${esc(displaySummary(signal))}</p>
      ${renderInterestChips(signal)}
      ${renderScoreBars(signal, "is-popover")}
      <div class="popover-actions">
        <span>${esc((signal.recommended_questions || [])[0] || "可继续追踪这条信号。")}</span>
        ${signal.link ? `<a href="${esc(signal.link)}" target="_blank" rel="noreferrer" onclick="event.stopPropagation()">原文</a>` : ""}
      </div>
    </aside>
  `;
}

function recommendationSections(items) {
  return SCORE_DIMENSIONS.map((dimension) => {
    const ranked = [...items]
      .sort((a, b) => {
        const aMetric = metricForSignal(a, dimension.key);
        const bMetric = metricForSignal(b, dimension.key);
        return bMetric.percent - aMetric.percent || Number(b.total_score || 0) - Number(a.total_score || 0);
      })
      .slice(0, SECTION_LIMIT);

    return {
      ...dimension,
      items: ranked
    };
  }).filter((section) => section.items.length);
}

function scorePercent(score) {
  const value = Number(score || 0);
  const percent = value <= 5 ? value * 20 : value;
  return Math.max(0, Math.min(100, Math.round(percent)));
}

function clampScore(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(100, Math.round(number)));
}

function toFivePoint(score) {
  const value = Number(score);
  const normalized = value <= 5 ? value : value / 20;
  return Math.max(0, Math.min(5, Math.round(normalized * 10) / 10));
}

function formatFivePoint(score) {
  return Number.isInteger(score) ? String(score) : score.toFixed(1);
}

function profileTermLabel(term) {
  const raw = String(term || "").trim();
  const normalized = raw.toLowerCase();
  return PROFILE_TERM_LABELS[normalized] || TAG_LABELS[normalized] || raw;
}

function displayTitle(signal) {
  if (signal.display_title) return localizeDisplayTitle(signal.display_title);

  const topic = interestPoints(signal)[0] || tagLabel(signalCluster(signal));
  const rawTitle = cleanDisplayText(signal.title);
  let candidate = removeSourceIntro(firstSentence(signal.display_summary || signal.what_happened || signal.why_relevant));

  if (!candidate || candidate === rawTitle) {
    candidate = removeSourceIntro(firstSentence(signal.what_happened || signal.why_relevant || rawTitle));
  }
  if (!candidate) return truncateDisplayText(rawTitle, 38);
  if (topic && !candidate.startsWith(`${topic}：`)) {
    return truncateDisplayText(`${topic}：${candidate}`, 38);
  }
  return truncateDisplayText(candidate, 38);
}

function localizeDisplayTitle(value) {
  return cleanDisplayText(value)
    .replace(/^AI Agent：/u, "AI 智能体：")
    .replace(/^AI Coding：/u, "AI 编程：")
    .replace(/^Open Source：/u, "开源：")
    .replace(/^Social Signal：/u, "社交信号：")
    .replace(/^Context：/u, "上下文：")
    .replace(/^MCP：/u, "MCP 协议：");
}

function displaySummary(signal) {
  if (signal.display_summary) return signal.display_summary;

  const summary = removeSourceIntro(signal.what_happened || signal.why_relevant || signal.title);
  return truncateDisplayText(summary, 150);
}

function interestPoints(signal) {
  const points = [];
  (signal.matched_keywords || []).forEach((match) => {
    points.push(tagLabel(match.tag) || match.label);
  });
  (signal.matched_profile_terms || []).forEach((term) => {
    points.push(profileTermLabel(term));
  });
  if (!points.length) {
    points.push(tagLabel(signalCluster(signal)));
  }

  const seen = new Set();
  return points
    .filter(Boolean)
    .map((point) => String(point).trim())
    .filter((point) => {
      const key = point.toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .slice(0, 4);
}

function renderInterestChips(signal) {
  const points = interestPoints(signal);
  return `
    <div class="interest-row" aria-label="相关兴趣点">
      <span class="interest-kicker">相关</span>
      ${points.map((point) => `<span class="interest-chip">${esc(point)}</span>`).join("")}
    </div>
  `;
}

function freshnessScore(signal) {
  const rawDate = signal.published_at || signal.fetched_at || state.payload?.generated_at;
  const timestamp = Date.parse(rawDate || "");
  if (!Number.isFinite(timestamp)) return 50;

  const hoursOld = Math.max(0, (Date.now() - timestamp) / 36e5);
  if (hoursOld <= 6) return 100;
  if (hoursOld <= 24) return 92;
  if (hoursOld <= 72) return 78;
  if (hoursOld <= 168) return 62;
  if (hoursOld <= 720) return 42;
  return 24;
}

function sourcePriorityBonus(priority) {
  if (priority === "high") return 8;
  if (priority === "medium") return 4;
  return 0;
}

function scoreBreakdown(signal) {
  const profileHits = signal.matched_profile_terms?.length || 0;
  const topicHits = signal.matched_keywords?.length || 0;
  const sourceHits = signal.matched_source_tags?.length || 0;
  const tagCount = signal.tags?.length || 0;
  const negativeHits = signal.negative_matches?.length || 0;
  const importance = scorePercent(signal.importance_score || signal.total_score || 0);
  const relevance = scorePercent(signal.relevance_score || signal.total_score || 0);
  const total = scorePercent(signal.total_score || 0);

  const career = clampScore(
    relevance
      + sourcePriorityBonus(signal.source?.priority)
      + Math.min(12, sourceHits * 3 + profileHits * 2)
      - negativeHits * 6
  );
  const interest = clampScore(
    Math.max(relevance * 0.55, total * 0.45)
      + profileHits * 8
      + topicHits * 10
      + Math.min(8, tagCount * 2)
      - negativeHits * 8
  );
  const freshness = freshnessScore(signal);
  const profileOverlap = Math.min(82, profileHits * 18 + sourceHits * 8 + topicHits * 6);
  const exploration = clampScore(
    (100 - profileOverlap) * 0.42
      + importance * 0.28
      + freshness * 0.2
      + Math.min(10, tagCount * 2)
      - negativeHits * 8
  );

  return SCORE_DIMENSIONS.map((dimension) => ({
    ...dimension,
    percent: { career, interest, freshness, explore: exploration }[dimension.key],
    value: toFivePoint({ career, interest, freshness, explore: exploration }[dimension.key])
  }));
}

function metricForSignal(signal, key) {
  return scoreBreakdown(signal).find((metric) => metric.key === key) || { percent: 0, value: 0 };
}

function renderScoreBars(signal, variant = "") {
  const className = ["score-bars", variant].filter(Boolean).join(" ");
  return `
    <div class="${className}" aria-label="职业、兴趣、新鲜、探索 5 分制评分">
      ${scoreBreakdown(signal).map((metric) => `
        <div class="score-bar" title="${esc(metric.label)} ${formatFivePoint(metric.value)}/5">
          <div class="score-bar-meta">
            <span>${esc(metric.label)}</span>
            <b>${formatFivePoint(metric.value)}</b>
          </div>
          <span class="score-track">
            <i style="--score:${metric.percent}%; --score-color:${metric.color}"></i>
          </span>
        </div>
      `).join("")}
    </div>
  `;
}

function scoreBasisText(signal) {
  if (signal.score_provenance) {
    const score = signal.score_provenance;
    return `规则基线 ${formatFivePoint(Number(score.baseline_score || 0))}/5，智能判断 ${score.agent_component == null ? "已回退" : `${formatFivePoint(Number(score.agent_component))}/5`}，最终分由 ${score.policy_version} 在代码中合成。`;
  }
  const freshnessSource = signal.published_at ? "发布时间" : signal.fetched_at ? "抓取时间" : "本次生成时间";
  return `职业参考后端相关性、来源优先级和画像命中；兴趣参考画像词、主题词与标签命中；新鲜根据${freshnessSource}距离当前时间估算；探索偏向新鲜、重要但与既有画像重合较少的内容。`;
}

const AGENT_DIMENSIONS = [
  ["relevance", "相关性"],
  ["novelty", "新颖性"],
  ["credibility", "可信度"],
  ["urgency", "紧迫性"],
  ["counter_signal", "反向信号"]
];

function renderAgentAssessment(signal) {
  const assessment = signal.agent_assessment;
  const provenance = signal.score_provenance || {};
  if (!assessment || signal.agent_status !== "valid") {
    return `
      <section class="detail-section agent-assessment is-fallback">
        <h4>Agent 新闻判断</h4>
        <p>本条未使用有效 Agent 判断：${esc(provenance.fallback_reason || "未进入候选池或模型不可用")}。</p>
      </section>
    `;
  }
  const baselineRank = Number(signal.baseline_rank || 0);
  const finalRank = Number(signal.final_rank || 0);
  const delta = Number(signal.rank_delta || 0);
  const rankText = baselineRank && finalRank
    ? `规则排序第 ${baselineRank}，混合排序第 ${finalRank}（${delta > 0 ? `上升 ${delta}` : delta < 0 ? `下降 ${Math.abs(delta)}` : "未变化"}）。`
    : "暂无可比较的排序变化。";
  return `
    <section class="detail-section agent-assessment">
      <h4>Agent 新闻判断</h4>
      <div class="agent-dimensions">
        ${AGENT_DIMENSIONS.map(([key, label]) => `
          <span><b>${esc(label)}</b>${formatFivePoint(Number(assessment[key] || 0) * 5)}/5</span>
        `).join("")}
      </div>
      <p>${esc(assessment.reasoning_summary || "")}</p>
      <p class="score-note">${esc(rankText)}</p>
      <div class="agent-evidence">
        <b>原文证据</b>
        <ul>${(assessment.evidence_spans || []).map((span) => `<li>${esc(span.quote || "")}</li>`).join("")}</ul>
      </div>
    </section>
  `;
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
      <small>${esc(tagLabel(signalCluster(signal)))} / ${esc(sourceTypeLabel(signal.source?.type || "rss"))}</small>
      <h3>${esc(displayTitle(signal))}</h3>
      <p>${esc(displaySummary(signal))}</p>
    </section>
    <section class="detail-score-chart">
      <header>
        <h4>四维评分</h4>
        <span>5 分制</span>
      </header>
      ${renderScoreBars(signal, "is-detail")}
      <p class="score-note">${esc(scoreBasisText(signal))}</p>
    </section>
    <section class="trace">
      <div class="trace-row"><time>${esc(state.payload?.generated_at || "-")}</time><span>抓取来源：${esc(sourceDisplayName(signal.source))}</span></div>
      <div class="trace-row"><time>接口</time><span>来自 /api/signals/latest 的最近一次成功信号</span></div>
      <div class="trace-row"><time>批次</time><span>输入批次：${esc(state.payload?.input_run_id || "-")}</span></div>
      <div class="trace-row"><time>工作流</time><span>${esc(signal.workflow_run_id || state.payload?.workflow_run_id || "legacy")}</span></div>
      <div class="trace-row"><time>智能判断</time><span>${esc(signal.agent_status || "未启用")} / ${esc(signal.score_provenance?.policy_version || "deterministic")}</span></div>
    </section>
    ${renderAgentAssessment(signal)}
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
      <p>页面不再只显示单一信号分。柱状图把后端规则分、画像命中、主题命中、来源优先级、时间信息和探索价值拆成四个维度。</p>
    </section>
    <section class="tag-line">
      ${(signal.tags || []).map((tag) => `<span>${esc(tagLabel(tag))}</span>`).join("")}
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
                  <div class="source-app-name">${esc(sourceDisplayName(source))}</div>
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
    state.sourceOfTruth === "sqlite_catalog"
      ? "SQLite SourceCatalog 是 source of truth；状态不会写回 YAML"
      : "Legacy fallback 正在读取 config/sources.yml";
  document.getElementById("source-config-panel").hidden = !state.sourceEditorOpen;
  document.getElementById("save-source-config").hidden = !state.sourceEditorOpen;
  document.getElementById("edit-source-config").textContent = state.sourceEditorOpen ? "收起编辑器" : "导入 legacy sources.yml";
  if (state.sourceEditorOpen && document.activeElement?.id !== "source-config-text") {
    document.getElementById("source-config-text").value = state.sourcesContent;
  }
  document.getElementById("expanded-source-grid").innerHTML = sources.map((source) => `
    <article class="expanded-source${source.runnable ? "" : " is-muted"}">
      ${renderSourceLogo(source, "expanded-logo")}
      <div class="expanded-source-name">${esc(sourceDisplayName(source))}</div>
      <div class="expanded-source-meta">${esc(sourceTypeLabel(source.type))} / ${esc(source.cadence)} / ${esc(source.tracking_state || (source.enabled ? "active" : "paused"))}</div>
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
    document.getElementById("folder-status").textContent = state.sourceOfTruth === "sqlite_catalog" ? "当前来源状态由 SourceCatalog 管理" : "Legacy fallback 会读取 sources.yml";
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

async function saveCurrentContext() {
  const text = document.getElementById("context-input").value.trim();
  if (!text) return;
  const status = document.getElementById("profile-live-status");
  status.textContent = "正在更新画像…";
  try {
    const result = await fetchJson("/api/context/events", {
      method: "POST",
      body: JSON.stringify({
        event_type: "user_statement",
        payload: { text },
        origin: "dashboard"
      })
    });
    state.profile = await fetchJson("/api/profile/current");
    document.getElementById("context-input").value = "";
    status.textContent = result.profile_status === "active"
      ? `画像已更新：${result.profile?.profile_id || "active"}`
      : `信息已保存，画像状态：${result.profile_status}`;
  } catch (error) {
    status.textContent = `更新失败：${error.message}`;
  }
}

async function shareInboxItem() {
  const url = document.getElementById("inbox-url").value.trim();
  const title = document.getElementById("inbox-title").value.trim();
  if (!url) return;
  const status = document.getElementById("inbox-live-status");
  status.textContent = "正在保存…";
  try {
    const result = await fetchJson("/api/inbox/items", {
      method: "POST",
      body: JSON.stringify({ url, title: title || null, note: title || null })
    });
    document.getElementById("inbox-url").value = "";
    document.getElementById("inbox-title").value = "";
    status.textContent = result.item?.tracking_state === "probation"
      ? "已保存，持续追踪正在试运行"
      : "已保存到 Inbox；持续追踪尚未解析";
    await loadSources();
  } catch (error) {
    status.textContent = `保存失败：${error.message}`;
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
  document.getElementById("save-context").addEventListener("click", saveCurrentContext);
  document.getElementById("share-inbox").addEventListener("click", shareInboxItem);
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
  document.addEventListener("click", (event) => {
    if (!state.previewId) return;
    if (event.target.closest("[data-preview-signal]") || event.target.closest("#news-preview-layer")) return;
    state.previewId = "";
    state.previewSection = "";
    state.previewRect = null;
    render();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.previewId) {
      state.previewId = "";
      state.previewSection = "";
      state.previewRect = null;
      render();
    }
    if (event.key === "Escape" && !document.getElementById("user-profile-modal").hidden) closeUserProfile();
    if (event.key === "Escape" && !document.getElementById("folder-overlay").hidden) closeSourceFolder();
  });
}

bindControls();
loadData();
