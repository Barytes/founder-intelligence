#!/usr/bin/env ruby
# frozen_string_literal: true

require "cgi"
require "erb"
require "fileutils"
require "json"
require "optparse"
require "time"
require "yaml"

DEFAULT_OPTIONS = {
  "sources" => "config/sources.yml",
  "adapter" => "data/adapter-output/rss-fetch-latest.json",
  "canonical" => "data/canonical-items/latest.json",
  "output" => "data/dashboard/source-dashboard.html"
}.freeze

def parse_options(argv)
  options = DEFAULT_OPTIONS.dup

  OptionParser.new do |opts|
    opts.banner = "Usage: src/build_source_dashboard.rb [options]"
    opts.on("--sources PATH", "Path to config/sources.yml") { |value| options["sources"] = value }
    opts.on("--adapter PATH", "Adapter output JSON path") { |value| options["adapter"] = value }
    opts.on("--canonical PATH", "Canonical items JSON path") { |value| options["canonical"] = value }
    opts.on("--output PATH", "Dashboard HTML output path") { |value| options["output"] = value }
  end.parse!(argv)

  options
end

def read_json(path, fallback)
  return fallback unless File.exist?(path)

  JSON.parse(File.read(path))
end

def present?(value)
  !(value.nil? || value.to_s.strip.empty?)
end

def safe_time(value)
  return nil unless present?(value)

  Time.parse(value.to_s).iso8601
rescue ArgumentError
  value
end

def source_record(source, adapter_result, canonical_items)
  items = canonical_items.select { |item| item["source_id"] == source["id"] }
  result_items = adapter_result ? adapter_result.fetch("items", []) : []
  errors = adapter_result ? adapter_result.fetch("errors", []) : []

  {
    "id" => source["id"],
    "name" => source["name"],
    "enabled" => source["enabled"] != false,
    "source_type" => source["source_type"],
    "provider" => source["provider"],
    "fetcher" => source["fetcher"],
    "priority" => source["priority"],
    "category" => source["category"],
    "tags" => source["tags"] || [],
    "schedule" => source["schedule"] || {},
    "connection" => {
      "rss_url" => source.dig("connection", "rss_url"),
      "rsshub_route" => source.dig("connection", "rsshub_route")
    }.compact,
    "status" => adapter_result ? adapter_result["status"] : (source["enabled"] == false ? "disabled" : "not_fetched"),
    "fetched_at" => adapter_result ? safe_time(adapter_result["fetched_at"]) : nil,
    "raw_count" => result_items.length,
    "canonical_count" => items.length,
    "error_count" => errors.length,
    "errors" => errors,
    "notes" => source["notes"]
  }
end

def compact_item(item)
  {
    "id" => item["id"],
    "source_id" => item["source_id"],
    "source_name" => item["source_name"],
    "provider" => item["provider"],
    "category" => item["category"],
    "priority" => item["priority"],
    "title" => item["title"],
    "summary" => item["summary"],
    "content" => item["content"],
    "link" => item["normalized_link"] || item["link"],
    "published_at" => safe_time(item["published_at"]),
    "fetched_at" => safe_time(item["fetched_at"]),
    "author" => item["author"],
    "tags" => item["tags"] || [],
    "quality_flags" => item["quality_flags"] || []
  }
end

def count_by(items, field)
  items.each_with_object(Hash.new(0)) do |item, counts|
    value = item[field] || "unknown"
    counts[value] += 1
  end.sort_by { |key, value| [-value, key.to_s] }.to_h
end

def build_payload(options)
  sources_config = YAML.load_file(options["sources"])
  adapter = read_json(options["adapter"], { "results" => [], "run_id" => nil })
  canonical = read_json(options["canonical"], { "items" => [], "summary" => {} })

  adapter_by_source = adapter.fetch("results", []).each_with_object({}) do |result, map|
    map[result["source_id"]] = result
  end

  canonical_items = canonical.fetch("items", [])
  source_records = sources_config.fetch("sources", []).map do |source|
    source_record(source, adapter_by_source[source["id"]], canonical_items)
  end
  visible_source_records = source_records.select { |source| source["enabled"] }
  visible_source_ids = visible_source_records.map { |source| source["id"] }
  visible_canonical_items = canonical_items.select { |item| visible_source_ids.include?(item["source_id"]) }

  compact_items = visible_canonical_items.map { |item| compact_item(item) }

  {
    "generated_at" => Time.now.iso8601,
    "adapter_run_id" => adapter["run_id"],
    "canonical_run_id" => canonical["run_id"],
    "summary" => {
      "sources" => visible_source_records.length,
      "enabled_sources" => visible_source_records.length,
      "fetched_sources" => visible_source_records.count { |source| %w[ok partial failed].include?(source["status"]) },
      "raw_items" => visible_source_records.sum { |source| source["raw_count"].to_i },
      "canonical_items" => compact_items.length,
      "dropped_items" => canonical.dig("summary", "dropped_items") || 0,
      "adapter_status" => count_by(visible_source_records, "status")
    },
    "breakdowns" => {
      "by_source" => visible_source_records.map do |source|
        {
          "id" => source["id"],
          "name" => source["name"],
          "raw" => source["raw_count"],
          "canonical" => source["canonical_count"],
          "status" => source["status"]
        }
      end,
      "by_category" => count_by(compact_items, "category"),
      "by_provider" => count_by(compact_items, "provider")
    },
    "sources" => visible_source_records,
    "items" => compact_items
  }
end

