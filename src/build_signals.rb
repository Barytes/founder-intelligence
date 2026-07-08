#!/usr/bin/env ruby
# frozen_string_literal: true

require "cgi"
require "fileutils"
require "json"
require "optparse"
require "time"
require "yaml"

DEFAULT_OPTIONS = {
  "input" => "data/canonical-items/latest.json",
  "profile" => "config/user-profile.yml",
  "rules" => "config/signal-rules.yml",
  "output" => "data/signals/latest.json",
  "markdown" => "data/dashboard/latest.md",
  "html" => "data/dashboard/latest.html",
  "top_n" => nil
}.freeze

def parse_options(argv)
  options = DEFAULT_OPTIONS.dup

  OptionParser.new do |opts|
    opts.banner = "Usage: src/build_signals.rb [options]"
    opts.on("--input PATH", "Canonical items JSON path") { |value| options["input"] = value }
    opts.on("--profile PATH", "User profile YAML path, defaults to config/user-profile.yml") { |value| options["profile"] = value }
    opts.on("--rules PATH", "Signal rules YAML path, defaults to config/signal-rules.yml") { |value| options["rules"] = value }
    opts.on("--output PATH", "Signal JSON output path") { |value| options["output"] = value }
    opts.on("--markdown PATH", "Dashboard Markdown output path") { |value| options["markdown"] = value }
    opts.on("--html PATH", "Dashboard HTML output path") { |value| options["html"] = value }
    opts.on("--top-n N", Integer, "Number of top signals to output") { |value| options["top_n"] = value }
  end.parse!(argv)

  options
end

def present?(value)
  !(value.nil? || value.to_s.strip.empty?)
end

def clean_text(value)
  return "" unless present?(value)

  CGI.unescapeHTML(value.to_s).gsub(/\s+/, " ").strip
end

def list(value)
  case value
  when Array
    value.compact
  when nil
    []
  else
    [value]
  end
end

def normalize_term(value)
  clean_text(value).downcase
end

def content_blob(item)
  [
    item["title"],
    item["summary"],
    item["content"]
  ].compact.join("\n")
end

def metadata_blob(item)
  [
    list(item["tags"]).join(" "),
    item["category"],
    item["source_name"],
    item["provider"]
  ].compact.join("\n")
end

def includes_term?(text, term)
  return false unless present?(term)

  text.downcase.include?(term.downcase)
end

def keyword_matches(text, rules)
  rules.fetch("keyword_rules", []).each_with_object([]) do |rule, matches|
    terms = list(rule["terms"]).select { |term| includes_term?(text, term) }
    next if terms.empty?

    matches << {
      "tag" => rule.fetch("tag"),
      "label" => rule["label"] || rule.fetch("tag"),
      "matched_terms" => terms.uniq
    }
  end
end

def profile_terms(profile)
  terms = []

  list(profile["interests"]).each { |value| terms << value }
  list(profile["watch_entities"]).each { |value| terms << value }

  list(profile["goals"]).each do |goal|
    terms << goal["title"]
    list(goal["keywords"]).each { |value| terms << value }
  end

  terms.compact.map { |term| clean_text(term) }.reject(&:empty?).uniq
end

def matched_profile_terms(text, profile)
  profile_terms(profile).select { |term| includes_term?(text, term) }
end

def canonical_token(value)
  normalize_term(value).gsub(/[^a-z0-9\u4e00-\u9fa5]+/, "")
end

def source_tag_matches(item, profile)
  item_terms = (list(item["tags"]) + [item["category"]]).compact
  normalized_item_terms = item_terms.each_with_object({}) do |term, map|
    token = canonical_token(term)
    map[token] = term if present?(token)
  end

  profile_terms(profile).each_with_object([]) do |term, matches|
    profile_token = canonical_token(term)
    next unless present?(profile_token)

    normalized_item_terms.each do |item_token, original|
      next unless item_token.include?(profile_token) || profile_token.include?(item_token)

      matches << original
    end
  end.uniq
end

def negative_matches(text, profile)
  list(profile["negative_preferences"]).select { |term| includes_term?(text, term) }
end

