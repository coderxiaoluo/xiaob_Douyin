"""评论意向：本地规则词表打分（不做大模型）。"""
from __future__ import annotations

import json
import threading
from copy import deepcopy
from pathlib import Path

_lock = threading.RLock()

DEFAULT_RULES = {
    "enabled": True,
    "threshold": 1,
    "positive": [
        "怎么买", "多少钱", "价格", "求购", "想买", "有没有卖",
        "求带", "带我", "求教", "怎么学", "报课", "报名",
        "私", "私聊", "私信", "加我", "微信", "vx", "V信",
        "合作", "代理", "加盟", "咨询", "详情",
        "链接", "同款", "求同款", "在哪买",
    ],
    "negative": [
        "互粉", "互关", "抽奖", "转发抽", "广告勿扰",
        "骗子", "假的", "别信", "侮辱", "滚",
    ],
    "extra_positive": [],
    "extra_negative": [],
}


def default_rules() -> dict:
    return deepcopy(DEFAULT_RULES)


def load_intent_rules(path: Path | None = None) -> dict:
    base = default_rules()
    if path is None or not path.is_file():
        return base
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return base
    if not isinstance(raw, dict):
        return base
    out = default_rules()
    if "enabled" in raw:
        out["enabled"] = bool(raw["enabled"])
    if "threshold" in raw:
        try:
            out["threshold"] = max(1, int(raw["threshold"]))
        except (TypeError, ValueError):
            pass
    for key in ("positive", "negative", "extra_positive", "extra_negative"):
        value = raw.get(key)
        if isinstance(value, list):
            out[key] = [str(x).strip() for x in value if str(x).strip()]
    return out


def save_intent_rules(path: Path, rules: dict) -> dict:
    data = load_intent_rules(None)
    if isinstance(rules, dict):
        if "enabled" in rules:
            data["enabled"] = bool(rules["enabled"])
        if "threshold" in rules:
            data["threshold"] = max(1, int(rules["threshold"]))
        for key in ("positive", "negative", "extra_positive", "extra_negative"):
            if key in rules and isinstance(rules[key], list):
                data[key] = [str(x).strip() for x in rules[key] if str(x).strip()]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return data


def _word_list(rules: dict, *keys: str) -> list[str]:
    words = []
    seen = set()
    for key in keys:
        for word in rules.get(key) or []:
            w = str(word).strip()
            if not w or w in seen:
                continue
            seen.add(w)
            words.append(w)
    return words


def score_intent_text(text: str, rules: dict | None = None, *, bonus_words: list[str] | None = None) -> dict:
    """对评论文本打意向分。"""
    rules = rules or default_rules()
    text = str(text or "")
    if not rules.get("enabled", True):
        return {
            "intent_score": 0,
            "intent_labels": [],
            "is_intent": False,
            "intent_hits": [],
            "intent_blocked": [],
        }

    positive = _word_list(rules, "positive", "extra_positive")
    if bonus_words:
        for w in bonus_words:
            w = str(w).strip()
            if w and w not in positive:
                positive.append(w)
    negative = _word_list(rules, "negative", "extra_negative")

    hits = [w for w in positive if w and w in text]
    blocked = [w for w in negative if w and w in text]
    score = len(hits) - (2 * len(blocked) if blocked else 0)
    threshold = max(1, int(rules.get("threshold") or 1))
    is_intent = score >= threshold and not blocked
    labels = []
    if is_intent:
        labels.append("意向")
    if blocked:
        labels.append("风险")
    elif hits and not is_intent:
        labels.append("弱意向")
    return {
        "intent_score": score,
        "intent_labels": labels,
        "is_intent": bool(is_intent),
        "intent_hits": hits[:8],
        "intent_blocked": blocked[:8],
    }


def attach_intent(row: dict, rules: dict | None = None, *, bonus_words: list[str] | None = None) -> dict:
    """给公开评论字典挂上意向字段（原地更新并返回）。"""
    if not isinstance(row, dict):
        return row
    scored = score_intent_text(row.get("text") or "", rules, bonus_words=bonus_words)
    row.update(scored)
    return row


def bonus_words_from_agent(agent: dict | None) -> list[str]:
    """从 Agent 目标里抽一点品类词当正向加成。"""
    if not isinstance(agent, dict):
        return []
    goal = agent.get("goal") or {}
    parts = []
    for key in ("category", "brief"):
        value = str(goal.get(key) or "").strip()
        if value:
            parts.append(value)
    words = []
    for part in parts:
        for token in part.replace("，", " ").replace(",", " ").replace("/", " ").split():
            token = token.strip()
            if 2 <= len(token) <= 12:
                words.append(token)
    return words[:12]
