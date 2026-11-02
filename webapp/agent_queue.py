"""Agent 确认队列：写操作步骤先入队，人工批准后才可进入后续执行（本阶段仍不真正执行）。"""
from __future__ import annotations

import json
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .agent_config import TOOL_KEYS

_lock = threading.RLock()


def _now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _empty_queue():
    return {"items": []}


def load_queue(path: Path) -> dict:
    if not path.is_file():
        return _empty_queue()
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return _empty_queue()
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        return _empty_queue()
    items = []
    for item in raw["items"]:
        if isinstance(item, dict) and item.get("id") and item.get("tool") in TOOL_KEYS:
            items.append(item)
    return {"items": items}


def save_queue(path: Path, data: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"items": list(data.get("items") or [])}
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return payload


def sync_queue_from_plan(path: Path, plan: dict) -> dict:
    """把计划里 needs_confirm 的步骤同步进队列；已有 pending/approved 不重复建。"""
    with _lock:
        queue = load_queue(path)
        existing = {
            (item.get("tool"), item.get("step_id")): item
            for item in queue["items"]
            if item.get("status") in ("pending", "approved")
        }
        created = []
        for step in plan.get("steps") or []:
            if step.get("status") != "needs_confirm":
                continue
            key = (step.get("tool"), step.get("id"))
            if key in existing:
                continue
            item = {
                "id": f"q_{uuid.uuid4().hex[:10]}",
                "step_id": step.get("id"),
                "tool": step.get("tool"),
                "title": step.get("title") or step.get("tool"),
                "description": step.get("description") or "",
                "count": step.get("count", 1),
                "status": "pending",
                "created_at": _now_iso(),
                "decided_at": None,
                "plan_summary": plan.get("summary") or "",
            }
            queue["items"].append(item)
            created.append(item)
            existing[key] = item
        if created:
            save_queue(path, queue)
        return {"queue": queue, "created": created}


def apply_queue_to_plan(plan: dict, queue: dict) -> dict:
    """用队列决议覆盖计划步骤状态。"""
    plan = deepcopy(plan)
    by_step = {}
    by_tool_pending = {}
    for item in queue.get("items") or []:
        sid = item.get("step_id")
        tool = item.get("tool")
        status = item.get("status")
        if sid:
            by_step[sid] = item
        if tool and status == "pending":
            by_tool_pending[tool] = item
        elif tool and status == "approved" and tool not in by_tool_pending:
            by_tool_pending.setdefault(tool, item)

    for step in plan.get("steps") or []:
        item = by_step.get(step.get("id"))
        if item is None:
            # 兼容：按 tool 匹配最近一条
            item = next(
                (row for row in reversed(queue.get("items") or [])
                 if row.get("tool") == step.get("tool")),
                None,
            )
        if not item:
            continue
        qstatus = item.get("status")
        if qstatus == "approved":
            step["status"] = "approved"
            step["queue_id"] = item.get("id")
            write_status = item.get("write_status") or ""
            worker_status = item.get("worker_status") or ""
            if write_status == "done":
                step["note"] = "写操作已执行"
            elif write_status == "drafted":
                step["note"] = "草稿已生成，等待执行发布"
            elif write_status == "error":
                step["note"] = f"写操作失败：{(item.get('write_error') or '')[:80]}"
            elif worker_status == "prepared":
                step["note"] = "只读准备完成，可生成评论草稿"
            elif worker_status == "error":
                step["note"] = f"只读准备失败：{(item.get('worker_error') or '')[:80]}"
            else:
                step["note"] = "已人工确认，可跑只读准备"
        elif qstatus == "rejected":
            step["status"] = "rejected"
            step["note"] = "已拒绝，本轮不执行"
            step["queue_id"] = item.get("id")
        elif qstatus == "pending" and step.get("status") == "needs_confirm":
            step["queue_id"] = item.get("id")
            step["note"] = step.get("note") or "等待人工确认"

    stats = plan.get("stats") or {}
    steps = plan.get("steps") or []
    stats.update({
        "total": len(steps),
        "needs_confirm": sum(1 for s in steps if s.get("status") == "needs_confirm"),
        "blocked": sum(1 for s in steps if s.get("status") == "blocked"),
        "ready": sum(1 for s in steps if s.get("status") == "ready"),
        "approved": sum(1 for s in steps if s.get("status") == "approved"),
        "rejected": sum(1 for s in steps if s.get("status") == "rejected"),
    })
    plan["stats"] = stats
    pending = [i for i in queue.get("items") or [] if i.get("status") == "pending"]
    plan["queue_pending"] = len(pending)
    return plan


def decide_queue_item(path: Path, item_id: str, *, approve: bool) -> dict:
    with _lock:
        queue = load_queue(path)
        target = None
        for item in queue["items"]:
            if item.get("id") == item_id:
                target = item
                break
        if target is None:
            raise KeyError(item_id)
        if target.get("status") != "pending":
            raise ValueError(f"该条目已是 {target.get('status')}，不能重复处理")
        target["status"] = "approved" if approve else "rejected"
        target["decided_at"] = _now_iso()
        save_queue(path, queue)
        return deepcopy(target)


def update_queue_item(path: Path, item_id: str, **fields) -> dict:
    """更新队列条目的扩展字段（如 worker 结果），不改变 approve/reject 决议。"""
    with _lock:
        queue = load_queue(path)
        target = None
        for item in queue["items"]:
            if item.get("id") == item_id:
                target = item
                break
        if target is None:
            raise KeyError(item_id)
        for key, value in fields.items():
            if key in ("id", "tool", "step_id"):
                continue
            target[key] = value
        target["updated_at"] = _now_iso()
        save_queue(path, queue)
        return deepcopy(target)


def queue_snapshot(path: Path) -> dict:
    with _lock:
        queue = load_queue(path)
    items = list(reversed(queue.get("items") or []))
    pending = [i for i in items if i.get("status") == "pending"]
    return {
        "items": items[:50],
        "pending": pending,
        "counts": {
            "pending": len(pending),
            "approved": sum(1 for i in items if i.get("status") == "approved"),
            "rejected": sum(1 for i in items if i.get("status") == "rejected"),
            "total": len(items),
        },
    }