def priority_weight(item, rules)
  priority = item["priority"] || "medium"
  rules.dig("scoring", "priority_weights", priority).to_f
end

def source_type_weight(item, rules)
  source_type = item["source_type"] || "rss"
  rules.dig("scoring", "source_type_weights", source_type).to_f
end

def parse_time(value)
  return nil unless present?(value)

  Time.parse(value.to_s)
rescue ArgumentError
  nil
end

def recency_weight(item, rules, now)
  time = parse_time(item["published_at"]) || parse_time(item["fetched_at"])
  return rules.dig("scoring", "recency", "unknown").to_f unless time

  days = ((now - time) / 86_400.0).abs
  if days < 1
    rules.dig("scoring", "recency", "same_day").to_f
  elsif days <= 3
    rules.dig("scoring", "recency", "within_3_days").to_f
  else
    rules.dig("scoring", "recency", "older").to_f
  end
end

def clamp_score(value, rules)
  min = rules.dig("scoring", "clamp", "min") || 1
  max = rules.dig("scoring", "clamp", "max") || 5
  [[value.round, min].max, max].min
end

def score_importance(item, keyword_matches, rules, now)
  base = 1.0
  source_signal = priority_weight(item, rules) + source_type_weight(item, rules) + recency_weight(item, rules, now)
  tag_signal = list(item["tags"]).length.positive? ? 0.3 : 0.0
  keyword_signal = [keyword_matches.length * 0.45, 1.8].min
  content_signal = clean_text(item["summary"]).length > 120 || clean_text(item["content"]).length > 240 ? 0.4 : 0.0

  score = clamp_score(base + source_signal + tag_signal + keyword_signal + content_signal, rules)
  factors = []
  factors << "高优先级来源" if item["priority"] == "high"
  factors << "近期抓取" if recency_weight(item, rules, now) >= 0.5
  factors << "匹配 #{keyword_matches.length} 个主题规则" if keyword_matches.length.positive?
  factors << "内容信息量较高" if content_signal.positive?

  [score, factors]
end

def score_relevance(item, matches, profile_matches, source_tag_matches, negatives, rules)
  base = 1.0
  keyword_signal = [matches.length * 0.35, 1.4].min
  profile_signal = [profile_matches.length * 0.55, 2.2].min
  source_tag_signal = [source_tag_matches.length * 0.25, 0.8].min
  negative_penalty = [negatives.length * 0.8, 1.6].min

  score = clamp_score(base + keyword_signal + profile_signal + source_tag_signal - negative_penalty, rules)
  factors = []
  factors << "命中个人画像关键词：#{profile_matches.first(5).join(", ")}" unless profile_matches.empty?
  factors << "来源标签贴近关注方向：#{source_tag_matches.first(5).join(", ")}" unless source_tag_matches.empty?
  factors << "命中主题：#{matches.map { |match| match["label"] }.first(5).join(", ")}" unless matches.empty?
  factors << "包含排除偏好：#{negatives.join(", ")}" unless negatives.empty?

  [score, factors]
end

def extract_sentences(value, max_sentences)
  text = clean_text(value)
  return [] unless present?(text)

  sentences = text.split(/(?<=[。！？.!?])\s+/)
  sentences = [text] if sentences.length <= 1
  sentences.map(&:strip).reject(&:empty?).first(max_sentences)
end

def summary_for(item, rules)
  max_sentences = rules.dig("recommendation", "max_summary_sentences") || 2
  source = present?(item["summary"]) ? item["summary"] : item["content"]
  sentences = extract_sentences(source, max_sentences)
  return clean_text(item["title"]) if sentences.empty?

  sentences.join(" ")
end

def why_important(item, importance_score, factors, matches)
  theme_text = matches.map { |match| match["label"] }.first(3).join("、")
  parts = []
  parts << "重要性 #{importance_score}/5"
  parts << "主题集中在 #{theme_text}" if present?(theme_text)
  parts << factors.join("，") unless factors.empty?
  parts.join("；")
end

def why_relevant(relevance_score, factors)
  return "相关性 #{relevance_score}/5；暂未命中强个人画像信号，适合作为背景观察。" if factors.empty?

  "相关性 #{relevance_score}/5；#{factors.join("；")}"
