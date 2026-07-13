import html
import math
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


DISPLAY_LABELS = {
    "ai-agent": "AI 智能体", "ai-coding": "AI 编程", "china-market": "中国市场",
    "context": "上下文", "creator-economy": "创作者经济", "developer-tools": "开发者工具",
    "github": "GitHub", "long-form": "长内容", "mcp": "MCP 协议",
    "meeting-intelligence": "会议智能", "investment-research": "投资研究",
    "open-source": "开源", "public-opinion": "公众讨论", "social-signal": "社交信号",
    "startup-signals": "创业信号", "trending": "趋势热点", "video": "视频内容",
    "AI Agent": "AI 智能体", "AI Coding": "AI 编程", "Context": "上下文",
    "Meeting Intelligence": "会议智能", "Investment Research": "投资研究",
    "Social Signal": "社交信号", "Open Source": "开源",
}


def present(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def clean_text(value: Any) -> str:
    if not present(value):
        return ""
    return re.sub(r"\s+", " ", html.unescape(str(value))).strip()


def listify(value: Any) -> list[Any]:
    if isinstance(value, list):
        return [item for item in value if item is not None]
    if value is None:
        return []
    return [value]


def includes_term(text: str, term: Any) -> bool:
    return present(term) and str(term).lower() in text.lower()


def content_blob(item: dict[str, Any]) -> str:
    return "\n".join(str(v) for v in [item.get("title"), item.get("summary"), item.get("content")] if v is not None)


def metadata_blob(item: dict[str, Any]) -> str:
    return "\n".join(str(v) for v in [" ".join(str(t) for t in listify(item.get("tags"))), item.get("category"), item.get("source_name"), item.get("provider")] if v is not None)


def keyword_matches(text: str, rules: dict[str, Any]) -> list[dict[str, Any]]:
    matches = []
    for rule in rules.get("keyword_rules", []):
        terms = []
        for term in listify(rule.get("terms")):
            if includes_term(text, term) and term not in terms:
                terms.append(term)
        if terms:
            matches.append({"tag": rule["tag"], "label": rule.get("label") or rule["tag"], "matched_terms": terms})
    return matches


def profile_terms(profile: dict[str, Any]) -> list[str]:
    terms = []
    terms.extend(listify(profile.get("interests")))
    terms.extend(listify(profile.get("watch_entities")))
    for goal in listify(profile.get("goals")):
        terms.append(goal.get("title"))
        terms.extend(listify(goal.get("keywords")))
    result = []
    for term in terms:
        cleaned = clean_text(term)
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def matched_profile_terms(text: str, profile: dict[str, Any]) -> list[str]:
    return [term for term in profile_terms(profile) if includes_term(text, term)]


def canonical_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fa5]+", "", clean_text(value).lower())


