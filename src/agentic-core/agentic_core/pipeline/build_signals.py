import html
import math
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


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


def build_signal(item: dict[str, Any], profile: dict[str, Any], rules: dict[str, Any], now: datetime) -> dict[str, Any]:
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
        lines.extend([f"## {index}. {signal['title']}", "", f"- 来源：{signal['source']['name']} / {signal['source']['provider']}", f"- 评分：重要性 {signal['importance_score']}/5，相关性 {signal['relevance_score']}/5，总分 {signal['total_score']}", f"- 发生了什么：{signal['what_happened']}", f"- 为什么重要：{signal['why_important']}", f"- 为什么与你有关：{signal['why_relevant']}", f"- 建议追问：{'；'.join(signal['recommended_questions'])}", f"- 风险/反例：{'；'.join(signal['risks'])}"])
        if present(signal.get("link")):
            lines.append(f"- 链接：{signal['link']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def html_dashboard(output: dict[str, Any]) -> str:
    return f"<!doctype html><html><head><meta charset=\"utf-8\"><title>Founder Daily Intelligence</title></head><body><h1>Founder Daily Intelligence</h1><p>推荐信号：{output['summary']['signals']}</p></body></html>\n"


def run(input_path: Path, profile_path: Path, rules_path: Path, output_path: Path, markdown_path: Path | None = None, html_path: Path | None = None, top_n: int | None = None) -> dict[str, Any]:
    canonical = json.loads(input_path.read_text(encoding="utf-8"))
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    output = build_output(canonical, profile, rules, top_n=top_n)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown_dashboard(output), encoding="utf-8")
    if html_path:
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html_dashboard(output), encoding="utf-8")
    return output