end

def recommended_questions(signal_context, rules)
  templates = list(rules.dig("question_templates"))
  max_questions = rules.dig("recommendation", "max_questions") || 3
  questions = []

  if signal_context["matches"].any?
    label = signal_context["matches"].first["label"]
    questions << "#{label} 方向是否正在形成可复用的数据源、工作流或商业场景？"
  end

  if signal_context["profile_matches"].any?
    term = signal_context["profile_matches"].first
    questions << "这个信号与「#{term}」的当前目标有什么直接交集？"
  elsif signal_context["source_tag_matches"].any?
    term = signal_context["source_tag_matches"].first
    questions << "这个信号与「#{term}」这个关注方向有什么直接交集？"
  end

  questions.concat(templates)
  questions.uniq.first(max_questions)
end

def risks_for(signal_context, rules)
  max_risks = rules.dig("recommendation", "max_risks") || 2
  risks = []
  risks << "命中了用户排除偏好，可能不值得继续追踪。" unless signal_context["negative_matches"].empty?
  risks.concat(list(rules.dig("risk_templates")))
  risks.uniq.first(max_risks)
end

def build_signal(item, profile, rules, now)
  content_text = content_blob(item)
  full_text = [content_text, metadata_blob(item)].join("\n")
  matches = keyword_matches(content_text, rules)
  profile_matches = matched_profile_terms(content_text, profile)
  tag_matches = source_tag_matches(item, profile)
  negatives = negative_matches(full_text, profile)
  importance_score, importance_factors = score_importance(item, matches, rules, now)
  relevance_score, relevance_factors = score_relevance(item, matches, profile_matches, tag_matches, negatives, rules)
  signal_context = {
    "matches" => matches,
    "profile_matches" => profile_matches,
    "source_tag_matches" => tag_matches,
    "negative_matches" => negatives
  }

  {
    "id" => item.fetch("id"),
    "title" => item["title"],
    "source" => {
      "id" => item["source_id"],
      "name" => item["source_name"],
      "provider" => item["provider"],
      "type" => item["source_type"],
      "priority" => item["priority"]
    },
    "link" => item["normalized_link"] || item["link"],
    "published_at" => item["published_at"],
    "fetched_at" => item["fetched_at"],
    "what_happened" => summary_for(item, rules),
    "tags" => (list(item["tags"]) + matches.map { |match| match["tag"] }).uniq,
    "matched_keywords" => matches,
    "matched_profile_terms" => profile_matches,
    "matched_source_tags" => tag_matches,
    "negative_matches" => negatives,
    "importance_score" => importance_score,
    "importance_factors" => importance_factors,
    "relevance_score" => relevance_score,
    "relevance_factors" => relevance_factors,
    "total_score" => ((importance_score * 0.45) + (relevance_score * 0.55)).round(2),
    "why_important" => why_important(item, importance_score, importance_factors, matches),
    "why_relevant" => why_relevant(relevance_score, relevance_factors),
    "recommended_questions" => recommended_questions(signal_context, rules),
    "risks" => risks_for(signal_context, rules),
    "quality_flags" => item["quality_flags"] || []
  }
end

def build_signals(canonical, profile, rules, top_n)
  now = Time.now
  min_relevance = rules.dig("recommendation", "min_relevance_score") || 1
  excluded_sources = list(rules.dig("filters", "excluded_sources"))
  excluded_categories = list(rules.dig("filters", "excluded_categories"))

  items = canonical.fetch("items").reject do |item|
    excluded_sources.include?(item["source_id"]) || excluded_categories.include?(item["category"])
  end

  signals = items.map do |item|
    build_signal(item, profile, rules, now)
  end

  signals = signals.select { |signal| signal["relevance_score"] >= min_relevance }
  signals.sort_by! { |signal| [-signal["total_score"], -signal["importance_score"], -signal["relevance_score"], signal["title"].to_s] }
  signals.first(top_n)
end

def ensure_parent(path)
  FileUtils.mkdir_p(File.dirname(path)) if present?(path)
end