def source_tag_matches(item: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    item_terms = listify(item.get("tags")) + [item.get("category")]
    normalized = {}
    for term in item_terms:
        token = canonical_token(term)
        if present(token):
            normalized[token] = term
    matches = []
    for term in profile_terms(profile):
        profile_token = canonical_token(term)
        if not present(profile_token):
            continue
        for item_token, original in normalized.items():
            if item_token in profile_token or profile_token in item_token:
                matches.append(original)
    result = []
    for match in matches:
        if match not in result:
            result.append(match)
    return result


def negative_matches(text: str, profile: dict[str, Any]) -> list[str]:
    return [term for term in listify(profile.get("negative_preferences")) if includes_term(text, term)]


def parse_time(value: Any) -> datetime | None:
    if not present(value):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def recency_weight(item: dict[str, Any], rules: dict[str, Any], now: datetime) -> float:
    time = parse_time(item.get("published_at")) or parse_time(item.get("fetched_at"))
    recency = rules.get("scoring", {}).get("recency", {})
    if not time:
        return float(recency.get("unknown", 0))
    if time.tzinfo and not now.tzinfo:
        now = now.astimezone()
    days = abs((now - time).total_seconds() / 86400.0)
    if days < 1:
        return float(recency.get("same_day", 0))
    if days <= 3:
        return float(recency.get("within_3_days", 0))
    return float(recency.get("older", 0))


def clamp_score(value: float, rules: dict[str, Any]) -> int:
    clamp = rules.get("scoring", {}).get("clamp", {})
    rounded = math.floor(value + 0.5)
    return min(max(rounded, clamp.get("min", 1)), clamp.get("max", 5))


def score_importance(item: dict[str, Any], matches: list[dict[str, Any]], rules: dict[str, Any], now: datetime):
    scoring = rules.get("scoring", {})
    source_signal = float(scoring.get("priority_weights", {}).get(item.get("priority") or "medium", 0)) + float(scoring.get("source_type_weights", {}).get(item.get("source_type") or "rss", 0)) + recency_weight(item, rules, now)
    tag_signal = 0.3 if len(listify(item.get("tags"))) > 0 else 0.0
    keyword_signal = min(len(matches) * 0.45, 1.8)
    content_signal = 0.4 if len(clean_text(item.get("summary"))) > 120 or len(clean_text(item.get("content"))) > 240 else 0.0
    score = clamp_score(1.0 + source_signal + tag_signal + keyword_signal + content_signal, rules)
    factors = []
    if item.get("priority") == "high":
        factors.append("高优先级来源")
    if recency_weight(item, rules, now) >= 0.5:
        factors.append("近期抓取")
    if matches:
        factors.append(f"匹配 {len(matches)} 个主题规则")
    if content_signal > 0:
        factors.append("内容信息量较高")
    return score, factors


def score_relevance(item: dict[str, Any], matches, profile_matches, tag_matches, negatives, rules):
    score = clamp_score(1.0 + min(len(matches) * 0.35, 1.4) + min(len(profile_matches) * 0.55, 2.2) + min(len(tag_matches) * 0.25, 0.8) - min(len(negatives) * 0.8, 1.6), rules)
    factors = []
    if profile_matches:
        factors.append(f"命中个人画像关键词：{', '.join(profile_matches[:5])}")
    if tag_matches:
        factors.append(f"来源标签贴近关注方向：{', '.join(str(t) for t in tag_matches[:5])}")
    if matches:
        factors.append(f"命中主题：{', '.join(match['label'] for match in matches[:5])}")
    if negatives:
        factors.append(f"包含排除偏好：{', '.join(str(n) for n in negatives)}")
    return score, factors


def extract_sentences(value: Any, max_sentences: int) -> list[str]:
    text = clean_text(value)
    if not present(text):
        return []
    sentences = re.split(r"(?<=[。！？.!?])\s+", text)
    if len(sentences) <= 1:
        sentences = [text]
    return [s.strip() for s in sentences if s.strip()][:max_sentences]


def truncate_display_text(value: Any, max_chars: int) -> str:
    text = clean_text(value)
    return text if len(text) <= max_chars else f"{text[: max_chars - 1].strip()}…"


def remove_source_prefix(value: Any) -> str:
    text = clean_text(value)
    text = re.sub(r"^(?:据|来自).{1,18}(?:报道|消息|称)[，,:：]\s*", "", text)
    text = re.sub(r"^(?:IT之家|新华社|红星新闻|环球网|新华网|中国新闻周刊)[\s\d月日号]*(?:消息|报道)?[，,:：]\s*", "", text)
    return re.sub(r"^[【\[][^】\]]{1,24}[】\]]\s*", "", text)


def display_label(value: Any) -> str:
    text = clean_text(value)
    return DISPLAY_LABELS.get(text) or DISPLAY_LABELS.get(text.replace("_", "-").lower()) or text


def github_item(item: dict[str, Any]) -> bool:
    return clean_text(item.get("provider")) == "github" or "github" in clean_text(item.get("source_id"))


def repository_short_name(item: dict[str, Any]) -> str:
    title = clean_text(item.get("title"))
    if "/" in title:
        return title.split("/", 1)[1]
    match = re.search(r"github\.com/[^/]+/([^/?#]+)", clean_text(item.get("normalized_link") or item.get("link")), re.I)
    return match.group(1) if match else ""


def without_github_metrics(value: Any) -> str:
    return re.sub(r"\s*Language:\s*.+?(?:\s+Stars:\s*[\d,]+)?(?:\s+Forks:\s*[\d,]+)?\s*$", "", remove_source_prefix(value), flags=re.I).strip()


def github_metric(value: Any, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}:\s*([^ ]+)", clean_text(value), re.I)
    return match.group(1) if match else ""


def format_count(value: Any) -> str:
    number = int(re.sub(r"\D", "", clean_text(value)) or 0)
    if not number:
        return ""
    return f"{number / 10_000:.1f} 万" if number >= 10_000 else f"{number:,}"


def github_metrics_sentence(value: Any) -> str:
    language = github_metric(value, "Language")
    stars = format_count(github_metric(value, "Stars"))
    forks = format_count(github_metric(value, "Forks"))
    parts = []
    if language:
        parts.append(f"主要语言 {language}")
    if stars:
        parts.append(f"约 {stars}星标" if "万" in stars else f"约 {stars} 星标")
    if forks:
        parts.append(f"{forks}分叉" if "万" in forks else f"{forks} 分叉")
    return "，".join(parts)


def localize_source_list(value: Any) -> str:
    return re.sub(r",\s*and the web$", " 和网页", clean_text(value), flags=re.I).replace(",", "、")


def rewrite_known_english_sentence(value: Any) -> str | None:
    text = re.sub(r"^π\s*", "", clean_text(value))
    patterns = [
        (r"^(.+?) delivers fully local long-term memory for AI Agents via a (\d+)-tier progressive pipeline, with zero external API dependencies\.?$", lambda m: f"{m[1]} 提供全本地 AI 智能体长期记忆，采用 {m[2]} 层渐进式流程且无外部 API 依赖"),
        (r"^Production-grade engineering skills for AI coding agents\.?$", lambda m: "面向 AI 编程智能体的生产级工程技能库"),
        (r"^AI agent skill that researches any topic across (.+?) - then synthesizes a grounded summary\.?$", lambda m: f"可在 {localize_source_list(m[1])} 等渠道调研任意主题并生成有依据摘要的 AI 智能体技能"),
        (r"^Instant, Concurrent, Secure & Lightweight Sandbox for AI Agents\.?$", lambda m: "面向 AI 智能体的即时、并发、安全、轻量沙箱"),
        (r"^Extracted system prompts from (.+)$", lambda m: f"整理来自 {m[1]} 的系统提示词"),
        (r"^(.+?) is the first and best Office suite purpose-built for AI agents to read, edit, and automate Word, Excel, and PowerPoint files\.?.*$", lambda m: f"{m[1]} 面向 AI 智能体读取、编辑和自动化 Word、Excel、PowerPoint 文件"),
        (r"^An agentic skills framework & software development methodology that works\.?$", lambda m: "可落地的智能体技能框架与软件开发方法论"),
        (r"^This is MCP server for Claude that gives it terminal control, file system search and diff file editing capabilities\.?$", lambda m: "为 Claude 提供终端控制、文件搜索和 diff 编辑能力的 MCP 服务器"),
        (r"^A Patch for GIMP 3\+ for Photoshop Users\.?$", lambda m: "面向 Photoshop 用户的 GIMP 3+ 适配补丁"),
        (r"^(.+?) turns commodity WiFi signals into real-time spatial intelligence, vital sign monitoring, and presence detection\s*[—-]\s*all without a single pixel of video\.?$", lambda m: f"{m[1]} 将普通 WiFi 信号转为实时空间智能、生命体征监测和存在检测，且无需视频画面"),
    ]
    for pattern, formatter in patterns:
        match = re.match(pattern, text, re.I)
        if match:
            return formatter(match)
    return None


def translate_common_tech_phrases(value: Any) -> str:
    text = clean_text(value)
    replacements = [
        (r"\bAI coding agents?\b", "AI 编程智能体"), (r"\bAI agents?\b", "AI 智能体"),
        (r"\bcoding agents?\b", "编程智能体"), (r"\bagentic skills?\b", "智能体技能"),
        (r"\bagentic\b", "智能体化"), (r"\bdeveloper tools?\b", "开发者工具"),
        (r"\blong-term memory\b", "长期记忆"), (r"\bmemory\b", "记忆"),
        (r"\bworkflow automation\b", "工作流自动化"), (r"\bopen source\b", "开源"),
        (r"\bself-hosted\b", "自托管"), (r"\bsecure\b", "安全"), (r"\blightweight\b", "轻量"),
        (r"\bsandbox\b", "沙箱"), (r"\bsystem prompts?\b", "系统提示词"),
        (r"\bfile system search\b", "文件系统搜索"), (r"\bterminal control\b", "终端控制"),
        (r"\bdiff file editing\b", "diff 文件编辑"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.I)
    return text


def special_chinese_display_summary(value: Any) -> str | None:
    return "围绕“300 行代码写 Cursor”的观点引发讨论，信号点在 AI 编程工具降低门槛后，开发者能力标准正在被重新讨论。" if re.search(r"300\s*行.*Cursor", clean_text(value), re.I) else None


def display_core_summary(item: dict[str, Any]) -> str:
    source = item.get("summary") if present(item.get("summary")) else item.get("content") or item.get("title")
    special = special_chinese_display_summary(source)
    if special:
        return special
    core = without_github_metrics(source)
    return rewrite_known_english_sentence(core) or rewrite_known_english_sentence((extract_sentences(core, 1) or [item.get("title", "")])[0]) or translate_common_tech_phrases((extract_sentences(core, 1) or [item.get("title", "")])[0])


def trim_subject_from_core(core: str, subject: str) -> str:
    for candidate in {subject, subject.replace("-", " ").replace("_", " ")} - {""}:
        core = re.sub(rf"^{re.escape(candidate)}\s*", "", core, flags=re.I)
    return core


def title_phrase_from_summary(summary: str) -> str:
    phrases = [("长期记忆", "主打全本地长期记忆"), ("生产级工程技能", "提供生产级工程技能库"), ("调研任意主题", "跨平台调研并合成摘要"), ("轻量沙箱", "提供轻量安全沙箱"), ("系统提示词", "整理主流 AI 系统提示词"), ("Office", "让智能体自动处理 Office 文件"), ("软件开发方法论", "提出智能体技能开发方法论"), ("MCP 服务器", "给 Claude 增加终端与文件能力"), ("GIMP", "贴近 Photoshop 用户的 GIMP 工作流"), ("WiFi", "用 WiFi 做空间与体征感知")]
    for term, phrase in phrases:
        if term in summary:
            return phrase
    if len(summary) <= 24:
        return summary
    return re.split(r"[，。；]", summary, maxsplit=1)[0]


def display_topic(context: dict[str, Any]) -> str | None:
    for key in ("matches", "profile_matches", "source_tag_matches"):
        values = context.get(key) or []
        if values:
            value = values[0].get("tag") or values[0].get("label") if isinstance(values[0], dict) else values[0]
            return display_label(value)
    return None


def display_title_for(item: dict[str, Any], context: dict[str, Any], rules: dict[str, Any]) -> str:
    source = item.get("summary") if present(item.get("summary")) else item.get("content") or item.get("title")
    subject = repository_short_name(item) if github_item(item) else ""
    candidate = "开发者能力门槛讨论升温" if re.search(r"300\s*行.*Cursor", clean_text(source), re.I) else title_phrase_from_summary(display_core_summary(item))
    if subject and subject not in candidate:
        candidate = f"{subject} {candidate}"
    topic = display_topic(context)
    max_chars = int(rules.get("recommendation", {}).get("max_display_title_chars", 42))
    candidate = truncate_display_text(candidate, max(max_chars - len(topic) - 1, 12) if topic else max_chars)
    return truncate_display_text(f"{topic}：{candidate}", max_chars) if topic and candidate else candidate


def display_summary_for(item: dict[str, Any], context: dict[str, Any], rules: dict[str, Any]) -> str:
    subject = repository_short_name(item) if github_item(item) else ""
    core = trim_subject_from_core(display_core_summary(item), subject)
    summary = f"开源项目 {subject}：{core}" if subject else core
    metrics = github_metrics_sentence(item.get("summary") if present(item.get("summary")) else item.get("content") or item.get("title"))
    if metrics:
        summary = f"{summary}；{metrics}"
    topic = display_topic(context)
    if topic and topic not in summary and not github_item(item):
        summary = f"这条内容与「{topic}」相关：{summary}"
    return truncate_display_text(summary, int(rules.get("recommendation", {}).get("max_display_summary_chars", 150)))


def summary_for(item: dict[str, Any], rules: dict[str, Any]) -> str:
    source = item.get("summary") if present(item.get("summary")) else item.get("content")
    sentences = extract_sentences(source, rules.get("recommendation", {}).get("max_summary_sentences", 2))
    return clean_text(item.get("title")) if not sentences else " ".join(sentences)


def recommended_questions(context: dict[str, Any], rules: dict[str, Any]) -> list[str]:
    questions = []
    if context["matches"]:
        questions.append(f"{context['matches'][0]['label']} 方向是否正在形成可复用的数据源、工作流或商业场景？")
    if context["profile_matches"]:
        questions.append(f"这个信号与「{context['profile_matches'][0]}」的当前目标有什么直接交集？")
    elif context["source_tag_matches"]:
        questions.append(f"这个信号与「{context['source_tag_matches'][0]}」这个关注方向有什么直接交集？")
    questions.extend(listify(rules.get("question_templates")))
    result = []
    for question in questions:
        if question not in result:
            result.append(question)
    return result[: rules.get("recommendation", {}).get("max_questions", 3)]


def risks_for(context: dict[str, Any], rules: dict[str, Any]) -> list[str]:
    risks = []
    if context["negative_matches"]:
        risks.append("命中了用户排除偏好，可能不值得继续追踪。")
    risks.extend(listify(rules.get("risk_templates")))
    result = []
    for risk in risks:
        if risk not in result:
            result.append(risk)
    return result[: rules.get("recommendation", {}).get("max_risks", 2)]


def compute_baseline_assessment(item: dict[str, Any], profile: dict[str, Any], rules: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Compute the version-1 deterministic assessment used by the current dashboard."""
    content_text = content_blob(item)
    full_text = "\n".join([content_text, metadata_blob(item)])
    matches = keyword_matches(content_text, rules)
    profile_matches = matched_profile_terms(content_text, profile)
    tag_matches = source_tag_matches(item, profile)
    negatives = negative_matches(full_text, profile)
    importance_score, importance_factors = score_importance(item, matches, rules, now)
    relevance_score, relevance_factors = score_relevance(item, matches, profile_matches, tag_matches, negatives, rules)
    context = {"matches": matches, "profile_matches": profile_matches, "source_tag_matches": tag_matches, "negative_matches": negatives}
    theme_text = "、".join(match["label"] for match in matches[:3])
    why_important = "；".join(part for part in [f"重要性 {importance_score}/5", f"主题集中在 {theme_text}" if present(theme_text) else None, "，".join(importance_factors) if importance_factors else None] if part)
    why_relevant = f"相关性 {relevance_score}/5；暂未命中强个人画像信号，适合作为背景观察。" if not relevance_factors else f"相关性 {relevance_score}/5；{'；'.join(relevance_factors)}"
    tags = []
    for tag in listify(item.get("tags")) + [match["tag"] for match in matches]:
        if tag not in tags:
            tags.append(tag)
    return {
        "id": item["id"],
        "title": item.get("title"),
        "display_title": display_title_for(item, context, rules),
        "display_summary": display_summary_for(item, context, rules),
        "source": {"id": item.get("source_id"), "name": item.get("source_name"), "provider": item.get("provider"), "type": item.get("source_type"), "priority": item.get("priority")},
        "link": item.get("normalized_link") or item.get("link"),
        "published_at": item.get("published_at"),
        "fetched_at": item.get("fetched_at"),
        "what_happened": summary_for(item, rules),
        "tags": tags,
        "matched_keywords": matches,
        "matched_profile_terms": profile_matches,
        "matched_source_tags": tag_matches,
        "negative_matches": negatives,
        "importance_score": importance_score,
        "importance_factors": importance_factors,
        "relevance_score": relevance_score,
        "relevance_factors": relevance_factors,
        "total_score": round((importance_score * 0.45) + (relevance_score * 0.55), 2),
        "why_important": why_important,
        "why_relevant": why_relevant,
        "recommended_questions": recommended_questions(context, rules),
        "risks": risks_for(context, rules),
        "quality_flags": item.get("quality_flags") or [],
    }


def build_signal(item: dict[str, Any], profile: dict[str, Any], rules: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Compatibility name retained for callers of the pre-L4 scorer."""
    return compute_baseline_assessment(item, profile, rules, now)


def build_signals(canonical: dict[str, Any], profile: dict[str, Any], rules: dict[str, Any], top_n: int, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now().astimezone()
    excluded_sources = listify(rules.get("filters", {}).get("excluded_sources"))
    excluded_categories = listify(rules.get("filters", {}).get("excluded_categories"))
    items = [item for item in canonical["items"] if item.get("source_id") not in excluded_sources and item.get("category") not in excluded_categories]
    signals = [build_signal(item, profile, rules, now) for item in items]
    min_relevance = rules.get("recommendation", {}).get("min_relevance_score", 1)
    signals = [signal for signal in signals if signal["relevance_score"] >= min_relevance]
    signals.sort(key=lambda signal: (-signal["total_score"], -signal["importance_score"], -signal["relevance_score"], str(signal.get("title"))))
    return signals[:top_n]


def build_output(canonical: dict[str, Any], profile: dict[str, Any], rules: dict[str, Any], generated_at: str | None = None, top_n: int | None = None) -> dict[str, Any]:
    top_n = top_n or profile.get("output_preferences", {}).get("default_top_n") or rules.get("recommendation", {}).get("top_n") or 10
    generated_at = generated_at or datetime.now().astimezone().isoformat()
    now = datetime.fromisoformat(generated_at)
    signals = build_signals(canonical, profile, rules, top_n, now=now)
    return {
        "contract_version": 1,
        "generated_at": generated_at,
        "input_run_id": canonical.get("run_id"),
        "profile_version": profile.get("version"),
        "rules_version": rules.get("version"),
        "summary": {"input_items": len(canonical["items"]), "signals": len(signals), "top_n": top_n},
        "signals": signals,
    }


def markdown_dashboard(output: dict[str, Any]) -> str:
    lines = ["# Founder Daily Intelligence - 信息聚合器", "", f"- 生成时间：{output['generated_at']}", f"- 输入批次：{output['input_run_id']}", f"- 推荐信号：{output['summary']['signals']}", ""]
    for index, signal in enumerate(output["signals"], 1):
        lines.extend([f"## {index}. {signal.get('display_title') or signal['title']}", "", f"- 来源：{signal['source']['name']} / {signal['source']['provider']}", f"- 评分：重要性 {signal['importance_score']}/5，相关性 {signal['relevance_score']}/5，总分 {signal['total_score']}", f"- 摘要：{signal.get('display_summary') or signal['what_happened']}", f"- 为什么重要：{signal['why_important']}", f"- 为什么与你有关：{signal['why_relevant']}", f"- 建议追问：{'；'.join(signal['recommended_questions'])}", f"- 风险/反例：{'；'.join(signal['risks'])}"])
        if present(signal.get("link")):
            lines.append(f"- 链接：{signal['link']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def html_dashboard(output: dict[str, Any]) -> str:
    return f"<!doctype html><html><head><meta charset=\"utf-8\"><title>Founder Daily Intelligence</title></head><body><h1>Founder Daily Intelligence</h1><p>推荐信号：{output['summary']['signals']}</p></body></html>\n"


def run(
    input_path: Path,
    profile_path: Path | None,
    rules_path: Path,
    output_path: Path,
    markdown_path: Path | None = None,
    html_path: Path | None = None,
    top_n: int | None = None,
    *,
    profile_override: dict[str, Any] | None = None,
    profile_id: str | None = None,
    profile_hash: str | None = None,
    profile_status: str | None = None,
) -> dict[str, Any]:
    canonical = json.loads(input_path.read_text(encoding="utf-8"))
    if profile_override is not None:
        profile = profile_override
    elif profile_path is not None:
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    else:
        profile = {}
    rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    output = build_output(canonical, profile, rules, top_n=top_n)
    if profile_status is not None:
        output["profile_status"] = profile_status
        output["profile_id"] = profile_id
        output["profile_hash"] = profile_hash
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown_dashboard(output), encoding="utf-8")
    if html_path:
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html_dashboard(output), encoding="utf-8")
    return output
