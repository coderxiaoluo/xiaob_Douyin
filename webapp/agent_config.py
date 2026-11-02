"""多模态引流 Agent 配置：目标卡、工具开关、配额与安全闸门。"""
from __future__ import annotations

from copy import deepcopy

FUNNELS = ("comment", "dm", "profile")
TOOL_KEYS = (
    "gen_video", "gen_cover", "publish_video",
    "comment", "hot_reply", "dm_reply",
)

DEFAULT_AGENT = {
    "enabled": False,
    "goal": {
        "category": "",
        "daily_videos": 1,
        "funnel": "comment",
        "brief": "",
    },
    "persona": {
        "tone": "轻松专业",
        "forbidden": "硬广、保证收益、诱导私下转账、辱骂挑衅",
    },
    "tools": {key: False for key in TOOL_KEYS},
    "quotas": {
        "max_publish_per_day": 3,
        "max_comments_per_day": 20,
        "max_dm_per_day": 10,
        "min_action_interval_sec": 180,
    },
    "engage": {
        "work_min_digg": 0,
        "comment_min_digg": 0,
        "comment_keyword": "",
        "comment_exclude": "",
        "max_comments_per_work": 5,
        "intent_only": False,
    },
    "safety": {
        "require_manual_confirm": True,
        "sensitive_word_check": True,
        "cooldown_after_errors": 3,
    },
}


def _text(value, *, field, limit):
    if not isinstance(value, str):
        raise ValueError(f"{field} 应为文本")
    if len(value) > limit:
        raise ValueError(f"{field} 过长，最多 {limit} 字")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in value):
        raise ValueError(f"{field} 含非法控制字符")
    return value


def _bool(value, field):
    if type(value) is not bool:
        raise ValueError(f"{field} 应为布尔值")
    return value


def _int(value, *, field, minimum, maximum):
    if type(value) is bool or not isinstance(value, int):
        raise ValueError(f"{field} 应为整数")
    if value < minimum or value > maximum:
        raise ValueError(f"{field} 应在 {minimum}–{maximum}")
    return value


def default_agent_config():
    return deepcopy(DEFAULT_AGENT)


def normalize_agent_config(raw=None):
    """把残缺配置补齐为完整结构，不做严格校验。"""
    base = default_agent_config()
    if not isinstance(raw, dict):
        return base
    if "enabled" in raw:
        base["enabled"] = bool(raw["enabled"])
    for section in ("goal", "persona", "tools", "quotas", "engage", "safety"):
        incoming = raw.get(section)
        if not isinstance(incoming, dict):
            continue
        for key, current in base[section].items():
            if key not in incoming:
                continue
            value = incoming[key]
            if isinstance(current, bool):
                base[section][key] = bool(value)
            elif isinstance(current, int):
                try:
                    base[section][key] = int(value)
                except (TypeError, ValueError):
                    pass
            elif isinstance(current, str) and isinstance(value, str):
                base[section][key] = value
    return base


def validate_agent_config(raw):
    """校验并返回可落盘的 Agent 配置。"""
    if not isinstance(raw, dict):
        raise ValueError("Agent 配置应为 JSON 对象")
    data = normalize_agent_config(raw)
    data["enabled"] = _bool(raw.get("enabled", data["enabled"]), "enabled")

    goal = raw.get("goal", data["goal"])
    if not isinstance(goal, dict):
        raise ValueError("goal 应为对象")
    data["goal"] = {
        "category": _text(goal.get("category", ""), field="品类", limit=64).strip(),
        "daily_videos": _int(goal.get("daily_videos", 1), field="日产量", minimum=0, maximum=20),
        "funnel": _text(goal.get("funnel", "comment"), field="承接方式", limit=16).strip(),
        "brief": _text(goal.get("brief", ""), field="任务目标", limit=2000).strip(),
    }
    if data["goal"]["funnel"] not in FUNNELS:
        raise ValueError("承接方式仅支持 comment / dm / profile")

    persona = raw.get("persona", data["persona"])
    if not isinstance(persona, dict):
        raise ValueError("persona 应为对象")
    data["persona"] = {
        "tone": _text(persona.get("tone", ""), field="语气", limit=64).strip() or "轻松专业",
        "forbidden": _text(persona.get("forbidden", ""), field="禁区", limit=500).strip(),
    }

    tools = raw.get("tools", data["tools"])
    if not isinstance(tools, dict):
        raise ValueError("tools 应为对象")
    data["tools"] = {
        key: _bool(tools.get(key, False), f"tools.{key}") for key in TOOL_KEYS
    }

    quotas = raw.get("quotas", data["quotas"])
    if not isinstance(quotas, dict):
        raise ValueError("quotas 应为对象")
    data["quotas"] = {
        "max_publish_per_day": _int(
            quotas.get("max_publish_per_day", 3), field="日发布上限", minimum=0, maximum=50),
        "max_comments_per_day": _int(
            quotas.get("max_comments_per_day", 20), field="日评论上限", minimum=0, maximum=500),
        "max_dm_per_day": _int(
            quotas.get("max_dm_per_day", 10), field="日私信上限", minimum=0, maximum=200),
        "min_action_interval_sec": _int(
            quotas.get("min_action_interval_sec", 180), field="最短间隔秒", minimum=30, maximum=3600),
    }

    engage = raw.get("engage", data.get("engage") or {})
    if not isinstance(engage, dict):
        raise ValueError("engage 应为对象")
    data["engage"] = {
        "work_min_digg": _int(
            engage.get("work_min_digg", 0), field="作品最低赞", minimum=0, maximum=10_000_000),
        "comment_min_digg": _int(
            engage.get("comment_min_digg", 0), field="评论最低赞", minimum=0, maximum=10_000_000),
        "comment_keyword": _text(
            engage.get("comment_keyword", ""), field="评论含关键词", limit=64).strip(),
        "comment_exclude": _text(
            engage.get("comment_exclude", ""), field="评论排除词", limit=64).strip(),
        "max_comments_per_work": _int(
            engage.get("max_comments_per_work", 5), field="每作品评论上限", minimum=1, maximum=30),
        "intent_only": _bool(engage.get("intent_only", False), "engage.intent_only"),
    }

    safety = raw.get("safety", data["safety"])
    if not isinstance(safety, dict):
        raise ValueError("safety 应为对象")
    data["safety"] = {
        "require_manual_confirm": _bool(
            safety.get("require_manual_confirm", True), "safety.require_manual_confirm"),
        "sensitive_word_check": _bool(
            safety.get("sensitive_word_check", True), "safety.sensitive_word_check"),
        "cooldown_after_errors": _int(
            safety.get("cooldown_after_errors", 3), field="连续失败冷却阈值", minimum=1, maximum=20),
    }

    # 私信风险最高：开启时强制人工确认门，避免误开裸奔。
    if data["tools"]["dm_reply"] and not data["safety"]["require_manual_confirm"]:
        raise ValueError("开启私信承接时必须同时开启「发布前人工确认」")
    if data["enabled"] and data["goal"]["daily_videos"] > data["quotas"]["max_publish_per_day"]:
        raise ValueError("日产量不能超过日发布上限")
    return data