def markdown_dashboard(output)
  lines = []
  lines << "# Founder Daily Intelligence - 信息聚合器"
  lines << ""
  lines << "- 生成时间：#{output["generated_at"]}"
  lines << "- 输入批次：#{output["input_run_id"]}"
  lines << "- 推荐信号：#{output["summary"]["signals"]}"
  lines << ""

  output.fetch("signals").each_with_index do |signal, index|
    lines << "## #{index + 1}. #{signal["title"]}"
    lines << ""
    lines << "- 来源：#{signal.dig("source", "name")} / #{signal.dig("source", "provider")}"
    lines << "- 评分：重要性 #{signal["importance_score"]}/5，相关性 #{signal["relevance_score"]}/5，总分 #{signal["total_score"]}"
    lines << "- 发生了什么：#{signal["what_happened"]}"
    lines << "- 为什么重要：#{signal["why_important"]}"
    lines << "- 为什么与你有关：#{signal["why_relevant"]}"
    lines << "- 建议追问：#{list(signal["recommended_questions"]).join("；")}"
    lines << "- 风险/反例：#{list(signal["risks"]).join("；")}"
    lines << "- 链接：#{signal["link"]}" if present?(signal["link"])
    lines << ""
  end

  "#{lines.join("\n")}\n"
end

def html_escape(value)
  CGI.escapeHTML(value.to_s)
end

def html_list(items)
  return "<p class=\"muted\">暂无</p>" if list(items).empty?

  "<ul>#{list(items).map { |item| "<li>#{html_escape(item)}</li>" }.join}</ul>"
end

