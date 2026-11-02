"""plan.v1：由 Agent 策略生成只读执行计划（预览，不落地执行）。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from .agent_config import TOOL_KEYS, normalize_agent_config, validate_agent_config

PLAN_SCHEMA = "plan.v1"

FUNNEL_LABEL = {
    "comment": "评论区互动",
    "dm": "私信承接",
    "profile": "主页引流",
}

TOOL_META = {
    "gen_video": {
        "title": "生成视频",
        "kind": "produce",
        "write": False,
        "desc": "按今日目标生成短视频脚本/成片候选",
    },
    "gen_cover": {
        "title": "生成封面",
        "kind": "produce",
        "write": False,
        "desc": "为成片生成封面图候选",
    },
    "publish_video": {
        "title": "发布视频",
        "kind": "publish",
        "write": True,
        "desc": "将成片发布到抖音",
        "quota": "publish",
    },
    "comment": {
        "title": "评论互动",
        "kind": "engage",
        "write": True,
        "desc": "在相关作品评论区互动引流",
        "quota": "comments",
    },
    "hot_reply": {
        "title": "热评回复",
        "kind": "engage",
        "write": True,
        "desc": "回复热门评论，提高曝光",
        "quota": "comments",
    },
    "dm_reply": {
        "title": "私信承接",
        "kind": "engage",
        "write": True,
        "desc": "对意向用户进行私信承接",
        "quota": "dm",
    },
}

# 计划步骤顺序：先生产后发布再互动
TOOL_ORDER = ("gen_video", "gen_cover", "publish_video", "comment", "hot_reply", "dm_reply")


def _now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def build_plan_from_agent(raw_agent) -> dict:
    """根据策略生成 plan.v1。不执行任何写操作。"""
    agent = validate_agent_config(normalize_agent_config(raw_agent))
    goal = agent["goal"]
    tools = agent["tools"]
    quotas = agent["quotas"]
    safety = agent["safety"]
    enabled_tools = [key for key in TOOL_ORDER if tools.get(key)]

    steps = []
    for index, key in enumerate(enabled_tools, start=1):
        meta = TOOL_META[key]
        needs_confirm = bool(safety["require_manual_confirm"] and meta["write"])
        if key == "dm_reply":
            needs_confirm = True  # 私信始终确认
        status = "ready"
        note = ""
        if not agent["enabled"]:
            status = "blocked"
            note = "策略未启用"
        elif key == "publish_video" and goal["daily_videos"] <= 0:
            status = "blocked"
            note = "日产量为 0"
        elif key == "publish_video" and goal["daily_videos"] > quotas["max_publish_per_day"]:
            status = "blocked"
            note = "日产量超过发布上限"
        elif needs_confirm:
            status = "needs_confirm"

        count = 1
        if key == "publish_video":
            count = max(0, min(goal["daily_videos"], quotas["max_publish_per_day"]))
        elif key in ("comment", "hot_reply"):
            count = min(5, quotas["max_comments_per_day"]) or 0
        elif key == "dm_reply":
            count = min(3, quotas["max_dm_per_day"]) or 0

        step = {
            "id": f"s{index}",
            "tool": key,
            "title": meta["title"],
            "kind": meta["kind"],
            "description": meta["desc"],
            "count": count,
            "write": meta["write"],
            "requires_confirm": needs_confirm,
            "status": status,
            "note": note,
        }
        if meta.get("quota"):
            step["quota"] = meta["quota"]
        steps.append(step)

    summary_bits = []
    if goal["category"]:
        summary_bits.append(goal["category"])
    summary_bits.append(FUNNEL_LABEL.get(goal["funnel"], goal["funnel"]))
    if goal["brief"]:
        summary_bits.append(goal["brief"])

    warnings = []
    if not agent["enabled"]:
        warnings.append("策略未启用：计划仅供预览")
    if not enabled_tools:
        warnings.append("未开启任何能力：计划为空")
    if tools.get("dm_reply") and not safety["require_manual_confirm"]:
        warnings.append("私信已开但人工确认关闭（保存时会被拒绝）")

    return {
        "schema": PLAN_SCHEMA,
        "created_at": _now_iso(),
        "executable": False,  # 本阶段只读预览
        "summary": " · ".join(summary_bits) if summary_bits else "未填写目标",
        "goal": deepcopy(goal),
        "persona": deepcopy(agent["persona"]),
        "quotas": deepcopy(quotas),
        "safety": deepcopy(safety),
        "enabled_tools": enabled_tools,
        "steps": steps,
        "warnings": warnings,
        "stats": {
            "total": len(steps),
            "needs_confirm": sum(1 for s in steps if s["status"] == "needs_confirm"),
            "blocked": sum(1 for s in steps if s["status"] == "blocked"),
            "ready": sum(1 for s in steps if s["status"] == "ready"),
        },
    }


def validate_plan(raw) -> dict:
    """轻量校验 plan.v1（预览结构，不要求落盘完整性）。"""
    if not isinstance(raw, dict):
        raise ValueError("计划应为 JSON 对象")
    if raw.get("schema") != PLAN_SCHEMA:
        raise ValueError(f"计划 schema 应为 {PLAN_SCHEMA}")
    steps = raw.get("steps")
    if not isinstance(steps, list):
        raise ValueError("steps 应为列表")
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("步骤格式不正确")
        if step.get("tool") not in TOOL_KEYS:
            raise ValueError(f"未知工具：{step.get('tool')}")
    return raw
