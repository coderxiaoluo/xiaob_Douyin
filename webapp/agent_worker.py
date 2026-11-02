"""Agent Worker（只读阶段）：对已批准步骤做搜索/拉评论候选，不发布、不评论、不私信。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from .agent_config import normalize_agent_config
from .agent_queue import load_queue, update_queue_item

READ_PREP_TOOLS = ("comment", "hot_reply")
WRITE_BLOCKED_TOOLS = ("publish_video", "dm_reply")
STUB_TOOLS = ("gen_video", "gen_cover")


def _now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _query_from_agent(agent: dict) -> str:
    goal = (agent or {}).get("goal") or {}
    parts = [goal.get("category") or "", goal.get("brief") or ""]
    query = " ".join(p.strip() for p in parts if p and str(p).strip())
    return query.strip() or "抖音"


def _public_work_from_aweme(info: dict) -> dict:
    return {
        "kind": "work",
        "id": str(info.get("work_id") or ""),
        "work_id": info.get("work_id"),
        "title": info.get("title") or info.get("desc") or "",
        "nickname": info.get("nickname") or "",
        "video_cover": info.get("video_cover") or "",
        "work_url": info.get("work_url") or "",
        "digg_count": info.get("digg_count") or 0,
        "comment_count": info.get("comment_count") or 0,
        "create_time": info.get("create_time") or 0,
    }


def _public_comment(row: dict, *, intent_rules: dict | None = None,
                    bonus_words: list | None = None) -> dict:
    from webapp.intent_rules import attach_intent

    user = row.get("user") or {}
    text = row.get("text") or row.get("content") or ""
    gender_raw = user.get("gender")
    try:
        gcode = int(gender_raw)
        gender = "男" if gcode == 1 else ("女" if gcode == 2 else "")
    except (TypeError, ValueError):
        gender = ""
    verified = bool(
        user.get("custom_verify")
        or user.get("enterprise_verify_reason")
        or user.get("verification_type")
    )
    item = {
        "kind": "comment",
        "cid": str(row.get("cid") or row.get("comment_id") or ""),
        "text": text[:200],
        "nickname": user.get("nickname") or "",
        "unique_id": user.get("unique_id") or user.get("short_id") or "",
        "uid": str(user.get("uid") or user.get("user_id") or ""),
        "sec_uid": user.get("sec_uid") or user.get("sec_user_id") or "",
        "gender": gender,
        "is_verified": verified,
        "ip_label": str(row.get("ip_label") or ""),
        "digg_count": int(row.get("digg_count") or 0),
        "create_time": row.get("create_time") or 0,
        "selected": True,
    }
    return attach_intent(item, intent_rules, bonus_words=bonus_words)


def _engage_filters(agent: dict) -> dict:
    engage = (agent or {}).get("engage") or {}
    return {
        "work_min_digg": int(engage.get("work_min_digg") or 0),
        "comment_min_digg": int(engage.get("comment_min_digg") or 0),
        "comment_keyword": str(engage.get("comment_keyword") or "").strip(),
        "comment_exclude": str(engage.get("comment_exclude") or "").strip(),
        "max_comments_per_work": max(1, int(engage.get("max_comments_per_work") or 5)),
        "intent_only": bool(engage.get("intent_only")),
    }


def _comment_passes(
    item: dict,
    *,
    min_digg: int,
    keyword: str,
    exclude: str,
    intent_only: bool = False,
    ip_label: str = "",
    gender: str = "",
) -> bool:
    digg = int(item.get("digg_count") or 0)
    if digg < min_digg:
        return False
    text = str(item.get("text") or "")
    if keyword and keyword not in text:
        return False
    if exclude and exclude in text:
        return False
    if intent_only and not item.get("is_intent"):
        return False
    if ip_label and ip_label not in str(item.get("ip_label") or ""):
        return False
    if gender and str(item.get("gender") or "") != gender:
        return False
    return True


def apply_candidate_filters(
    works: list,
    comments: list,
    *,
    work_min_digg: int = 0,
    comment_min_digg: int = 0,
    comment_keyword: str = "",
    comment_exclude: str = "",
    max_comments_per_work: int = 5,
    intent_only: bool = False,
    comment_ip_label: str = "",
    comment_gender: str = "",
    selected_work_ids: list | None = None,
    selected_comment_cids: list | None = None,
) -> tuple[list, list]:
    """按点赞/关键词/意向过滤，并写回 selected 勾选状态。"""
    work_ids_set = set(selected_work_ids) if selected_work_ids is not None else None
    cid_set = set(selected_comment_cids) if selected_comment_cids is not None else None

    filtered_works = []
    for work in works or []:
        if not isinstance(work, dict):
            continue
        row = dict(work)
        digg = int(row.get("digg_count") or 0)
        if digg < work_min_digg:
            row["selected"] = False
            row["filtered_out"] = True
        else:
            row["filtered_out"] = False
            if work_ids_set is None:
                row["selected"] = True if row.get("selected", True) else False
            else:
                row["selected"] = str(row.get("work_id") or "") in work_ids_set
        filtered_works.append(row)

    per_work = {}
    filtered_comments = []
    for comment in comments or []:
        if not isinstance(comment, dict):
            continue
        row = dict(comment)
        ok = _comment_passes(
            row,
            min_digg=comment_min_digg,
            keyword=comment_keyword,
            exclude=comment_exclude,
            intent_only=intent_only,
            ip_label=comment_ip_label,
            gender=comment_gender,
        )
        wid = str(row.get("work_id") or "")
        if ok:
            used = per_work.get(wid, 0)
            if used >= max_comments_per_work:
                ok = False
            else:
                per_work[wid] = used + 1
        row["filtered_out"] = not ok
        if not ok:
            row["selected"] = False
        elif cid_set is None:
            row["selected"] = True if row.get("selected", True) else False
        else:
            row["selected"] = str(row.get("cid") or "") in cid_set
        filtered_comments.append(row)
    return filtered_works, filtered_comments


def _prepare_comment_candidates(auth, agent: dict, *, work_limit: int = 6, comment_fetch: int = 20) -> dict:
    """搜相关作品，并抽样拉一级评论（只读）；按 engage 筛选后默认全选通过项。"""
    from pathlib import Path

    from dy_apis.douyin_api import DouyinAPI
    from utils.data_util import handle_work_info
    from webapp.intent_rules import bonus_words_from_agent, load_intent_rules

    filters = _engage_filters(agent)
    intent_only = bool((agent.get("engage") or {}).get("intent_only"))
    filters["intent_only"] = intent_only
    query = _query_from_agent(agent)
    rules = load_intent_rules(Path(__file__).resolve().parents[1] / "datas" / "intent_rules.json")
    bonus = bonus_words_from_agent(agent)
    raw = DouyinAPI.search_some_general_work(
        auth, query, work_limit, "0", "0", "", "0", "0",
    )
    works = []
    hot_comments = []
    for row in raw:
        aweme = row.get("aweme_info") if isinstance(row, dict) else None
        if not isinstance(aweme, dict):
            continue
        info = handle_work_info(aweme)
        pub = _public_work_from_aweme(info)
        if not pub.get("work_id"):
            continue
        pub["selected"] = True
        works.append(pub)
        url = pub.get("work_url") or f"https://www.douyin.com/video/{pub['work_id']}"
        try:
            page = DouyinAPI.get_work_out_comment(auth, url, "0")
            comments = page.get("comments") if isinstance(page, dict) else None
            if not isinstance(comments, list):
                continue
            # 多拉一些，再按点赞/关键词/意向筛
            ranked = sorted(
                [c for c in comments if isinstance(c, dict)],
                key=lambda c: int(c.get("digg_count") or 0),
                reverse=True,
            )
            for comment in ranked[:comment_fetch]:
                item = _public_comment(comment, intent_rules=rules, bonus_words=bonus)
                if not item.get("cid"):
                    continue
                item["work_id"] = pub["work_id"]
                item["work_title"] = pub.get("title") or ""
                hot_comments.append(item)
        except Exception as exc:  # 单条失败不阻断整体
            works[-1]["comment_error"] = str(exc)[:120]

    works, hot_comments = apply_candidate_filters(
        works, hot_comments, **filters,
    )
    selected_works = sum(1 for w in works if w.get("selected") and not w.get("filtered_out"))
    selected_comments = sum(1 for c in hot_comments if c.get("selected") and not c.get("filtered_out"))
    intent_n = sum(1 for c in hot_comments if c.get("is_intent"))
    return {
        "mode": "readonly_prep",
        "query": query,
        "filters": filters,
        "works": works,
        "comments": hot_comments,
        "message": (
            f"只读准备完成：作品 {len(works)}（已选 {selected_works}）"
            f" · 评论 {len(hot_comments)}（已选 {selected_comments} · 意向 {intent_n}）"
        ),
    }


def update_candidate_selection(
    *,
    queue_path,
    item_id: str,
    work_ids: list | None = None,
    comment_cids: list | None = None,
    filters: dict | None = None,
) -> dict:
    """更新某条队列项的候选勾选/筛选条件（不重新请求抖音）。"""
    queue = load_queue(queue_path)
    target = next((i for i in queue.get("items") or [] if i.get("id") == item_id), None)
    if target is None:
        raise KeyError(item_id)
    prep = dict(target.get("worker_result") or {})
    if prep.get("mode") != "readonly_prep":
        raise ValueError("该条目还没有只读准备结果")
    base_filters = dict(prep.get("filters") or {})
    if isinstance(filters, dict):
        for key in (
            "work_min_digg", "comment_min_digg", "comment_keyword",
            "comment_exclude", "max_comments_per_work", "intent_only",
            "comment_ip_label", "comment_gender",
        ):
            if key in filters and filters[key] is not None:
                base_filters[key] = filters[key]
    works, comments = apply_candidate_filters(
        prep.get("works") or [],
        prep.get("comments") or [],
        work_min_digg=int(base_filters.get("work_min_digg") or 0),
        comment_min_digg=int(base_filters.get("comment_min_digg") or 0),
        comment_keyword=str(base_filters.get("comment_keyword") or "").strip(),
        comment_exclude=str(base_filters.get("comment_exclude") or "").strip(),
        max_comments_per_work=max(1, int(base_filters.get("max_comments_per_work") or 5)),
        intent_only=bool(base_filters.get("intent_only")),
        comment_ip_label=str(base_filters.get("comment_ip_label") or "").strip(),
        comment_gender=str(base_filters.get("comment_gender") or "").strip(),
        selected_work_ids=work_ids,
        selected_comment_cids=comment_cids,
    )
    selected_works = sum(1 for w in works if w.get("selected") and not w.get("filtered_out"))
    selected_comments = sum(1 for c in comments if c.get("selected") and not c.get("filtered_out"))
    prep.update({
        "filters": base_filters,
        "works": works,
        "comments": comments,
        "message": (
            f"筛选已更新：作品已选 {selected_works}/{len(works)}"
            f" · 评论已选 {selected_comments}/{len(comments)}"
        ),
    })
    fields = {"worker_result": prep}
    # 改筛选后旧草稿失效，需重新生成
    if target.get("write_status") == "drafted":
        fields.update({
            "write_status": "",
            "write_draft": None,
            "write_result": None,
            "write_error": "",
        })
    return update_queue_item(queue_path, item_id, **fields)


def run_readonly_prep(*, queue_path, agent: dict, auth, item_id: str | None = None) -> dict:
    """
    对已批准队列项做只读准备。
    - comment / hot_reply：搜作品 + 拉评论候选
    - publish / dm：标记为仍需写操作 Worker（本阶段跳过）
    - gen_*：标记为待媒体流水线
    """
    agent = normalize_agent_config(agent)
    queue = load_queue(queue_path)
    targets = []
    for item in queue.get("items") or []:
        if item.get("status") != "approved":
            continue
        if item_id and item.get("id") != item_id:
            continue
        if item.get("worker_status") == "prepared" and not item_id:
            continue
        targets.append(item)

    if not targets:
        return {
            "ok": True,
            "ran": [],
            "message": "没有可准备的已批准项（请先批准确认队列，或指定条目）",
        }

    ran = []
    for item in targets:
        tool = item.get("tool")
        try:
            if tool in READ_PREP_TOOLS:
                result = _prepare_comment_candidates(auth, agent)
                updated = update_queue_item(
                    queue_path,
                    item["id"],
                    worker_status="prepared",
                    worker_mode="readonly",
                    worker_at=_now_iso(),
                    worker_result=result,
                    worker_error="",
                )
            elif tool in WRITE_BLOCKED_TOOLS:
                updated = update_queue_item(
                    queue_path,
                    item["id"],
                    worker_status="skipped",
                    worker_mode="readonly",
                    worker_at=_now_iso(),
                    worker_result={
                        "mode": "readonly_skip",
                        "message": "写操作尚未接入，只读 Worker 不会执行发布/私信",
                    },
                    worker_error="",
                )
            elif tool in STUB_TOOLS:
                updated = update_queue_item(
                    queue_path,
                    item["id"],
                    worker_status="skipped",
                    worker_mode="readonly",
                    worker_at=_now_iso(),
                    worker_result={
                        "mode": "readonly_skip",
                        "message": "生成视频/封面尚未接入媒体流水线",
                    },
                    worker_error="",
                )
            else:
                updated = update_queue_item(
                    queue_path,
                    item["id"],
                    worker_status="skipped",
                    worker_mode="readonly",
                    worker_at=_now_iso(),
                    worker_result={"mode": "readonly_skip", "message": f"未知工具：{tool}"},
                    worker_error="",
                )
            ran.append(deepcopy(updated))
        except Exception as exc:
            updated = update_queue_item(
                queue_path,
                item["id"],
                worker_status="error",
                worker_mode="readonly",
                worker_at=_now_iso(),
                worker_error=str(exc)[:300],
            )
            ran.append(deepcopy(updated))

    prepared = sum(1 for row in ran if row.get("worker_status") == "prepared")
    errors = sum(1 for row in ran if row.get("worker_status") == "error")
    return {
        "ok": errors == 0,
        "ran": ran,
        "message": f"只读准备结束：成功 {prepared} · 失败 {errors} · 处理 {len(ran)}",
    }


def _forbidden_hits(text: str, forbidden: str) -> list[str]:
    raw = (forbidden or "").replace("，", "、").replace(",", "、")
    words = [w.strip() for w in raw.split("、") if w.strip()]
    return [w for w in words if w and w in (text or "")]


def _draft_top_comment(agent: dict, work: dict) -> str:
    """一级评论草稿：短互动，不硬广。"""
    cat = ((agent.get("goal") or {}).get("category") or "").strip() or "这"
    brief = ((agent.get("goal") or {}).get("brief") or "").strip()
    title = (work.get("title") or "").strip()
    hook = brief[:12] if brief else (title[:12] if title else cat)
    return f"{cat}这块「{hook}」有感，后续还能再拆一版吗？"


def _draft_hot_reply(agent: dict, comment: dict) -> str:
    cat = ((agent.get("goal") or {}).get("category") or "").strip() or "这"
    nick = (comment.get("nickname") or "").strip()
    prefix = f"@{nick} " if nick else ""
    return f"{prefix}同感，{cat}这块确实值得细聊。"


def build_write_drafts(agent: dict, item: dict) -> dict:
    """基于只读准备结果生成待发草稿（不发抖音）；仅使用已勾选且未滤掉的候选。"""
    agent = normalize_agent_config(agent)
    tool = item.get("tool")
    prep = item.get("worker_result") or {}
    works = [
        w for w in (prep.get("works") or [])
        if isinstance(w, dict) and w.get("selected") and not w.get("filtered_out")
    ]
    comments = [
        c for c in (prep.get("comments") or [])
        if isinstance(c, dict) and c.get("selected") and not c.get("filtered_out")
    ]
    want = max(1, int(item.get("count") or 1))
    forbidden = (agent.get("persona") or {}).get("forbidden") or ""
    drafts = []

    if tool == "hot_reply":
        for comment in comments:
            if len(drafts) >= want:
                break
            text = _draft_hot_reply(agent, comment)
            hits = _forbidden_hits(text, forbidden) if agent["safety"]["sensitive_word_check"] else []
            drafts.append({
                "kind": "hot_reply",
                "work_id": comment.get("work_id") or "",
                "reply_id": comment.get("cid") or "",
                "target_text": (comment.get("text") or "")[:80],
                "content": text,
                "blocked": bool(hits),
                "blocked_words": hits,
            })
    else:
        # comment：对作品发一级评论
        for work in works:
            if len(drafts) >= want:
                break
            wid = work.get("work_id") or ""
            if not wid:
                continue
            text = _draft_top_comment(agent, work)
            hits = _forbidden_hits(text, forbidden) if agent["safety"]["sensitive_word_check"] else []
            drafts.append({
                "kind": "comment",
                "work_id": wid,
                "work_title": (work.get("title") or "")[:80],
                "reply_id": "",
                "content": text,
                "blocked": bool(hits),
                "blocked_words": hits,
            })
    if not drafts:
        raise ValueError("没有已勾选的候选，请先筛选/勾选作品或评论后再生成草稿")

    usable = [d for d in drafts if not d.get("blocked")]
    return {
        "mode": "write_draft",
        "tool": tool,
        "drafts": drafts,
        "message": f"草稿 {len(drafts)} 条（可发 {len(usable)} · 命中禁区 {len(drafts) - len(usable)}）",
    }


def run_write_drafts(*, queue_path, agent: dict, item_id: str | None = None) -> dict:
    """为已只读准备的条目生成写操作草稿。"""
    agent = normalize_agent_config(agent)
    queue = load_queue(queue_path)
    targets = []
    for item in queue.get("items") or []:
        if item.get("status") != "approved":
            continue
        if item.get("worker_status") != "prepared":
            continue
        if item.get("tool") not in READ_PREP_TOOLS:
            continue
        if item_id and item.get("id") != item_id:
            continue
        targets.append(item)
    if not targets:
        return {
            "ok": True,
            "ran": [],
            "message": "没有可生成草稿的项（需已批准且只读准备完成）",
        }

    ran = []
    for item in targets:
        try:
            draft = build_write_drafts(agent, item)
            updated = update_queue_item(
                queue_path,
                item["id"],
                write_status="drafted",
                write_at=_now_iso(),
                write_draft=draft,
                write_error="",
                write_result=None,
            )
            ran.append(deepcopy(updated))
        except Exception as exc:
            updated = update_queue_item(
                queue_path,
                item["id"],
                write_status="error",
                write_at=_now_iso(),
                write_error=str(exc)[:300],
            )
            ran.append(deepcopy(updated))
    errors = sum(1 for row in ran if row.get("write_status") == "error")
    return {
        "ok": errors == 0,
        "ran": ran,
        "message": f"草稿生成结束：成功 {len(ran) - errors} · 失败 {errors}",
    }


def run_write_execute(*, queue_path, agent: dict, auth, item_id: str | None = None,
                      dry_run: bool = False) -> dict:
    """执行评论写操作。默认真实发布；dry_run 只演练不发抖音。"""
    import time

    from dy_apis.douyin_api import DouyinAPI

    agent = normalize_agent_config(agent)
    queue = load_queue(queue_path)
    interval = int((agent.get("quotas") or {}).get("min_action_interval_sec") or 180)
    targets = []
    for item in queue.get("items") or []:
        if item.get("status") != "approved":
            continue
        if item.get("write_status") != "drafted":
            continue
        if item.get("tool") not in READ_PREP_TOOLS:
            continue
        if item_id and item.get("id") != item_id:
            continue
        targets.append(item)
    if not targets:
        return {
            "ok": True,
            "ran": [],
            "message": "没有可执行项（请先生成评论草稿）",
        }

    ran = []
    for item in targets:
        draft_pack = item.get("write_draft") or {}
        drafts = [d for d in (draft_pack.get("drafts") or []) if not d.get("blocked")]
        want = max(1, int(item.get("count") or 1))
        drafts = drafts[:want]
        results = []
        try:
            for i, draft in enumerate(drafts):
                wid = str(draft.get("work_id") or "")
                content = (draft.get("content") or "").strip()
                reply_id = draft.get("reply_id") or ""
                if not wid or not content:
                    results.append({"ok": False, "error": "草稿缺少 work_id/content", "draft": draft})
                    continue
                if dry_run:
                    results.append({
                        "ok": True,
                        "dry_run": True,
                        "work_id": wid,
                        "content": content,
                        "reply_id": reply_id,
                    })
                else:
                    resp = DouyinAPI.publish_comment(
                        auth, wid, content, reply_id=reply_id or "",
                    )
                    status = resp.get("status_code") if isinstance(resp, dict) else None
                    ok = status in (0, None) and isinstance(resp, dict)
                    # 部分成功响应用 status_code=0；否则保留原文供排查
                    results.append({
                        "ok": bool(ok) or (isinstance(resp, dict) and resp.get("comment")),
                        "work_id": wid,
                        "content": content,
                        "reply_id": reply_id,
                        "status_code": status,
                        "response": {
                            k: resp.get(k)
                            for k in ("status_code", "status_msg", "message")
                            if isinstance(resp, dict) and k in resp
                        },
                    })
                if i + 1 < len(drafts) and not dry_run and interval > 0:
                    time.sleep(interval)
            ok_n = sum(1 for r in results if r.get("ok"))
            updated = update_queue_item(
                queue_path,
                item["id"],
                write_status="done" if ok_n else "error",
                write_at=_now_iso(),
                write_result={
                    "mode": "write_execute",
                    "dry_run": dry_run,
                    "results": results,
                    "message": f"{'演练' if dry_run else '发布'}完成：成功 {ok_n}/{len(results)}",
                },
                write_error="" if ok_n else "全部发布失败",
            )
            ran.append(deepcopy(updated))
        except Exception as exc:
            updated = update_queue_item(
                queue_path,
                item["id"],
                write_status="error",
                write_at=_now_iso(),
                write_error=str(exc)[:300],
                write_result={"mode": "write_execute", "results": results},
            )
            ran.append(deepcopy(updated))

    done = sum(1 for row in ran if row.get("write_status") == "done")
    errors = sum(1 for row in ran if row.get("write_status") == "error")
    return {
        "ok": errors == 0,
        "ran": ran,
        "message": f"写操作结束：成功 {done} · 失败 {errors} · {'演练' if dry_run else '实发'}",
    }