def html_dashboard(output)
  cards = output.fetch("signals").each_with_index.map do |signal, index|
    tags = list(signal["tags"]).first(8).map { |tag| "<span class=\"tag\">#{html_escape(tag)}</span>" }.join
    link = present?(signal["link"]) ? "<a href=\"#{html_escape(signal["link"])}\" target=\"_blank\" rel=\"noreferrer\">原文</a>" : ""

    <<~HTML
      <article class="card">
        <div class="card-top">
          <span class="rank">#{index + 1}</span>
          <div>
            <h2>#{html_escape(signal["title"])}</h2>
            <p class="source">#{html_escape(signal.dig("source", "name"))} · #{html_escape(signal.dig("source", "provider"))} #{link}</p>
          </div>
        </div>
        <div class="score-row">
          <span>重要性 #{signal["importance_score"]}/5</span>
          <span>相关性 #{signal["relevance_score"]}/5</span>
          <span>总分 #{signal["total_score"]}</span>
        </div>
        <p class="summary">#{html_escape(signal["what_happened"])}</p>
        <section>
          <h3>为什么重要</h3>
          <p>#{html_escape(signal["why_important"])}</p>
        </section>
        <section>
          <h3>为什么与你有关</h3>
          <p>#{html_escape(signal["why_relevant"])}</p>
        </section>
        <section class="grid">
          <div>
            <h3>建议追问</h3>
            #{html_list(signal["recommended_questions"])}
          </div>
          <div>
            <h3>风险/反例</h3>
            #{html_list(signal["risks"])}
          </div>
        </section>
        <div class="tags">#{tags}</div>
      </article>
    HTML
  end.join("\n")

  <<~HTML
    <!doctype html>
    <html lang="zh-CN">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Founder Daily Intelligence</title>
      <style>
        :root {
          color-scheme: light;
          --bg: #f6f7f3;
          --ink: #1e2528;
          --muted: #647075;
          --line: #d9ded8;
          --panel: #ffffff;
          --accent: #276c64;
          --accent-soft: #e5f1ee;
          --warn: #9a5b21;
        }
        * { box-sizing: border-box; }
        body {
          margin: 0;
          background: var(--bg);
          color: var(--ink);
          font-family: Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
          line-height: 1.5;
        }
        header {
          padding: 32px 24px 20px;
          border-bottom: 1px solid var(--line);
          background: #fbfcf9;
        }
        .wrap {
          max-width: 1080px;
          margin: 0 auto;
        }
        h1 {
          margin: 0 0 8px;
          font-size: 28px;
          font-weight: 700;
          letter-spacing: 0;
        }
        .meta {
          display: flex;
          flex-wrap: wrap;
          gap: 10px 18px;
          color: var(--muted);
          font-size: 14px;
        }
        main {
          padding: 24px;
        }
        .card {
          background: var(--panel);
          border: 1px solid var(--line);
          border-radius: 8px;
          padding: 20px;
          margin-bottom: 16px;
        }
        .card-top {
          display: grid;
          grid-template-columns: 40px 1fr;
          gap: 12px;
          align-items: start;
        }
        .rank {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 32px;
          height: 32px;
          border-radius: 50%;
          background: var(--accent);
          color: white;
          font-weight: 700;
        }
        h2 {
          margin: 0;
          font-size: 20px;
          line-height: 1.35;
          letter-spacing: 0;
        }
        .source {
          margin: 6px 0 0;
          color: var(--muted);
          font-size: 14px;
        }
        a {
          color: var(--accent);
          font-weight: 700;
          text-decoration: none;
        }
        .score-row {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin: 16px 0;
        }
        .score-row span {
          background: var(--accent-soft);
          color: var(--accent);
          border: 1px solid #c8e1da;
          border-radius: 999px;
          padding: 5px 10px;
          font-size: 13px;
          font-weight: 700;
        }
        .summary {
          margin: 0 0 16px;
          font-size: 15px;
        }
        h3 {
          margin: 0 0 6px;
          font-size: 14px;
          letter-spacing: 0;
          color: #2f3a3d;
        }
        section {
          margin-top: 14px;
        }
        section p {
          margin: 0;
          color: #313b3f;
        }
        .grid {
          display: grid;
          grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
          gap: 16px;
        }
        ul {
          margin: 0;
          padding-left: 18px;
        }
        li {
          margin-bottom: 4px;
        }
        .tags {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          margin-top: 16px;
        }
        .tag {
          border: 1px solid var(--line);
          border-radius: 999px;
          padding: 4px 8px;
          color: var(--muted);
          font-size: 12px;
        }
        .muted {
          color: var(--muted);
          margin: 0;
        }
        @media (max-width: 720px) {
          header, main { padding-left: 16px; padding-right: 16px; }
          h1 { font-size: 24px; }
          .grid { grid-template-columns: 1fr; }
          .card { padding: 16px; }
        }
      </style>
    </head>
    <body>
      <header>
        <div class="wrap">
          <h1>Founder Daily Intelligence</h1>
          <div class="meta">
            <span>生成时间：#{html_escape(output["generated_at"])}</span>
            <span>输入批次：#{html_escape(output["input_run_id"])}</span>
            <span>推荐信号：#{output.dig("summary", "signals")}</span>
          </div>
        </div>
      </header>
      <main>
        <div class="wrap">
          #{cards}
        </div>
      </main>
    </body>
    </html>
  HTML
end

def main(argv)
  options = parse_options(argv)
  canonical = JSON.parse(File.read(options["input"]))
  profile = YAML.load_file(options["profile"])
  rules = YAML.load_file(options["rules"])
  top_n = options["top_n"] || profile.dig("output_preferences", "default_top_n") || rules.dig("recommendation", "top_n") || 10
  signals = build_signals(canonical, profile, rules, top_n)

  output = {
    "contract_version" => 1,
    "generated_at" => Time.now.iso8601,
    "input_run_id" => canonical["run_id"],
    "profile_version" => profile["version"],
    "rules_version" => rules["version"],
    "summary" => {
      "input_items" => canonical.fetch("items").length,
      "signals" => signals.length,
      "top_n" => top_n
    },
    "signals" => signals
  }

  ensure_parent(options["output"])
  File.write(options["output"], "#{JSON.pretty_generate(output)}\n")

  if present?(options["markdown"])
    ensure_parent(options["markdown"])
    File.write(options["markdown"], markdown_dashboard(output))
  end

  if present?(options["html"])
    ensure_parent(options["html"])
    File.write(options["html"], html_dashboard(output))
  end

  puts JSON.pretty_generate(output["summary"])
end

main(ARGV)