def dashboard_template
  <<~HTML
    <!doctype html>
    <html lang="zh-CN">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Founder Intelligence · 信息源看板</title>
      <style>
        /*
          Huashu assumptions:
          - This is a local, high-fidelity HTML dashboard for reviewing the information aggregator.
          - Data comes from the project artifacts: config/sources.yml, adapter output, canonical items, and signals.
          - No external fonts or images are loaded; the visual system favors dense operational clarity.
          - This file is a prototype/inspection surface, not the production app shell.
        */
        :root {
          --paper: oklch(0.97 0.018 83);
          --paper-2: oklch(0.93 0.018 83);
          --ink: oklch(0.19 0.018 230);
          --muted: oklch(0.47 0.018 230);
          --line: oklch(0.83 0.018 83);
          --panel: oklch(0.99 0.006 83);
          --green: oklch(0.48 0.09 172);
          --green-soft: oklch(0.92 0.044 172);
          --rust: oklch(0.55 0.13 42);
          --rust-soft: oklch(0.91 0.045 42);
          --blue: oklch(0.45 0.09 245);
          --blue-soft: oklch(0.91 0.042 245);
          --yellow: oklch(0.72 0.11 88);
          --yellow-soft: oklch(0.94 0.05 88);
          --danger: oklch(0.48 0.15 28);
          --shadow: 0 18px 50px rgba(32, 35, 31, 0.08);
        }

        * { box-sizing: border-box; }
        html { scroll-behavior: smooth; }
        body {
          margin: 0;
          min-width: 320px;
          overflow-x: hidden;
          background:
            linear-gradient(90deg, color-mix(in oklch, var(--line) 34%, transparent) 1px, transparent 1px),
            linear-gradient(180deg, color-mix(in oklch, var(--line) 28%, transparent) 1px, transparent 1px),
            var(--paper);
          background-size: 48px 48px;
          color: var(--ink);
          font-family: "Avenir Next", "PingFang SC", "Microsoft YaHei", sans-serif;
          line-height: 1.55;
        }

        button, input, select {
          font: inherit;
        }

        .shell {
          min-height: 100vh;
          display: grid;
          grid-template-columns: minmax(260px, 320px) minmax(0, 1fr);
        }

        .sidebar {
          position: sticky;
          top: 0;
          height: 100vh;
          overflow: auto;
          min-width: 0;
          padding: 28px 22px;
          background: color-mix(in oklch, var(--panel) 90%, transparent);
          border-right: 1px solid var(--line);
        }

        .brand-kicker {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 18px;
          color: var(--muted);
          font-size: 12px;
          letter-spacing: 0.12em;
          text-transform: uppercase;
        }

        .brand-mark {
          width: 18px;
          height: 18px;
          border: 2px solid var(--ink);
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 2px;
          padding: 2px;
        }

        .brand-mark span {
          background: var(--ink);
        }

        h1, h2, h3 {
          margin: 0;
          text-wrap: balance;
          letter-spacing: 0;
          overflow-wrap: anywhere;
        }

        h1 {
          font-family: Georgia, "Times New Roman", serif;
          font-size: clamp(30px, 4vw, 56px);
          line-height: 0.98;
          font-weight: 500;
          max-width: 780px;
        }

        .sidebar h2 {
          font-family: Georgia, "Times New Roman", serif;
          font-weight: 500;
          font-size: 28px;
          line-height: 1.05;
          margin-bottom: 10px;
        }

        .sidebar-note {
          color: var(--muted);
          font-size: 14px;
          margin: 0 0 22px;
          text-wrap: pretty;
          overflow-wrap: anywhere;
        }

        .source-list {
          display: grid;
          gap: 12px;
        }

        .context-panel {
          margin-top: 22px;
          padding-top: 20px;
          border-top: 1px solid var(--line);
        }

        .context-head {
          display: flex;
          justify-content: space-between;
          align-items: start;
          gap: 12px;
          margin-bottom: 10px;
        }

        .context-head h3 {
          font-size: 16px;
          line-height: 1.2;
        }

        .context-head p {
          margin: 4px 0 0;
          color: var(--muted);
          font-size: 12px;
        }

        .context-area {
          width: 100%;
          min-height: 188px;
          resize: vertical;
          border: 1px solid var(--line);
          background: var(--panel);
          color: var(--ink);
          padding: 11px;
          font: 12px/1.55 "JetBrains Mono", "Menlo", monospace;
          outline: none;
        }

        .context-area:focus {
          border-color: var(--green);
        }

        .context-actions {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 8px;
          margin-top: 9px;
        }

        .context-actions button {
          min-height: 36px;
          border: 1px solid var(--line);
          background: var(--panel);
          color: var(--ink);
          cursor: pointer;
          font-size: 13px;
          transition: background 140ms ease, border-color 140ms ease;
        }

        .context-actions button:hover {
          border-color: color-mix(in oklch, var(--green) 55%, var(--line));
          background: var(--green-soft);
        }

        .context-toggle {
          display: flex;
          align-items: center;
          gap: 8px;
          min-height: 38px;
          margin-top: 10px;
          color: var(--ink);
          font-size: 13px;
          cursor: pointer;
        }

        .context-toggle input {
          width: 16px;
          height: 16px;
          accent-color: var(--green);
        }

        .context-toggle.disabled {
          color: var(--muted);
          cursor: not-allowed;
        }

        .context-terms {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          min-height: 30px;
          margin-top: 9px;
        }

        .context-status,
        .muted-note {
          color: var(--muted);
          font-size: 12px;
        }

        .source-card {
          position: relative;
          width: 100%;
          border: 1px solid var(--line);
          background: var(--panel);
          padding: 12px;
          text-align: left;
          cursor: pointer;
          min-height: 112px;
          display: grid;
          gap: 9px;
          transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
        }

        .source-card:hover,
        .source-card.active {
          transform: translateY(-1px);
          border-color: color-mix(in oklch, var(--green) 55%, var(--line));
          background: var(--green-soft);
        }

        .source-card.disabled {
          opacity: 0.55;
        }

        .source-card.empty {
          border-style: dashed;
          cursor: default;
          background: color-mix(in oklch, var(--panel) 72%, var(--paper-2));
        }

        .source-card.empty:hover {
          transform: none;
          border-color: var(--line);
          background: color-mix(in oklch, var(--panel) 72%, var(--paper-2));
        }

        .source-name {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          font-weight: 700;
          line-height: 1.25;
          padding-right: 28px;
        }

        .source-count {
          font-family: Georgia, "Times New Roman", serif;
          font-weight: 500;
          font-size: 24px;
          line-height: 1;
        }

        .source-description {
          color: var(--muted);
          font-size: 12px;
          line-height: 1.45;
          margin: 0;
          display: -webkit-box;
          -webkit-line-clamp: 3;
          -webkit-box-orient: vertical;
          overflow: hidden;
          text-wrap: pretty;
        }

        .source-remove {
          position: absolute;
          top: 8px;
          right: 8px;
          width: 26px;
          height: 26px;
          display: inline-grid;
          place-items: center;
          border: 1px solid var(--line);
          background: color-mix(in oklch, var(--panel) 80%, transparent);
          color: var(--muted);
          cursor: pointer;
          font-size: 18px;
          line-height: 1;
        }

        .source-remove:hover {
          color: var(--danger);
          border-color: color-mix(in oklch, var(--danger) 50%, var(--line));
          background: color-mix(in oklch, var(--rust-soft) 70%, white);
        }

        .source-mini-action {
          min-height: 24px;
          border: 1px solid var(--line);
          background: color-mix(in oklch, white 55%, transparent);
          color: var(--ink);
          font-size: 12px;
          cursor: pointer;
          padding: 2px 8px;
        }

        .source-mini-action:hover {
          border-color: color-mix(in oklch, var(--green) 55%, var(--line));
          background: var(--green-soft);
        }

        .source-draft-area {
          width: 100%;
          min-height: 86px;
          resize: vertical;
          border: 1px solid var(--line);
          background: var(--panel);
          color: var(--ink);
          padding: 10px;
          font: 12px/1.5 "JetBrains Mono", "Menlo", monospace;
          outline: none;
        }

        .source-draft-area:focus {
          border-color: var(--green);
        }

        .source-draft-actions {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 8px;
        }

        .source-draft-actions button {
          min-height: 34px;
          border: 1px solid var(--line);
          background: var(--panel);
          color: var(--ink);
          cursor: pointer;
          font-size: 12px;
        }

        .source-draft-actions button:hover {
          border-color: color-mix(in oklch, var(--green) 55%, var(--line));
          background: var(--green-soft);
        }

        .source-ai-output {
          border: 1px solid color-mix(in oklch, var(--blue) 45%, var(--line));
          background: var(--blue-soft);
          color: var(--ink);
          padding: 10px;
          font-size: 12px;
          line-height: 1.45;
          white-space: pre-wrap;
          text-wrap: pretty;
        }

        .source-meta {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          margin-top: 9px;
        }

        .pill {
          display: inline-flex;
          align-items: center;
          min-height: 24px;
          padding: 3px 8px;
          border: 1px solid var(--line);
          background: color-mix(in oklch, white 55%, transparent);
          color: var(--muted);
          font-size: 12px;
          white-space: nowrap;
        }

        .pill.ok { color: var(--green); border-color: color-mix(in oklch, var(--green) 55%, var(--line)); background: var(--green-soft); }
        .pill.warn { color: var(--rust); border-color: color-mix(in oklch, var(--rust) 55%, var(--line)); background: var(--rust-soft); }
        .pill.blue { color: var(--blue); border-color: color-mix(in oklch, var(--blue) 55%, var(--line)); background: var(--blue-soft); }

        .content {
          padding: 34px;
          max-width: 1560px;
          width: 100%;
          min-width: 0;
          margin: 0 auto;
        }

        .topbar {
          display: flex;
          align-items: end;
          justify-content: space-between;
          gap: 24px;
          margin-bottom: 18px;
          padding-bottom: 18px;
          border-bottom: 1px solid var(--line);
        }

        .topbar h1 {
          font-size: clamp(30px, 4vw, 48px);
        }

        .summary-strip {
          display: flex;
          flex-wrap: wrap;
          justify-content: flex-end;
          gap: 8px;
          max-width: 560px;
        }

        .section {
          margin-top: 24px;
        }

        .compact-section {
          margin-top: 0;
        }

        .section-head {
          display: flex;
          align-items: end;
          justify-content: space-between;
          gap: 18px;
          margin-bottom: 12px;
        }

        .section-head h2 {
          font-family: Georgia, "Times New Roman", serif;
          font-weight: 500;
          font-size: 30px;
        }

        .section-head p {
          margin: 0;
          color: var(--muted);
          font-size: 14px;
        }

        .toolbar {
          display: grid;
          grid-template-columns: minmax(240px, 1fr) 180px 180px;
          gap: 10px;
          margin-bottom: 12px;
        }

        .toolbar input,
        .toolbar select {
          height: 44px;
          border: 1px solid var(--line);
          background: var(--panel);
          color: var(--ink);
          padding: 0 12px;
          outline: none;
        }

        .toolbar input:focus,
        .toolbar select:focus {
          border-color: var(--green);
        }

        .item-layout {
          display: grid;
          grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr);
          gap: 14px;
        }

        .items {
          display: grid;
          gap: 10px;
        }

        .item-card {
          border: 1px solid var(--line);
          background: var(--panel);
          padding: 14px;
          cursor: pointer;
          transition: border-color 140ms ease, background 140ms ease;
        }

        .item-card:hover,
        .item-card.active {
          border-color: color-mix(in oklch, var(--blue) 55%, var(--line));
          background: var(--blue-soft);
        }

        .item-card.context-match {
          border-left: 4px solid var(--green);
        }

        .item-card h3 {
          font-size: 16px;
          line-height: 1.35;
          margin-bottom: 9px;
        }

        .item-card p {
          margin: 0;
          color: var(--muted);
          font-size: 14px;
          display: -webkit-box;
          -webkit-line-clamp: 3;
          -webkit-box-orient: vertical;
          overflow: hidden;
          text-wrap: pretty;
        }

        .item-detail {
          position: sticky;
          top: 24px;
          max-height: calc(100vh - 48px);
          overflow: auto;
          border: 1px solid var(--line);
          background: var(--panel);
          padding: 18px;
          box-shadow: var(--shadow);
        }

        .item-detail h2 {
          font-family: Georgia, "Times New Roman", serif;
          font-weight: 500;
          line-height: 1.08;
          font-size: 32px;
          margin-bottom: 12px;
        }

        .detail-body {
          color: var(--muted);
          font-size: 15px;
          white-space: pre-wrap;
          text-wrap: pretty;
        }

        .context-match-box {
          margin: 14px 0;
          padding: 12px;
          border: 1px solid color-mix(in oklch, var(--green) 45%, var(--line));
          background: var(--green-soft);
        }

        .context-match-box strong {
          display: block;
          margin-bottom: 8px;
          font-size: 13px;
        }

        .detail-link {
          display: inline-flex;
          min-height: 42px;
          align-items: center;
          margin-top: 16px;
          color: var(--ink);
          text-decoration: none;
          border-bottom: 1px solid var(--ink);
          font-weight: 700;
        }

        .empty-state {
          border: 1px dashed var(--line);
          padding: 28px;
          color: var(--muted);
          background: color-mix(in oklch, var(--panel) 70%, transparent);
        }

        @media (max-width: 1180px) {
          .shell { grid-template-columns: 1fr; }
          .sidebar {
            position: relative;
            height: auto;
            border-right: 0;
            border-bottom: 1px solid var(--line);
          }
          .source-list {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
          .topbar,
          .item-layout {
            grid-template-columns: 1fr;
          }
          .topbar {
            display: grid;
            align-items: start;
          }
          .summary-strip {
            justify-content: flex-start;
          }
          .item-detail {
            position: relative;
            top: auto;
            max-height: none;
          }
        }

        @media (max-width: 820px) {
          .content { padding: 22px 16px; }
          .source-list,
          .toolbar {
            grid-template-columns: 1fr;
          }
        }
      </style>
    </head>
    <body>
      <div class="shell">
        <aside class="sidebar">
          <div class="brand-kicker">
            <span class="brand-mark"><span></span><span></span><span></span><span></span></span>
            Local Intelligence
          </div>
          <h2>信息源</h2>
          <p class="sidebar-note">卡片可选择、删减或新增；空白卡片用于描述想追踪的信息源。</p>
          <div class="source-list" id="sourceList"></div>
          <section class="context-panel" aria-label="user.md">
            <div class="context-head">
              <div>
                <h3>user.md</h3>
                <p>关注对象与关键词</p>
              </div>
              <span class="pill blue" id="userTermCount">0 词</span>
            </div>
            <textarea class="context-area" id="userMdInput" spellcheck="false"></textarea>
            <div class="context-actions">
              <button type="button" id="saveUserMd">保存</button>
              <button type="button" id="resetUserMd">重置</button>
              <button type="button" id="downloadUserMd">下载</button>
            </div>
            <label class="context-toggle" id="contextToggleLabel">
              <input type="checkbox" id="contextOnlyToggle">
              <span>只看 user.md 相关</span>
            </label>
            <div class="context-terms" id="userTermPreview"></div>
            <div class="context-status" id="userMdStatus"></div>
          </section>
        </aside>

        <main class="content">
          <section class="topbar">
            <div>
              <div class="brand-kicker">Founder Intelligence / Source Viewer</div>
              <h1>信息源与抓取信息</h1>
            </div>
            <div class="summary-strip" id="summaryStrip"></div>
          </section>

          <section class="section compact-section">
            <div class="section-head">
              <div>
                <h2>抓取信息</h2>
                <p>按来源、分类、关键词筛选；点任意条目查看详情。</p>
              </div>
            </div>
            <div class="toolbar">
              <input id="searchInput" type="search" placeholder="搜索标题、摘要、标签">
              <select id="sourceFilter"></select>
              <select id="categoryFilter"></select>
            </div>
            <div class="item-layout">
              <div class="items" id="itemList"></div>
              <article class="item-detail" id="itemDetail"></article>
            </div>
          </section>
        </main>
      </div>

      <script>
        window.DASHBOARD_DATA = <%= data_json %>;

        const data = window.DASHBOARD_DATA;
        const USER_MD_STORAGE_KEY = 'founder-intelligence:user-md';
        const SOURCE_CARDS_STORAGE_KEY = 'founder-intelligence:source-cards';
        const sourceState = loadSourceState();
        const state = {
          source: 'all',
          category: 'all',
          search: '',
          activeItemId: data.items[0] ? data.items[0].id : null,
          userMd: loadUserMd(),
          userTerms: { include: [], exclude: [] },
          onlyUserRelevant: false,
          hiddenSourceIds: sourceState.hiddenSourceIds,
          customSourceCards: sourceState.customSourceCards,
          sourceDraft: '',
          sourceSuggestion: ''
        };

        const $ = (selector) => document.querySelector(selector);
        const fmt = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' });

        function text(value, fallback = '—') {
          return value === null || value === undefined || value === '' ? fallback : String(value);
        }

        function formatTime(value) {
          if (!value) return '—';
          const date = new Date(value);
          if (Number.isNaN(date.getTime())) return value;
          return fmt.format(date);
        }

        function statusClass(status) {
          if (status === 'ok') return 'ok';
          if (status === 'disabled' || status === 'not_fetched') return 'warn';
          if (status === 'partial') return 'blue';
          return 'warn';
        }

        function escapeHtml(value) {
          return text(value, '').replace(/[&<>"']/g, (char) => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
          }[char]));
        }

        function pill(label, cls = '') {
          return `<span class="pill ${cls}">${escapeHtml(label)}</span>`;
        }

        function loadSourceState() {
          try {
            const parsed = JSON.parse(window.localStorage.getItem(SOURCE_CARDS_STORAGE_KEY) || '{}');
            return {
              hiddenSourceIds: Array.isArray(parsed.hiddenSourceIds) ? parsed.hiddenSourceIds : [],
              customSourceCards: Array.isArray(parsed.customSourceCards) ? parsed.customSourceCards : []
            };
          } catch (_error) {
            return { hiddenSourceIds: [], customSourceCards: [] };
          }
        }

        function storeSourceState() {
          try {
            window.localStorage.setItem(SOURCE_CARDS_STORAGE_KEY, JSON.stringify({
              hiddenSourceIds: state.hiddenSourceIds,
              customSourceCards: state.customSourceCards
            }));
            return true;
          } catch (_error) {
            return false;
          }
        }

        function sourceDescription(source) {
          return text(
            source.description ||
            source.notes ||
            source.connection?.rss_url ||
            source.connection?.rsshub_route ||
            '已接入抓取流程的信息源。'
          );
        }

        function baseSourceCards() {
          return data.sources.map((source) => ({
            id: source.id,
            name: source.name,
            provider: source.provider,
            priority: source.priority || 'medium',
            status: source.status,
            canonical_count: source.canonical_count,
            tags: source.tags || [],
            description: sourceDescription(source),
            custom: false
          }));
        }

        function visibleSourceCards() {
          const base = baseSourceCards().filter((source) => !state.hiddenSourceIds.includes(source.id));
          return [...base, ...state.customSourceCards];
        }

        function visibleDataSourceIds() {
          return visibleSourceCards().filter((source) => !source.custom).map((source) => source.id);
        }

        function visibleDataItems() {
          const ids = visibleDataSourceIds();
          return data.items.filter((item) => ids.includes(item.source_id));
        }

        function sourceDraftTerms(value) {
          const cleaned = text(value, '')
            .replace(/[。！？!?]/g, '，')
            .replace(/(我想|想要|想看|帮我|追踪|关注|抓取|检索|找到|关于|信息源|资讯|新闻|内容)/g, ' ');
          const terms = splitTermLine(cleaned)
            .flatMap((part) => part.split(/\\s+/))
            .map((part) => normalizeTerm(part))
            .filter(Boolean);
          return Array.from(new Set(terms)).slice(0, 10);
        }

        function buildSourceSuggestion(value) {
          const raw = text(value, '').trim();
          const terms = sourceDraftTerms(raw);
          const focus = terms.length ? terms.join('、') : (raw || '待补充主题');
          const haystack = `${raw} ${terms.join(' ')}`.toLowerCase();
          const channels = ['官网 Blog / Changelog', 'RSS / RSSHub 路由', '行业媒体与专题页'];

          if (/(github|开源|repo|release|版本|sdk|api)/i.test(haystack)) {
            channels.push('GitHub Releases / Issues');
          }
          if (/(投融资|融资|创业|创始人|vc|startup|product hunt|yc)/i.test(haystack)) {
            channels.push('Product Hunt / YC / 投资机构博客');
          }
          if (/(社媒|twitter|x|微博|小红书|公众号|播客|youtube)/i.test(haystack)) {
            channels.push('社媒搜索页 / 公众号 / 播客更新');
          }

          return [
            `检索目标：持续发现「${focus}」相关的一手信息源。`,
            `优先渠道：${Array.from(new Set(channels)).join('、')}。`,
            `关键词组合：${terms.length ? terms.join(' OR ') : focus}。`,
            '抓取要求：保留标题、来源、发布时间、摘要和原文链接，优先一手发布与高信噪比来源。',
            '排除：广告、重复转载、无来源摘要、纯观点转述。'
          ].join('\\n');
        }

        function sourceDraftName(value) {
          const terms = sourceDraftTerms(value);
          if (terms.length === 0) return '新信息源';
          return `${terms.slice(0, 2).join(' / ')} 线索`;
        }

        function addDraftSourceCard() {
          const draft = state.sourceDraft.trim();
          if (!draft) {
            state.sourceSuggestion = '先写下要追踪的主题、公司、人物或渠道。';
            renderSources();
            return;
          }

          const suggestion = state.sourceSuggestion && !state.sourceSuggestion.startsWith('先写下')
            ? state.sourceSuggestion
            : buildSourceSuggestion(draft);
          const card = {
            id: `custom-${Date.now()}`,
            name: sourceDraftName(draft),
            provider: 'AI prompt',
            priority: 'draft',
            status: 'draft',
            canonical_count: 0,
            tags: sourceDraftTerms(draft).slice(0, 6),
            description: suggestion,
            custom: true
          };

          state.customSourceCards = [...state.customSourceCards, card];
          state.sourceDraft = '';
          state.sourceSuggestion = '';
          storeSourceState();
          renderAll();
        }

        function removeSourceCard(id) {
          if (id.startsWith('custom-')) {
            state.customSourceCards = state.customSourceCards.filter((source) => source.id !== id);
          } else if (!state.hiddenSourceIds.includes(id)) {
            state.hiddenSourceIds = [...state.hiddenSourceIds, id];
          }
          if (state.source === id) state.source = 'all';
          storeSourceState();
          renderAll();
        }

        function renderSourceFilterOptions() {
          const cards = visibleSourceCards();
          const options = ['all', ...cards.map((source) => source.id)];
          if (!options.includes(state.source)) state.source = 'all';
          $('#sourceFilter').innerHTML = options.map((id) => {
            const source = cards.find((candidate) => candidate.id === id);
            const label = id === 'all' ? '全部可见来源' : source.name;
            return `<option value="${escapeHtml(id)}">${escapeHtml(label)}</option>`;
          }).join('');
          $('#sourceFilter').value = state.source;
        }

        function defaultUserMd() {
          return [
            '# user.md',
            '',
            '## 关注对象',
            '- 信息聚合器',
            '- AI Agent',
            '- 创始人效率',
            '',
            '## 关键词',
            'AI, Agent, RSS, 产品, 增长, 投资, 竞品, 信息源',
            '',
            '## 排除',
            '- 纯广告',
            '- 娱乐八卦'
          ].join('\\n');
        }

        function loadUserMd() {
          try {
            return window.localStorage.getItem(USER_MD_STORAGE_KEY) || defaultUserMd();
          } catch (_error) {
            return defaultUserMd();
          }
        }

        function storeUserMd(value) {
          try {
            window.localStorage.setItem(USER_MD_STORAGE_KEY, value);
            return true;
          } catch (_error) {
            return false;
          }
        }

        function splitTermLine(value) {
          const separators = ['，', ',', '、', ';', '；', '|', '/', '\\\\'];
          return separators.reduce((parts, separator) => (
            parts.flatMap((part) => part.split(separator))
          ), [value]);
        }

        function normalizeTerm(term) {
          const normalized = text(term, '')
            .replace(/^[：:]+/, '')
            .replace(/[。！？!?]+$/g, '')
            .trim()
            .toLowerCase();
          if (normalized.length < 2 || normalized.length > 40) return null;
          if (/^(user\\.md|user|md)$/i.test(normalized)) return null;
          return normalized;
        }

        function parseUserMd(markdown) {
          const include = [];
          const exclude = [];
          let section = 'include';
          const addTerm = (collection, term) => {
            const normalized = normalizeTerm(term);
            if (normalized && !collection.includes(normalized)) collection.push(normalized);
          };

          text(markdown, '').split(/\\r?\\n/).forEach((line) => {
            const raw = line.trim();
            if (!raw) return;
            if (/^#+/.test(raw)) {
              const heading = raw.replace(/^#+\\s*/, '').toLowerCase();
              section = /(排除|忽略|不关注|exclude|ignore)/i.test(heading) ? 'exclude' : 'include';
              return;
            }

            const normalizedLine = raw
              .replace(/^[-*+]\\s*/, '')
              .replace(/^(关键词|关注对象|行业|公司|主题|排除|忽略|不关注|目标|问题|focus|keywords|exclude|ignore)[:：]/i, '')
              .replace(/[`*_>#]/g, ' ')
              .trim();

            splitTermLine(normalizedLine).forEach((part) => {
              addTerm(section === 'exclude' ? exclude : include, part);
            });
          });

          return {
            include: include.slice(0, 48),
            exclude: exclude.slice(0, 24)
          };
        }

        function itemHaystack(item) {
          return [
            item.title,
            item.summary,
            item.content,
            item.source_name,
            item.provider,
            item.category,
            (item.tags || []).join(' ')
          ].join(' ').toLowerCase();
        }

        function contextForItem(item) {
          const haystack = itemHaystack(item);
          const hits = state.userTerms.include.filter((term) => haystack.includes(term));
          const excluded = state.userTerms.exclude.filter((term) => haystack.includes(term));
          return {
            hits,
            excluded,
            relevant: hits.length > 0 && excluded.length === 0
          };
        }

        function contextMatchCount() {
          return visibleDataItems().filter((item) => contextForItem(item).relevant).length;
        }

        function renderSources() {
          const list = $('#sourceList');
          const cards = visibleSourceCards();
          const allCard = `
            <article class="source-card ${state.source === 'all' ? 'active' : ''}" data-source="all">
              <div class="source-name">
                <span>全部可见来源</span>
                <span class="source-count">${visibleDataItems().length}</span>
              </div>
              <p class="source-description">汇总当前保留的信息源卡片；删除卡片后，对应抓取信息会从全部视图中隐藏。</p>
              <div class="source-meta">
                ${pill(`${cards.length} 张卡`, 'ok')}
                ${pill(`${state.customSourceCards.length} 张草稿`, state.customSourceCards.length ? 'warn' : '')}
                ${state.hiddenSourceIds.length ? `<button type="button" class="source-mini-action" id="restoreDefaultSources">恢复默认源</button>` : ''}
              </div>
            </article>
          `;

          const sourceCards = cards.map((source) => `
            <article class="source-card ${state.source === source.id ? 'active' : ''}" data-source="${escapeHtml(source.id)}">
              <button type="button" class="source-remove" data-remove-source="${escapeHtml(source.id)}" aria-label="删除 ${escapeHtml(source.name)}">×</button>
              <div class="source-name">
                <span>${escapeHtml(source.name)}</span>
                <span class="source-count">${source.custom ? '0' : source.canonical_count}</span>
              </div>
              <p class="source-description">${escapeHtml(source.description)}</p>
              <div class="source-meta">
                ${pill(source.status, statusClass(source.status))}
                ${pill(source.provider || 'source')}
                ${pill(source.priority || 'medium')}
                ${source.custom ? pill('待接入', 'warn') : ''}
              </div>
            </article>
          `).join('');

          const draftCard = `
            <article class="source-card empty" id="sourceDraftCard">
              <div class="source-name">
                <span>添加信息源</span>
                <span class="pill blue">空白卡片</span>
              </div>
              <textarea class="source-draft-area" id="sourceDraftInput" placeholder="输入想追踪的主题、公司、人物、渠道或问题">${escapeHtml(state.sourceDraft)}</textarea>
              <div class="source-draft-actions">
                <button type="button" id="assistSourcePrompt">AI补全</button>
                <button type="button" id="addSourceCard">加入</button>
                <button type="button" id="clearSourceDraft">清空</button>
              </div>
              ${state.sourceSuggestion ? `<div class="source-ai-output" id="sourceAiOutput">${escapeHtml(state.sourceSuggestion)}</div>` : '<div class="muted-note">AI 补全会把输入转成可用于检索信息源的提示。</div>'}
            </article>
          `;

          list.innerHTML = allCard + sourceCards + draftCard;
          renderSourceFilterOptions();

          list.querySelectorAll('.source-card[data-source]').forEach((card) => {
            card.addEventListener('click', (event) => {
              if (event.target.closest('button')) return;
              state.source = state.source === card.dataset.source && card.dataset.source !== 'all' ? 'all' : card.dataset.source;
              renderSourceFilterOptions();
              renderAll();
            });
          });

          list.querySelectorAll('[data-remove-source]').forEach((button) => {
            button.addEventListener('click', (event) => {
              event.stopPropagation();
              removeSourceCard(button.dataset.removeSource);
            });
          });

          $('#sourceDraftInput').addEventListener('input', (event) => {
            state.sourceDraft = event.target.value;
          });
          $('#assistSourcePrompt').addEventListener('click', () => {
            state.sourceSuggestion = buildSourceSuggestion(state.sourceDraft);
            renderSources();
          });
          $('#addSourceCard').addEventListener('click', () => {
            addDraftSourceCard();
          });
          $('#clearSourceDraft').addEventListener('click', () => {
            state.sourceDraft = '';
            state.sourceSuggestion = '';
            renderSources();
          });
          const restoreButton = $('#restoreDefaultSources');
          if (restoreButton) {
            restoreButton.addEventListener('click', (event) => {
              event.stopPropagation();
              state.hiddenSourceIds = [];
              storeSourceState();
              renderAll();
            });
          }
        }

        function renderHeader() {
          const userTermCount = state.userTerms.include.length;
          const userMatchLabel = userTermCount > 0 ? `${contextMatchCount()} 条 user.md 相关` : 'user.md 0 词';
          $('#summaryStrip').innerHTML = [
            pill(`${visibleSourceCards().length} 张源卡`, 'ok'),
            pill(`${visibleDataItems().length} 条抓取信息`, 'blue'),
            pill(userMatchLabel, userTermCount > 0 ? 'ok' : 'warn'),
            pill(`生成 ${formatTime(data.generated_at)}`)
          ].join('');
        }

        function initFilters() {
          renderSourceFilterOptions();

          const categories = ['all', ...Array.from(new Set(data.items.map((item) => item.category || 'unknown'))).sort()];
          $('#categoryFilter').innerHTML = categories.map((category) => {
            const label = category === 'all' ? '全部分类' : category;
            return `<option value="${escapeHtml(category)}">${escapeHtml(label)}</option>`;
          }).join('');

          $('#searchInput').addEventListener('input', (event) => {
            state.search = event.target.value.trim().toLowerCase();
            renderItems();
          });
          $('#sourceFilter').addEventListener('change', (event) => {
            state.source = event.target.value;
            renderAll();
          });
          $('#categoryFilter').addEventListener('change', (event) => {
            state.category = event.target.value;
            renderItems();
          });
        }

        function renderUserPanelMeta(message = '') {
          const includeTerms = state.userTerms.include;
          const excludeTerms = state.userTerms.exclude;
          const toggle = $('#contextOnlyToggle');
          const toggleLabel = $('#contextToggleLabel');

          $('#userTermCount').textContent = `${includeTerms.length} 词`;
          toggle.checked = state.onlyUserRelevant;
          toggle.disabled = includeTerms.length === 0;
          toggleLabel.classList.toggle('disabled', includeTerms.length === 0);

          const preview = [
            ...includeTerms.slice(0, 8).map((term) => pill(term, 'blue')),
            ...excludeTerms.slice(0, 4).map((term) => pill(`排除 ${term}`, 'warn'))
          ];
          $('#userTermPreview').innerHTML = preview.length ? preview.join('') : '<span class="muted-note">暂无关键词</span>';
          $('#userMdStatus').textContent = message || `${contextMatchCount()} 条当前信息命中`;
        }

        function applyUserMd(value, message = '') {
          state.userMd = value;
          state.userTerms = parseUserMd(value);
          if (state.userTerms.include.length === 0) {
            state.onlyUserRelevant = false;
          }
          renderUserPanelMeta(message);
          renderAll();
        }

        function downloadUserMd() {
          const blob = new Blob([state.userMd], { type: 'text/markdown;charset=utf-8' });
          const url = URL.createObjectURL(blob);
          const link = document.createElement('a');
          link.href = url;
          link.download = 'user.md';
          document.body.append(link);
          link.click();
          link.remove();
          URL.revokeObjectURL(url);
        }

        function initUserPanel() {
          const input = $('#userMdInput');
          state.userTerms = parseUserMd(state.userMd);
          input.value = state.userMd;

          input.addEventListener('input', (event) => {
            applyUserMd(event.target.value);
          });
          $('#saveUserMd').addEventListener('click', () => {
            const saved = storeUserMd(state.userMd);
            renderUserPanelMeta(saved ? '已保存到本机浏览器' : '浏览器未允许保存');
          });
          $('#resetUserMd').addEventListener('click', () => {
            input.value = defaultUserMd();
            storeUserMd(input.value);
            applyUserMd(input.value, '已重置');
          });
          $('#downloadUserMd').addEventListener('click', () => {
            downloadUserMd();
            renderUserPanelMeta('已生成 user.md 下载');
          });
          $('#contextOnlyToggle').addEventListener('change', (event) => {
            state.onlyUserRelevant = event.target.checked;
            renderUserPanelMeta();
            renderHeader();
            renderItems();
          });

          renderUserPanelMeta();
        }

        function filteredItems() {
          return data.items.filter((item) => {
            const visibleSourceIds = visibleDataSourceIds();
            const sourceVisible = visibleSourceIds.includes(item.source_id);
            const sourceOk = state.source === 'all'
              ? sourceVisible
              : sourceVisible && item.source_id === state.source;
            const categoryOk = state.category === 'all' || (item.category || 'unknown') === state.category;
            const haystack = itemHaystack(item);
            const searchOk = !state.search || haystack.includes(state.search);
            const userOk = !state.onlyUserRelevant || contextForItem(item).relevant;
            return sourceOk && categoryOk && searchOk && userOk;
          });
        }

        function renderItems() {
          const items = filteredItems();
          if (!items.find((item) => item.id === state.activeItemId)) {
            state.activeItemId = items[0] ? items[0].id : null;
          }
          $('#itemList').innerHTML = items.length ? items.map((item) => {
            const context = contextForItem(item);
            return `
              <article class="item-card ${item.id === state.activeItemId ? 'active' : ''} ${context.relevant ? 'context-match' : ''}" data-item="${escapeHtml(item.id)}">
                <div class="source-meta">
                  ${pill(item.source_name || item.source_id)}
                  ${pill(item.category || 'unknown')}
                  ${(item.quality_flags || []).slice(0, 2).map((flag) => pill(flag, 'warn')).join('')}
                  ${context.hits.slice(0, 3).map((term) => pill(term, 'ok')).join('')}
                </div>
                <h3>${escapeHtml(item.title)}</h3>
                <p>${escapeHtml(item.summary || item.content || 'No summary captured.')}</p>
              </article>
            `;
          }).join('') : '<div class="empty-state">当前筛选条件下没有抓取信息。</div>';

          $('#itemList').querySelectorAll('.item-card').forEach((card) => {
            card.addEventListener('click', () => {
              state.activeItemId = card.dataset.item;
              renderItems();
            });
          });

          renderDetail(items);
        }

        function renderDetail(items) {
          const item = items.find((candidate) => candidate.id === state.activeItemId);
          const detail = $('#itemDetail');
          if (!item) {
            detail.innerHTML = '<div class="empty-state">选择左侧任意抓取信息查看详情。</div>';
            return;
          }
          const body = item.content || item.summary || 'No content captured.';
          const context = contextForItem(item);
          const contextHtml = context.hits.length > 0 ? `
            <div class="context-match-box">
              <strong>user.md 命中</strong>
              <div class="source-meta">
                ${context.hits.slice(0, 10).map((term) => pill(term, 'ok')).join('')}
                ${context.excluded.slice(0, 4).map((term) => pill(`排除 ${term}`, 'warn')).join('')}
              </div>
            </div>
          ` : `
            <div class="context-match-box">
              <strong>user.md 未命中</strong>
              <div class="context-status">该条信息暂未匹配当前关注对象与关键词。</div>
            </div>
          `;
          detail.innerHTML = `
            <div class="source-meta">
              ${pill(item.source_name || item.source_id, 'ok')}
              ${pill(item.provider)}
              ${pill(formatTime(item.fetched_at))}
            </div>
            <h2>${escapeHtml(item.title)}</h2>
            ${contextHtml}
            <div class="detail-body">${escapeHtml(body)}</div>
            <div class="source-meta" style="margin-top:16px">
              ${(item.tags || []).slice(0, 8).map((tag) => pill(tag)).join('')}
            </div>
            ${item.link ? `<a class="detail-link" href="${escapeHtml(item.link)}" target="_blank" rel="noreferrer">打开原文</a>` : ''}
          `;
        }

        function renderAll() {
          renderSources();
          renderHeader();
          renderItems();
        }

        initFilters();
        initUserPanel();
        renderAll();
      </script>
    </body>
    </html>
  HTML
end

def render_html(payload)
  data_json = JSON.generate(payload).gsub("</", "<\\/")
  ERB.new(dashboard_template).result_with_hash(data_json: data_json)
end

def main(argv)
  options = parse_options(argv)
  payload = build_payload(options)
  html = render_html(payload)

  FileUtils.mkdir_p(File.dirname(options["output"]))
  File.write(options["output"], html)

  puts JSON.pretty_generate(
    "output" => options["output"],
    "sources" => payload.dig("summary", "sources"),
    "canonical_items" => payload.dig("summary", "canonical_items")
  )
end

main(ARGV)
