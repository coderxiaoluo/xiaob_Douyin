# coding=utf-8
"""Douyin Spider Web 工作台。

启动：python -m webapp.server
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv, set_key
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import requests

from main import Data_Spider, safe_download_work
from utils.common_util import load_env
from utils.data_util import handle_work_info, save_to_xlsx
from utils.proxy import proxies_from_url
from dy_apis.douyin_api import DouyinAPI, parse_aweme_id, parse_sec_user_id
from webapp.live_feed import KIND_LABEL, LiveSession, fetch_ranks

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
TEMPLATE_DIR = APP_DIR / "templates"
ENV_PATH = ROOT / ".env"
AGENT_PATH = ROOT / "datas" / "agent_config.json"
AGENT_EXAMPLE_PATH = ROOT / "agent_config.example.json"
AGENT_QUEUE_PATH = ROOT / "datas" / "agent_queue.json"
INTENT_RULES_PATH = ROOT / "datas" / "intent_rules.json"

FP_KEYS = (
    "DY_FP_UA",
    "DY_FP_BROWSER_VERSION",
    "DY_FP_ENGINE_VERSION",
    "DY_FP_SCREEN_WIDTH",
    "DY_FP_SCREEN_HEIGHT",
    "DY_FP_CPU_CORE_NUM",
    "DY_FP_DEVICE_MEMORY",
    "DY_FP_ACCEPT_LANGUAGE",
)

app = FastAPI(title="Douyin Spider Workbench", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

_lock = threading.Lock()
_auth = None
_base_path: dict = {}
_jobs: dict[str, dict] = {}
_spider = Data_Spider()
_live = LiveSession()
_qr_lock = threading.Lock()
_qr_thread: threading.Thread | None = None
_qr_generation = 0
_qr = {"status": "idle", "qr_url": "", "message": ""}
# 清空只去掉登录材料。浏览器指纹和代理留着，下一次扫码按当前指纹重写 Cookie。
_SESSION_KEYS = (
    "DY_COOKIES",
    "DY_LIVE_COOKIES",
    "DY_TICKET",
    "DY_TS_SIGN",
    "DY_CLIENT_CERT",
    "DY_PRIVATE_KEY",
    "DY_DTRAIT_BLOB",
    "DY_SESSION_DTRAIT",
)

MODULES = [
    {"id": "search_work", "group": "搜索", "label": "搜作品", "desc": "综合搜索视频/图文"},
    {"id": "search_user", "group": "搜索", "label": "搜用户", "desc": "按关键词找账号"},
    {"id": "search_live", "group": "搜索", "label": "搜直播", "desc": "直播间搜索"},
    {"id": "live_room", "group": "直播", "label": "直播间", "desc": "只读监听弹幕、礼物、进场、点赞，并查看 PK 榜和贡献榜", "view": "live"},
    {"id": "user_works", "group": "用户", "label": "用户作品", "desc": "主页全部作品"},
    {"id": "user_profile", "group": "用户", "label": "用户资料", "desc": "主页基础信息"},
    {"id": "followers", "group": "用户", "label": "粉丝列表", "desc": "指定用户粉丝"},
    {"id": "following", "group": "用户", "label": "关注列表", "desc": "指定用户关注"},
    {"id": "work_detail", "group": "作品", "label": "作品详情", "desc": "单条作品信息"},
    {"id": "comments", "group": "作品", "label": "评论区", "desc": "含多级回复"},
    {"id": "work_urls", "group": "作品", "label": "链接批量", "desc": "多链接扫描"},
    {"id": "favorites", "group": "我的", "label": "收藏列表", "desc": "用户公开收藏"},
    {"id": "feed", "group": "我的", "label": "推荐流", "desc": "首页推荐"},
    {"id": "notices", "group": "我的", "label": "消息通知", "desc": "互动通知"},
]


def _ensure_runtime():
    global _auth, _base_path
    with _lock:
        if _auth is None:
            load_dotenv(dotenv_path=str(ENV_PATH), override=True)
            proxies = proxies_from_url(os.getenv("DY_PROXY"))
            cookies = (os.getenv("DY_COOKIES") or "").strip()
            if cookies:
                _auth = load_env(
                    env_path=str(ENV_PATH),
                    bootstrap_creator=False,
                    proxies=proxies,
                )
            else:
                # 没有 Cookie 时不要走进 CLI 的阻塞扫码。页面自己有二维码登录。
                from builder.auth import DouyinAuth
                _auth = DouyinAuth()
                _auth.cookie = {}
                _auth._proxies = proxies
            media = ROOT / "datas" / "media_datas"
            excel = ROOT / "datas" / "excel_datas"
            media.mkdir(parents=True, exist_ok=True)
            excel.mkdir(parents=True, exist_ok=True)
            _base_path = {"media": str(media), "excel": str(excel)}
        return _auth, _base_path


def _set_job(job_id: str, **fields):
    with _lock:
        job = _jobs.setdefault(job_id, {})
        job.update(fields)
        job["updated_at"] = time.time()


def _append_log(job_id: str, message: str):
    with _lock:
        job = _jobs.setdefault(job_id, {})
        logs = job.setdefault("logs", [])
        logs.append({"ts": time.time(), "msg": message})
        if len(logs) > 240:
            del logs[:-240]


def _public_work(item: dict) -> dict:
    create_time = item.get("create_time") or 0
    try:
        create_time = int(create_time)
    except (TypeError, ValueError):
        create_time = 0
    return {
        "kind": "work",
        "id": str(item.get("work_id") or ""),
        "work_id": item.get("work_id"),
        "title": item.get("title") or item.get("desc") or "",
        "nickname": item.get("nickname") or "",
        "author_avatar": item.get("author_avatar") or "",
        "video_cover": item.get("video_cover") or "",
        "work_type": item.get("work_type") or "",
        "work_url": item.get("work_url") or "",
        "digg_count": item.get("digg_count") or 0,
        "comment_count": item.get("comment_count") or 0,
        "collect_count": item.get("collect_count") or 0,
        "share_count": item.get("share_count") or 0,
        "create_time": create_time,
    }


_COVER_HOST_SUFFIXES = (
    "douyinpic.com",
    "douyincdn.com",
    "byteimg.com",
    "ibyteimg.com",
    "tiktokcdn.com",
    "snssdk.com",
    "amemv.com",
    "douyin.com",
    "iesdouyin.com",
)


def _cover_host_allowed(host: str) -> bool:
    h = (host or "").lower().split(":")[0]
    return any(h == s or h.endswith("." + s) for s in _COVER_HOST_SUFFIXES)


def _public_user(u: dict, idx: int = 0) -> dict:
    info = u.get("user_info") or u.get("user") or u
    sec = info.get("sec_uid") or info.get("sec_user_id") or ""
    uid = str(info.get("uid") or info.get("user_id") or "")
    avatar = ""
    thumb = info.get("avatar_thumb") or {}
    if isinstance(thumb, dict):
        avatar = (thumb.get("url_list") or [""])[0]
    return {
        "kind": "user",
        "id": sec or uid or f"user-{idx}",
        "nickname": info.get("nickname") or "",
        "unique_id": info.get("unique_id") or info.get("short_id") or "",
        "signature": info.get("signature") or "",
        "follower_count": info.get("follower_count") or 0,
        "aweme_count": info.get("aweme_count") or 0,
        "sec_uid": sec,
        "uid": uid,
        "avatar": avatar,
        "user_url": f"https://www.douyin.com/user/{sec}" if sec else "",
    }


def _public_live(row: dict, idx: int = 0) -> dict:
    lives = row.get("lives") or row.get("live_info") or row
    if isinstance(lives, dict) and "author" in lives:
        author = lives.get("author") or {}
        room = lives
    else:
        author = (lives.get("author") if isinstance(lives, dict) else {}) or {}
        room = lives if isinstance(lives, dict) else {}
    title = room.get("title") or row.get("type_name") or "直播"
    rid = str(room.get("room_id") or room.get("id") or idx)
    return {
        "kind": "live",
        "id": rid,
        "title": title,
        "nickname": author.get("nickname") or "",
        "user_count": room.get("user_count") or room.get("total_user") or 0,
        "sec_uid": author.get("sec_uid") or "",
        "cover": ((room.get("cover") or {}).get("url_list") or [""])[0]
        if isinstance(room.get("cover"), dict) else "",
    }


def _avatar_url(user: dict | None) -> str:
    user = user or {}
    for key in ("avatar_thumb", "avatar_medium", "avatar_larger"):
        thumb = user.get(key)
        if isinstance(thumb, dict):
            urls = thumb.get("url_list") or []
            if urls:
                return str(urls[0] or "")
        elif isinstance(thumb, str) and thumb:
            return thumb
    return ""


def _gender_label(value) -> str:
    try:
        code = int(value)
    except (TypeError, ValueError):
        return ""
    if code == 1:
        return "男"
    if code == 2:
        return "女"
    return ""


def _public_comment_user(user: dict | None) -> dict:
    user = user or {}
    sec = user.get("sec_uid") or user.get("sec_user_id") or ""
    uid = str(user.get("uid") or user.get("user_id") or "")
    verified = bool(
        user.get("custom_verify")
        or user.get("enterprise_verify_reason")
        or user.get("verification_type")
    )
    return {
        "nickname": user.get("nickname") or "未知用户",
        "unique_id": user.get("unique_id") or user.get("short_id") or "",
        "uid": uid,
        "sec_uid": sec,
        "avatar": _avatar_url(user),
        "user_url": f"https://www.douyin.com/user/{sec}" if sec else "",
        "gender": _gender_label(user.get("gender")),
        "is_verified": verified,
        "follower_count": int(user.get("follower_count") or 0),
    }


def _public_comment(c: dict, idx: int = 0, *, intent_rules: dict | None = None,
                    bonus_words: list | None = None) -> dict:
    from webapp.intent_rules import attach_intent

    user = _public_comment_user(c.get("user") or {})
    cid = str(c.get("cid") or c.get("comment_id") or idx)
    replies = c.get("reply_comment") or []
    reply_list = replies if isinstance(replies, list) else []
    ip_label = (
        c.get("ip_label")
        or c.get("ip_label_name")
        or (c.get("comment_extra") or {}).get("ip_label")
        or ""
    )
    row = {
        "kind": "comment",
        "id": cid,
        "text": c.get("text") or "",
        "nickname": user["nickname"],
        "unique_id": user["unique_id"],
        "uid": user["uid"],
        "sec_uid": user["sec_uid"],
        "avatar": user["avatar"],
        "user_url": user["user_url"],
        "gender": user["gender"],
        "is_verified": user["is_verified"],
        "follower_count": user["follower_count"],
        "ip_label": str(ip_label or ""),
        "digg_count": c.get("digg_count") or 0,
        "reply_count": len(reply_list) if reply_list else (c.get("reply_comment_total") or 0),
        "create_time": c.get("create_time") or 0,
        "replies": [
            {
                **_public_comment_user(r.get("user") or {}),
                "text": r.get("text") or "",
                "digg_count": r.get("digg_count") or 0,
                "create_time": r.get("create_time") or 0,
                "ip_label": str(r.get("ip_label") or ""),
            }
            for r in reply_list[:8]
        ],
    }
    return attach_intent(row, intent_rules, bonus_words=bonus_words)


def _public_notice(n: dict, idx: int = 0) -> dict:
    nid = str(n.get("nid") or n.get("notice_id") or idx)
    return {
        "kind": "notice",
        "id": nid,
        "title": n.get("title") or n.get("content") or json.dumps(n, ensure_ascii=False)[:80],
        "type": n.get("type") or n.get("notice_type") or "",
        "create_time": n.get("create_time") or 0,
    }


def _finish_scan(job_id: str, results: list, message: str, default_name: str,
                 result_kind: str, works_map: dict | None = None):
    with _lock:
        job = _jobs.setdefault(job_id, {})
        job["_works"] = works_map or {}
        job["_rows"] = {str(r.get("id")): r for r in results if r.get("id")}
        job["default_name"] = default_name
        job["result_kind"] = result_kind
    _set_job(
        job_id,
        status="done",
        progress=100,
        message=message,
        results=results,
        excel_path="",
        count=len(results),
        selectable=True,
        result_kind=result_kind,
    )
    _append_log(job_id, "仅扫描，未落盘；勾选后可保存/导出")


def _start_job(kind: str, runner, payload: dict) -> dict:
    job_id = uuid.uuid4().hex[:12]
    _set_job(
        job_id, id=job_id, kind=kind, status="queued", progress=0,
        message="排队中", results=[], logs=[], excel_path="", count=0,
        selectable=False, default_name="", result_kind="", created_at=time.time(),
    )
    threading.Thread(target=runner, args=(job_id, payload), daemon=True).start()
    return {"job_id": job_id}


# ---------- runners ----------

def _run_search_work(job_id: str, payload: dict):
    try:
        auth, _ = _ensure_runtime()
        query = payload["query"].strip()
        num = int(payload.get("require_num") or 12)
        _set_job(job_id, status="running", progress=8, message="扫描作品…")
        raw = DouyinAPI.search_some_general_work(
            auth, query, num,
            str(payload.get("sort_type") or "0"),
            str(payload.get("publish_time") or "0"),
            payload.get("filter_duration") or "",
            payload.get("search_range") or "0",
            payload.get("content_type") or "0",
        )
        works, pubs = [], []
        for i, row in enumerate(raw):
            info = handle_work_info(row["aweme_info"])
            works.append(info)
            pubs.append(_public_work(info))
            _set_job(job_id, progress=10 + int(80 * (i + 1) / max(len(raw), 1)),
                     results=pubs, message=f"解析 {i + 1}/{len(raw)}")
        _finish_scan(job_id, pubs, f"扫描完成 · {len(pubs)} 条", query, "work",
                     {str(w["work_id"]): w for w in works})
    except Exception as exc:
        _append_log(job_id, traceback.format_exc())
        _set_job(job_id, status="error", message=str(exc), progress=100)


def _run_search_user(job_id: str, payload: dict):
    try:
        auth, _ = _ensure_runtime()
        query = payload["query"].strip()
        num = int(payload.get("require_num") or 12)
        _set_job(job_id, status="running", progress=10, message="搜索用户…")
        raw = DouyinAPI.search_some_user(auth, query, num)
        pubs = [_public_user(u, i) for i, u in enumerate(raw)]
        _finish_scan(job_id, pubs, f"用户 {len(pubs)} 个", query, "user")
    except Exception as exc:
        _append_log(job_id, traceback.format_exc())
        _set_job(job_id, status="error", message=str(exc), progress=100)


def _run_search_live(job_id: str, payload: dict):
    try:
        auth, _ = _ensure_runtime()
        query = payload["query"].strip()
        num = int(payload.get("require_num") or 12)
        _set_job(job_id, status="running", progress=10, message="搜索直播…")
        raw = DouyinAPI.search_some_live(auth, query, num)
        pubs = [_public_live(u, i) for i, u in enumerate(raw)]
        _finish_scan(job_id, pubs, f"直播 {len(pubs)} 场", query, "live")
    except Exception as exc:
        _append_log(job_id, traceback.format_exc())
        _set_job(job_id, status="error", message=str(exc), progress=100)


def _run_user_works(job_id: str, payload: dict):
    try:
        auth, _ = _ensure_runtime()
        sec_uid, referer = parse_sec_user_id(payload["user_url"].strip())
        _set_job(job_id, status="running", progress=5, message="拉取用户…")
        user_info = None
        nickname = "用户"
        try:
            user_info = DouyinAPI.get_user_info(auth, referer)
            nickname = (user_info.get("user") or {}).get("nickname") or nickname
        except Exception as err:
            _append_log(job_id, f"资料失败，继续扫作品：{err}")
        work_list = DouyinAPI.get_user_all_work_info(auth, referer)
        works, pubs = [], []
        for i, work in enumerate(work_list):
            if user_info and user_info.get("user"):
                work.setdefault("author", {}).update(user_info["user"])
            info = handle_work_info(work)
            works.append(info)
            pubs.append(_public_work(info))
            if i == 0 and nickname == "用户":
                nickname = info.get("nickname") or nickname
            _set_job(job_id, progress=15 + int(75 * (i + 1) / max(len(work_list), 1)),
                     results=pubs, message=f"扫描 {i + 1}/{len(work_list)}")
        _finish_scan(job_id, pubs, f"{nickname} · {len(pubs)} 条", nickname or sec_uid,
                     "work", {str(w["work_id"]): w for w in works})
    except Exception as exc:
        _append_log(job_id, traceback.format_exc())
        _set_job(job_id, status="error", message=str(exc), progress=100)


def _run_user_profile(job_id: str, payload: dict):
    try:
        auth, _ = _ensure_runtime()
        _, referer = parse_sec_user_id(payload["user_url"].strip())
        _set_job(job_id, status="running", progress=30, message="拉取资料…")
        data = DouyinAPI.get_user_info(auth, referer)
        pub = _public_user({"user": data.get("user") or {}})
        extra = data.get("user") or {}
        pub["signature"] = extra.get("signature") or ""
        pub["following_count"] = extra.get("following_count") or 0
        pub["total_favorited"] = extra.get("total_favorited") or 0
        _finish_scan(job_id, [pub], f"资料 · {pub.get('nickname')}", pub.get("nickname") or "profile", "user")
    except Exception as exc:
        _append_log(job_id, traceback.format_exc())
        _set_job(job_id, status="error", message=str(exc), progress=100)


def _resolve_user_ids(auth, user_url: str):
    sec_uid, referer = parse_sec_user_id(user_url)
    info = DouyinAPI.get_user_info(auth, referer)
    user = info.get("user") or {}
    uid = str(user.get("uid") or "")
    if not uid:
        raise RuntimeError("未能解析 uid，请确认链接有效且 Cookie 可用")
    return uid, sec_uid, user.get("nickname") or "用户", referer


def _run_followers(job_id: str, payload: dict):
    try:
        auth, _ = _ensure_runtime()
        num = int(payload.get("require_num") or 20)
        _set_job(job_id, status="running", progress=10, message="解析用户…")
        uid, sec, nick, _ = _resolve_user_ids(auth, payload["user_url"].strip())
        _append_log(job_id, f"{nick} 粉丝")
        raw = DouyinAPI.get_some_user_follower_list(auth, uid, sec, num)
        pubs = [_public_user({"user": u}, i) for i, u in enumerate(raw)]
        _finish_scan(job_id, pubs, f"粉丝 {len(pubs)}", f"{nick}-粉丝", "user")
    except Exception as exc:
        _append_log(job_id, traceback.format_exc())
        _set_job(job_id, status="error", message=str(exc), progress=100)


def _run_following(job_id: str, payload: dict):
    try:
        auth, _ = _ensure_runtime()
        num = int(payload.get("require_num") or 20)
        _set_job(job_id, status="running", progress=10, message="解析用户…")
        uid, sec, nick, _ = _resolve_user_ids(auth, payload["user_url"].strip())
        raw = DouyinAPI.get_some_user_following_list(auth, uid, sec, num)
        pubs = [_public_user({"user": u}, i) for i, u in enumerate(raw)]
        _finish_scan(job_id, pubs, f"关注 {len(pubs)}", f"{nick}-关注", "user")
    except Exception as exc:
        _append_log(job_id, traceback.format_exc())
        _set_job(job_id, status="error", message=str(exc), progress=100)


def _run_work_detail(job_id: str, payload: dict):
    try:
        auth, _ = _ensure_runtime()
        url = payload["work_url"].strip()
        _set_job(job_id, status="running", progress=20, message="拉取作品…")
        info = _spider.spider_work(auth, url)
        pub = _public_work(info)
        _finish_scan(job_id, [pub], "作品详情就绪", str(info.get("work_id") or "work"),
                     "work", {str(info["work_id"]): info})
    except Exception as exc:
        _append_log(job_id, traceback.format_exc())
        _set_job(job_id, status="error", message=str(exc), progress=100)


def _run_comments(job_id: str, payload: dict):
    try:
        from webapp.intent_rules import load_intent_rules

        auth, _ = _ensure_runtime()
        url = payload["work_url"].strip()
        aweme_id, refer = parse_aweme_id(url)
        _set_job(job_id, status="running", progress=15, message="拉取评论…")
        raw = DouyinAPI.get_work_all_comment(auth, refer)
        rules = load_intent_rules(INTENT_RULES_PATH)
        pubs = [_public_comment(c, i, intent_rules=rules) for i, c in enumerate(raw)]
        intent_n = sum(1 for row in pubs if row.get("is_intent"))
        _finish_scan(
            job_id, pubs,
            f"评论 {len(pubs)} 条 · 意向 {intent_n}",
            f"comments-{aweme_id}", "comment",
        )
    except Exception as exc:
        _append_log(job_id, traceback.format_exc())
        _set_job(job_id, status="error", message=str(exc), progress=100)


def _run_work_urls(job_id: str, payload: dict):
    try:
        auth, _ = _ensure_runtime()
        urls = [u.strip() for u in (payload.get("urls") or []) if u.strip()]
        if not urls:
            raise ValueError("请至少填一个作品链接")
        name = (payload.get("excel_name") or "works").strip() or "works"
        works, pubs = [], []
        for i, url in enumerate(urls):
            _set_job(job_id, status="running", progress=int(90 * i / max(len(urls), 1)),
                     message=f"扫描 {i + 1}/{len(urls)}")
            info = _spider.spider_work(auth, url)
            works.append(info)
            pubs.append(_public_work(info))
            _set_job(job_id, results=pubs)
        _finish_scan(job_id, pubs, f"扫描完成 · {len(pubs)}", name, "work",
                     {str(w["work_id"]): w for w in works})
    except Exception as exc:
        _append_log(job_id, traceback.format_exc())
        _set_job(job_id, status="error", message=str(exc), progress=100)


def _run_favorites(job_id: str, payload: dict):
    try:
        auth, _ = _ensure_runtime()
        user_url = (payload.get("user_url") or "").strip()
        _set_job(job_id, status="running", progress=10, message="拉取收藏…")
        if user_url:
            sec_uid, referer = parse_sec_user_id(user_url)
            cursor = "0"
            raw_works = []
            while True:
                res = DouyinAPI.get_user_favorite(auth, sec_uid, cursor)
                awemes = res.get("aweme_list") or []
                raw_works.extend(awemes)
                if res.get("has_more") != 1 or len(raw_works) >= int(payload.get("require_num") or 30):
                    break
                cursor = str(res.get("max_cursor") or "0")
                if cursor == "0":
                    break
            limit = int(payload.get("require_num") or 30)
            raw_works = raw_works[:limit]
            works, pubs = [], []
            for i, w in enumerate(raw_works):
                info = handle_work_info(w)
                works.append(info)
                pubs.append(_public_work(info))
                _set_job(job_id, progress=20 + int(70 * (i + 1) / max(len(raw_works), 1)), results=pubs)
            _finish_scan(job_id, pubs, f"收藏作品 {len(pubs)}", f"fav-{sec_uid[:12]}", "work",
                         {str(x["work_id"]): x for x in works})
        else:
            data = DouyinAPI.get_collect_list(auth)
            collects = data.get("collects_list") or data.get("list") or []
            pubs = []
            for i, c in enumerate(collects):
                pubs.append({
                    "kind": "collect",
                    "id": str(c.get("collects_id") or c.get("id") or i),
                    "title": c.get("collects_name") or c.get("name") or f"收藏夹{i+1}",
                    "count": c.get("total_number") or c.get("item_count") or 0,
                })
            _finish_scan(job_id, pubs, f"收藏夹 {len(pubs)}", "collects", "collect")
    except Exception as exc:
        _append_log(job_id, traceback.format_exc())
        _set_job(job_id, status="error", message=str(exc), progress=100)


def _run_feed(job_id: str, payload: dict):
    try:
        auth, _ = _ensure_runtime()
        count = str(payload.get("require_num") or 20)
        _set_job(job_id, status="running", progress=20, message="拉取推荐流…")
        data = DouyinAPI.get_feed(auth, count=count)
        aweme_list = []
        for block in data.get("aweme_list") or data.get("data") or []:
            if isinstance(block, dict) and block.get("aweme_info"):
                aweme_list.append(block["aweme_info"])
            elif isinstance(block, dict) and block.get("aweme_id"):
                aweme_list.append(block)
        if not aweme_list and isinstance(data.get("aweme_list"), list):
            aweme_list = data["aweme_list"]
        works, pubs = [], []
        for i, w in enumerate(aweme_list):
            try:
                info = handle_work_info(w)
            except Exception:
                continue
            works.append(info)
            pubs.append(_public_work(info))
            _set_job(job_id, progress=30 + int(60 * (i + 1) / max(len(aweme_list), 1)), results=pubs)
        _finish_scan(job_id, pubs, f"推荐 {len(pubs)} 条", "feed", "work",
                     {str(x["work_id"]): x for x in works})
    except Exception as exc:
        _append_log(job_id, traceback.format_exc())
        _set_job(job_id, status="error", message=str(exc), progress=100)


def _run_notices(job_id: str, payload: dict):
    try:
        auth, _ = _ensure_runtime()
        num = int(payload.get("require_num") or 20)
        group = str(payload.get("notice_group") or "700")
        _set_job(job_id, status="running", progress=20, message="拉取通知…")
        raw = DouyinAPI.get_some_notice_list(auth, num=num, notice_group=group)
        pubs = [_public_notice(n, i) for i, n in enumerate(raw)]
        _finish_scan(job_id, pubs, f"通知 {len(pubs)} 条", f"notices-{group}", "notice")
    except Exception as exc:
        _append_log(job_id, traceback.format_exc())
        _set_job(job_id, status="error", message=str(exc), progress=100)


def _run_save(job_id: str, payload: dict):
    try:
        _, base_path = _ensure_runtime()
        source_id = payload["source_job_id"]
        ids = [str(x) for x in (payload.get("work_ids") or payload.get("ids") or [])]
        save_choice = payload.get("save_choice") or "all"
        excel_name = (payload.get("excel_name") or "selected").strip() or "selected"
        with _lock:
            source = _jobs.get(source_id) or {}
            works_pool = dict(source.get("_works") or {})
            rows_pool = dict(source.get("_rows") or {})
            result_kind = source.get("result_kind") or "work"

        if not ids:
            raise ValueError("请至少勾选一条")

        _set_job(job_id, status="running", progress=5, message="保存所选…")
        if result_kind == "work" and works_pool:
            selected = []
            for wid in ids:
                item = works_pool.get(wid)
                if item:
                    selected.append(item)
            if not selected:
                raise ValueError("所选作品已失效，请重新扫描")
            total = max(len(selected), 1)
            for i, info in enumerate(selected):
                if save_choice in {"all", "media"} or "media" in str(save_choice):
                    safe_download_work(info, base_path["media"], save_choice)
                _set_job(job_id, progress=10 + int(70 * (i + 1) / total),
                         message=f"处理 {i + 1}/{len(selected)}")
            excel_path = ""
            if save_choice in {"all", "excel"}:
                excel_path = os.path.abspath(os.path.join(base_path["excel"], f"{excel_name}.xlsx"))
                save_to_xlsx(selected, excel_path)
                _append_log(job_id, f"Excel {excel_path}")
            _set_job(job_id, status="done", progress=100, message=f"已保存 {len(selected)} 条",
                     results=[_public_work(w) for w in selected], excel_path=excel_path,
                     count=len(selected), selectable=False)
            return

        # 非作品：导出勾选行为 JSON + 简易 xlsx
        rows = [rows_pool[i] for i in ids if i in rows_pool]
        if not rows:
            raise ValueError("所选数据已失效，请重新扫描")
        export_dir = Path(base_path["excel"])
        json_path = export_dir / f"{excel_name}.json"
        json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        excel_path = ""
        if save_choice in {"all", "excel"}:
            import openpyxl
            excel_path = str(export_dir / f"{excel_name}.xlsx")
            flat = [
                {k: v for k, v in r.items() if not isinstance(v, (list, dict))}
                for r in rows
            ]
            wb = openpyxl.Workbook()
            ws = wb.active
            keys = list(flat[0].keys()) if flat else ["id"]
            ws.append(keys)
            for row in flat:
                ws.append([str(row.get(k, "")) for k in keys])
            wb.save(excel_path)
        _append_log(job_id, f"JSON {json_path}")
        _set_job(job_id, status="done", progress=100, message=f"已导出 {len(rows)} 条",
                 results=rows, excel_path=excel_path, count=len(rows), selectable=False)
    except Exception as exc:
        _append_log(job_id, traceback.format_exc())
        _set_job(job_id, status="error", message=str(exc), progress=100)


RUNNERS = {
    "search_work": _run_search_work,
    "search_user": _run_search_user,
    "search_live": _run_search_live,
    "user_works": _run_user_works,
    "user_profile": _run_user_profile,
    "followers": _run_followers,
    "following": _run_following,
    "work_detail": _run_work_detail,
    "comments": _run_comments,
    "work_urls": _run_work_urls,
    "favorites": _run_favorites,
    "feed": _run_feed,
    "notices": _run_notices,
}


class JobBody(BaseModel):
    module: str
    query: str = ""
    user_url: str = ""
    work_url: str = ""
    urls: list[str] = Field(default_factory=list)
    excel_name: str = "works"
    require_num: int = Field(12, ge=1, le=100)
    sort_type: str = "0"
    publish_time: str = "0"
    filter_duration: str = ""
    search_range: str = "0"
    content_type: str = "0"
    notice_group: str = "700"


class SaveBody(BaseModel):
    source_job_id: str
    work_ids: list[str] = Field(default_factory=list)
    ids: list[str] = Field(default_factory=list)
    save_choice: str = "all"
    excel_name: str = "selected"


class ConfigBody(BaseModel):
    cookies: str = ""
    dump: str = ""
    ua: str = ""
    browser_version: str = ""
    engine_version: str = ""
    screen_width: str = ""
    screen_height: str = ""
    cpu_core_num: str = ""
    device_memory: str = ""
    accept_language: str = ""
    proxy: str = ""
    reload_auth: bool = True


class AgentBody(BaseModel):
    enabled: bool = False
    goal: dict = Field(default_factory=dict)
    persona: dict = Field(default_factory=dict)
    tools: dict = Field(default_factory=dict)
    quotas: dict = Field(default_factory=dict)
    safety: dict = Field(default_factory=dict)


def _cookie_map(cookie: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in re.split(r";\s*", cookie or ""):
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _ensure_sv_web_id(cookie: str, verify_fp: str = "") -> str:
    cmap = _cookie_map(cookie)
    fp = verify_fp or cmap.get("s_v_web_id") or cmap.get("verifyFp") or ""
    if fp and "s_v_web_id" not in cmap:
        cookie = cookie.rstrip("; ") + f"; s_v_web_id={fp}"
    return cookie


def _parse_browser_dump(text: str) -> dict:
    """从 DevTools 复制的 Request URL / Headers 文本中提取 Cookie 与指纹。"""
    raw = (text or "").strip()
    result: dict[str, str] = {}
    if not raw:
        return result

    cookie_m = re.search(
        r"(?im)^(?:cookie|Cookie)\s*[:=]\s*(.+)$", raw
    )
    if cookie_m:
        result["cookies"] = cookie_m.group(1).strip()
    elif "sessionid=" in raw and "\n" not in raw.strip().split("sessionid=")[0][:40]:
        # 整段就是 cookie
        if "Request URL" not in raw and ":authority" not in raw:
            result["cookies"] = raw.strip().strip("'\"")

    ua_m = re.search(r"(?im)^(?:user-agent|User-Agent)\s*[:=]\s*(.+)$", raw)
    if ua_m:
        result["ua"] = ua_m.group(1).strip()

    al_m = re.search(r"(?im)^(?:accept-language|Accept-Language)\s*[:=]\s*(.+)$", raw)
    if al_m:
        result["accept_language"] = al_m.group(1).strip()

    url_m = re.search(r"https?://[^\s]+", raw)
    if url_m:
        url = url_m.group(0).rstrip(")'\",")
        qs = parse_qs(urlparse(url).query)
        mapping = {
            "screen_width": "screen_width",
            "screen_height": "screen_height",
            "cpu_core_num": "cpu_core_num",
            "device_memory": "device_memory",
            "browser_version": "browser_version",
            "engine_version": "engine_version",
            "verifyFp": "verify_fp",
            "fp": "verify_fp",
            "webid": "webid",
        }
        for src, dst in mapping.items():
            vals = qs.get(src)
            if vals and vals[0]:
                result[dst] = unquote(vals[0])

    # 单独的 cookie= 行里可能没有，尝试从整段找 sessionid=
    if "cookies" not in result:
        sess = re.search(r"(sessionid=[^;\s]+(?:;[^;\n]+)*)", raw)
        if sess and "ttwid=" in raw:
            # 抓一段含关键登录 cookie 的串
            block = re.search(
                r"((?:bd_ticket_guard_client_web_domain|passport_csrf_token|sessionid)=.+)",
                raw,
                re.S,
            )
            if block:
                chunk = block.group(1)
                # 截到换行或明显非 cookie 字符前
                chunk = re.split(r"[\r\n]+", chunk, 1)[0].strip()
                if "sessionid=" in chunk:
                    result["cookies"] = chunk

    return result


def _read_env_file() -> dict[str, str]:
    data: dict[str, str] = {}
    if not ENV_PATH.exists():
        return data
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        data[k.strip()] = v.strip().strip("'").strip('"')
    return data


def _write_env_values(updates: dict[str, str]):
    if not ENV_PATH.exists():
        ENV_PATH.write_text("# Douyin Spider local config\n", encoding="utf-8")
    for key, value in updates.items():
        set_key(str(ENV_PATH), key, value if value is not None else "", quote_mode="always")
        os.environ[key] = value if value is not None else ""
    load_dotenv(dotenv_path=str(ENV_PATH), override=True)


def _refresh_fingerprint_bindings():
    """让请求头和签名跟当前 DY_FP_* 走。这两处在进程启动时缓存，只改配置不会更新。"""
    import utils.dy_util as dy_util
    import utils.fingerprint as fingerprint
    from builder.header import HeaderBuilder

    fingerprint._profile = None  # noqa: SLF001
    profile = fingerprint.get_profile()
    HeaderBuilder.ua = profile["ua"]
    HeaderBuilder.sec_ch_ua = profile["sec_ch_ua"]
    HeaderBuilder.sec_ch_ua_platform = profile["sec_ch_ua_platform"]
    HeaderBuilder.accept_language = profile["accept_language"]
    dy_util._pure_signer = None  # noqa: SLF001 — 签名器里的 UA / 屏幕也是启动时冻住的


def _reload_runtime_auth():
    global _auth, _base_path
    import utils.common_util as common_util

    _refresh_fingerprint_bindings()
    common_util.dy_auth = None
    common_util.dy_live_auth = None
    with _lock:
        _auth = None
        _base_path = {}
    return _ensure_runtime()


def _stamp_device_cookies(auth):
    """扫码落盘前，用当前指纹重写设备 Cookie。setdefault 不会覆盖旧屏幕。"""
    from dy_apis.login_api import DYLoginApi

    cookie = getattr(auth, "cookie", None)
    if not isinstance(cookie, dict):
        return
    for name in (
        "dy_swidth", "dy_sheight", "device_web_cpu_core", "device_web_memory_size",
        "stream_recommend_feed_params", "fpk2",
    ):
        cookie.pop(name, None)
    DYLoginApi._add_page_cookies(auth)
    auth.cookie_str = "; ".join(f"{k}={v}" for k, v in auth.cookie.items())


def _config_snapshot() -> dict:
    env = _read_env_file()
    cookies = env.get("DY_COOKIES") or os.getenv("DY_COOKIES") or ""
    cmap = _cookie_map(cookies)
    fp = {k: env.get(k) or os.getenv(k) or "" for k in FP_KEYS}
    return {
        "has_cookies": bool(cookies.strip()),
        "cookie_length": len(cookies),
        "has_sessionid": bool(cmap.get("sessionid")),
        "has_ttwid": bool(cmap.get("ttwid")),
        "has_uifid": bool(cmap.get("UIFID") or cmap.get("uifid")),
        "has_sv_web_id": bool(cmap.get("s_v_web_id")),
        "sessionid_preview": (cmap.get("sessionid") or "")[:8] + "…" if cmap.get("sessionid") else "",
        "fp": {
            "ua": fp["DY_FP_UA"],
            "browser_version": fp["DY_FP_BROWSER_VERSION"],
            "engine_version": fp["DY_FP_ENGINE_VERSION"],
            "screen_width": fp["DY_FP_SCREEN_WIDTH"],
            "screen_height": fp["DY_FP_SCREEN_HEIGHT"],
            "cpu_core_num": fp["DY_FP_CPU_CORE_NUM"],
            "device_memory": fp["DY_FP_DEVICE_MEMORY"],
            "accept_language": fp["DY_FP_ACCEPT_LANGUAGE"],
        },
        "env_path": str(ENV_PATH),
        "proxy": env.get("DY_PROXY") or os.getenv("DY_PROXY") or "",
        "tips": {
            "must": ["cookie 整行（含 sessionid / ttwid / UIFID）", "User-Agent", "屏幕宽高 / CPU / 内存（与浏览器一致）"],
            "ignore": ["msToken", "a_bogus", "x-secsdk-csrf-token", "单次接口 URL（可忽略）"],
        },
    }


@app.get("/")
def index():
    return FileResponse(TEMPLATE_DIR / "index.html")


def _load_agent_config() -> dict:
    from webapp.agent_config import default_agent_config, normalize_agent_config
    if AGENT_PATH.is_file():
        try:
            raw = json.loads(AGENT_PATH.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            raw = None
        return normalize_agent_config(raw)
    if AGENT_EXAMPLE_PATH.is_file():
        try:
            raw = json.loads(AGENT_EXAMPLE_PATH.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            raw = None
        return normalize_agent_config(raw)
    return default_agent_config()


def _write_agent_config(data: dict) -> None:
    AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = AGENT_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(AGENT_PATH)


@app.get("/api/config")
def api_config_get():
    return {"ok": True, **_config_snapshot()}


def _plan_with_queue(agent: dict, *, sync: bool = True) -> tuple[dict, dict]:
    from webapp.agent_plan import build_plan_from_agent
    from webapp.agent_queue import apply_queue_to_plan, queue_snapshot, sync_queue_from_plan
    plan = build_plan_from_agent(agent)
    if sync:
        sync_queue_from_plan(AGENT_QUEUE_PATH, plan)
    queue = queue_snapshot(AGENT_QUEUE_PATH)
    plan = apply_queue_to_plan(plan, {"items": queue.get("items") or []})
    return plan, queue


@app.get("/api/agent")
def api_agent_get():
    agent = _load_agent_config()
    plan, queue = _plan_with_queue(agent, sync=True)
    return {
        "ok": True,
        "agent": agent,
        "plan": plan,
        "queue": queue,
        "path": str(AGENT_PATH),
    }


@app.post("/api/agent")
def api_agent_save(body: AgentBody):
    from webapp.agent_config import validate_agent_config
    try:
        saved = validate_agent_config(body.model_dump())
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    _write_agent_config(saved)
    plan, queue = _plan_with_queue(saved, sync=True)
    return {
        "ok": True,
        "agent": saved,
        "plan": plan,
        "queue": queue,
        "path": str(AGENT_PATH),
    }


@app.get("/api/intent-rules")
def api_intent_rules_get():
    from webapp.intent_rules import load_intent_rules
    return {"ok": True, "rules": load_intent_rules(INTENT_RULES_PATH), "path": str(INTENT_RULES_PATH)}


class IntentRulesBody(BaseModel):
    enabled: bool | None = None
    threshold: int | None = None
    positive: list[str] | None = None
    negative: list[str] | None = None
    extra_positive: list[str] | None = None
    extra_negative: list[str] | None = None


@app.post("/api/intent-rules")
def api_intent_rules_save(body: IntentRulesBody):
    from webapp.intent_rules import load_intent_rules, save_intent_rules
    current = load_intent_rules(INTENT_RULES_PATH)
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    current.update(patch)
    saved = save_intent_rules(INTENT_RULES_PATH, current)
    return {"ok": True, "rules": saved, "path": str(INTENT_RULES_PATH)}


@app.get("/api/agent/plan")
def api_agent_plan_get():
    """按当前已保存策略生成只读今日计划，并同步确认队列。"""
    agent = _load_agent_config()
    plan, queue = _plan_with_queue(agent, sync=True)
    return {"ok": True, "plan": plan, "queue": queue, "path": str(AGENT_PATH)}


@app.post("/api/agent/plan")
def api_agent_plan_preview(body: AgentBody):
    """用表单草稿生成计划预览；可选择是否写入确认队列。"""
    from webapp.agent_config import validate_agent_config
    from webapp.agent_plan import build_plan_from_agent
    from webapp.agent_queue import apply_queue_to_plan, queue_snapshot, sync_queue_from_plan
    try:
        agent = validate_agent_config(body.model_dump())
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    plan = build_plan_from_agent(agent)
    sync_queue_from_plan(AGENT_QUEUE_PATH, plan)
    queue = queue_snapshot(AGENT_QUEUE_PATH)
    plan = apply_queue_to_plan(plan, {"items": queue.get("items") or []})
    return {"ok": True, "plan": plan, "queue": queue, "draft": True}


class QueueDecisionBody(BaseModel):
    action: str  # approve | reject


@app.get("/api/agent/queue")
def api_agent_queue_get():
    from webapp.agent_queue import queue_snapshot
    return {"ok": True, "queue": queue_snapshot(AGENT_QUEUE_PATH), "path": str(AGENT_QUEUE_PATH)}


@app.post("/api/agent/queue/{item_id}")
def api_agent_queue_decide(item_id: str, body: QueueDecisionBody):
    from webapp.agent_queue import decide_queue_item
    action = (body.action or "").strip().lower()
    if action not in ("approve", "reject"):
        raise HTTPException(400, "action 仅为 approve 或 reject")
    try:
        item = decide_queue_item(AGENT_QUEUE_PATH, item_id, approve=(action == "approve"))
    except KeyError:
        raise HTTPException(404, "确认条目不存在") from None
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    agent = _load_agent_config()
    plan, queue = _plan_with_queue(agent, sync=False)
    return {
        "ok": True,
        "item": item,
        "plan": plan,
        "queue": queue,
    }


class WorkerRunBody(BaseModel):
    item_id: str = ""


@app.post("/api/agent/worker/run")
def api_agent_worker_run(body: WorkerRunBody = WorkerRunBody()):
    """对已批准步骤跑只读准备（搜作品/拉评论候选），不写抖音。"""
    from webapp.agent_worker import run_readonly_prep
    try:
        auth, _ = _ensure_runtime()
    except Exception as error:
        raise HTTPException(400, f"会话未就绪：{error}") from error
    if not getattr(auth, "cookie", None):
        raise HTTPException(400, "请先在会话配置登录后再跑只读准备")
    agent = _load_agent_config()
    result = run_readonly_prep(
        queue_path=AGENT_QUEUE_PATH,
        agent=agent,
        auth=auth,
        item_id=(body.item_id or "").strip() or None,
    )
    plan, queue = _plan_with_queue(agent, sync=False)
    return {
        "ok": bool(result.get("ok")),
        "message": result.get("message") or "",
        "ran": result.get("ran") or [],
        "plan": plan,
        "queue": queue,
    }


class WorkerWriteBody(BaseModel):
    item_id: str = ""
    action: str = "draft"  # draft | execute
    dry_run: bool = False


class WorkerSelectBody(BaseModel):
    item_id: str
    work_ids: list[str] | None = None
    comment_cids: list[str] | None = None
    work_min_digg: int | None = None
    comment_min_digg: int | None = None
    comment_keyword: str | None = None
    comment_exclude: str | None = None
    max_comments_per_work: int | None = None
    intent_only: bool | None = None
    comment_ip_label: str | None = None
    comment_gender: str | None = None


@app.post("/api/agent/worker/select")
def api_agent_worker_select(body: WorkerSelectBody):
    """勾选/筛选只读准备里的作品与评论候选。"""
    from webapp.agent_worker import update_candidate_selection

    item_id = (body.item_id or "").strip()
    if not item_id:
        raise HTTPException(400, "缺少 item_id")
    filters = {}
    for key in (
        "work_min_digg", "comment_min_digg", "comment_keyword",
        "comment_exclude", "max_comments_per_work", "intent_only",
        "comment_ip_label", "comment_gender",
    ):
        value = getattr(body, key, None)
        if value is not None:
            filters[key] = value
    try:
        updated = update_candidate_selection(
            queue_path=AGENT_QUEUE_PATH,
            item_id=item_id,
            work_ids=body.work_ids,
            comment_cids=body.comment_cids,
            filters=filters or None,
        )
    except KeyError as error:
        raise HTTPException(404, f"队列项不存在：{error}") from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    agent = _load_agent_config()
    plan, queue = _plan_with_queue(agent, sync=False)
    return {
        "ok": True,
        "item": updated,
        "message": (updated.get("worker_result") or {}).get("message") or "筛选已更新",
        "plan": plan,
        "queue": queue,
    }



@app.post("/api/agent/worker/write")
def api_agent_worker_write(body: WorkerWriteBody = WorkerWriteBody()):
    """生成评论草稿，或执行已草稿的评论发布。"""
    from webapp.agent_worker import run_write_drafts, run_write_execute

    action = (body.action or "draft").strip().lower()
    item_id = (body.item_id or "").strip() or None
    agent = _load_agent_config()
    if action == "draft":
        result = run_write_drafts(
            queue_path=AGENT_QUEUE_PATH,
            agent=agent,
            item_id=item_id,
        )
    elif action == "execute":
        try:
            auth, _ = _ensure_runtime()
        except Exception as error:
            raise HTTPException(400, f"会话未就绪：{error}") from error
        if not getattr(auth, "cookie", None):
            raise HTTPException(400, "请先在会话配置登录后再执行写操作")
        result = run_write_execute(
            queue_path=AGENT_QUEUE_PATH,
            agent=agent,
            auth=auth,
            item_id=item_id,
            dry_run=bool(body.dry_run),
        )
    else:
        raise HTTPException(400, "action 仅支持 draft / execute")
    plan, queue = _plan_with_queue(agent, sync=False)
    return {
        "ok": bool(result.get("ok")),
        "message": result.get("message") or "",
        "ran": result.get("ran") or [],
        "plan": plan,
        "queue": queue,
    }


@app.post("/api/config/parse")
def api_config_parse(body: ConfigBody):
    parsed = _parse_browser_dump(body.dump or body.cookies)
    return {"ok": True, "parsed": parsed}


@app.post("/api/config")
def api_config_save(body: ConfigBody):
    parsed = _parse_browser_dump(body.dump) if body.dump.strip() else {}
    cookies = (body.cookies or parsed.get("cookies") or "").strip()
    if not cookies and body.dump.strip():
        # dump 本身可能整段就是 cookie
        maybe = body.dump.strip()
        if "sessionid=" in maybe:
            cookies = _parse_browser_dump(maybe).get("cookies") or maybe

    if cookies and "sessionid=" not in cookies:
        raise HTTPException(400, "Cookie 中缺少 sessionid，请确认已登录后复制")

    verify_fp = parsed.get("verify_fp") or ""
    if cookies:
        cookies = _ensure_sv_web_id(cookies, verify_fp)

    ua = (body.ua or parsed.get("ua") or "").strip()
    browser_version = (body.browser_version or parsed.get("browser_version") or "").strip()
    engine_version = (body.engine_version or parsed.get("engine_version") or browser_version).strip()
    screen_width = (body.screen_width or parsed.get("screen_width") or "").strip()
    screen_height = (body.screen_height or parsed.get("screen_height") or "").strip()
    cpu_core_num = (body.cpu_core_num or parsed.get("cpu_core_num") or "").strip()
    device_memory = (body.device_memory or parsed.get("device_memory") or "").strip()
    accept_language = (body.accept_language or parsed.get("accept_language") or "").strip()
    proxy = (body.proxy or "").strip()

    updates = {}
    if cookies:
        updates["DY_COOKIES"] = cookies
    if ua:
        updates["DY_FP_UA"] = ua
    if browser_version:
        updates["DY_FP_BROWSER_VERSION"] = browser_version
    if engine_version:
        updates["DY_FP_ENGINE_VERSION"] = engine_version
    if screen_width:
        updates["DY_FP_SCREEN_WIDTH"] = screen_width
    if screen_height:
        updates["DY_FP_SCREEN_HEIGHT"] = screen_height
    if cpu_core_num:
        updates["DY_FP_CPU_CORE_NUM"] = cpu_core_num
    if device_memory:
        updates["DY_FP_DEVICE_MEMORY"] = device_memory
    if accept_language:
        updates["DY_FP_ACCEPT_LANGUAGE"] = accept_language
    updates["DY_PROXY"] = proxy

    if "DY_COOKIES" not in updates:
        existing = (_read_env_file().get("DY_COOKIES") or os.getenv("DY_COOKIES") or "").strip()
        if not existing:
            raise HTTPException(400, "请粘贴 Cookie（或含 cookie: 行的抓包文本）")

    _write_env_values(updates)

    status = {"ok": True, "saved_keys": list(updates.keys()), **_config_snapshot()}
    if body.reload_auth:
        try:
            auth, _ = _reload_runtime_auth()
            cookie = auth.cookie or {}
            uid = None
            try:
                uid = DouyinAPI.get_my_uid(auth)
            except Exception:
                uid = None
            status["reloaded"] = True
            status["logged_in"] = bool(cookie.get("sessionid"))
            status["uid"] = uid
        except Exception as exc:
            status["reloaded"] = False
            status["reload_error"] = str(exc)
    return status


class ActionCommentBody(BaseModel):
    aweme_id: str = ""
    work_url: str = ""
    content: str = ""
    reply_id: str = ""


class ActionDiggBody(BaseModel):
    aweme_id: str = ""
    work_url: str = ""
    action: str = "1"


class ActionCollectBody(BaseModel):
    aweme_id: str = ""
    work_url: str = ""
    action: str = "1"


def _action_auth():
    """写操作要求已登录，否则底层只会返回空响应，排查成本很高。"""
    auth, _ = _ensure_runtime()
    cookie = getattr(auth, "cookie", None) or {}
    if not cookie.get("sessionid"):
        raise HTTPException(400, "未登录：请先在「会话配置」扫码或粘贴 Cookie")
    return auth


def _action_target(body) -> str:
    target = (body.aweme_id or body.work_url or "").strip()
    if not target:
        raise HTTPException(400, "缺少作品 ID 或链接")
    return target


@app.post("/api/action/comment")
def api_action_comment(body: ActionCommentBody):
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(400, "评论内容不能为空")
    if len(content) > 200:
        raise HTTPException(400, "评论最多 200 字")
    target = _action_target(body)
    auth = _action_auth()
    try:
        resp = DouyinAPI.publish_comment(
            auth, target, content, reply_id=(body.reply_id or "").strip(),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc))
    ok = isinstance(resp, dict) and resp.get("status_code") == 0
    msg = "评论已发布" if ok else (
        (resp or {}).get("status_msg") or (resp or {}).get("message") or "发布失败"
    )
    return {"ok": ok, "message": msg, "detail": resp}


@app.post("/api/action/digg")
def api_action_digg(body: ActionDiggBody):
    action = "0" if str(body.action) == "0" else "1"
    target = _action_target(body)
    auth = _action_auth()
    try:
        ok = bool(DouyinAPI.digg(auth, target, action))
    except Exception as exc:
        raise HTTPException(400, str(exc))
    label = "已点赞" if action == "1" else "已取消点赞"
    return {"ok": ok, "message": label if ok else "操作失败", "action": action}


@app.post("/api/action/collect")
def api_action_collect(body: ActionCollectBody):
    action = "0" if str(body.action) == "0" else "1"
    target = _action_target(body)
    auth = _action_auth()
    try:
        resp = DouyinAPI.collect_aweme(auth, target, action)
    except Exception as exc:
        raise HTTPException(400, str(exc))
    ok = isinstance(resp, dict) and resp.get("status_code") == 0
    label = "已收藏" if action == "1" else "已取消收藏"
    msg = label if ok else ((resp or {}).get("status_msg") or "操作失败")
    return {"ok": ok, "message": msg, "action": action}


# ===== 素材库 =====
MEDIA_UPLOAD_DIR = ROOT / "datas" / "media_uploads"
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
MEDIA_SUFFIX_KIND = {
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".webp": "image",
    ".gif": "image", ".bmp": "image",
    ".mp4": "video", ".mov": "video", ".avi": "video", ".mkv": "video",
    ".webm": "video",
}


def _media_root() -> Path:
    MEDIA_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return MEDIA_UPLOAD_DIR


def _media_kind(name: str) -> str:
    return MEDIA_SUFFIX_KIND.get(Path(name).suffix.lower(), "file")


def _media_public(name: str) -> dict:
    stat = (_media_root() / name).stat()
    return {
        "name": name,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "kind": _media_kind(name),
        "url": f"/api/media/preview/{name}",
    }


def _media_path(name: str) -> Path:
    raw = (name or "").strip()
    if not raw or "/" in raw or "\\" in raw or ".." in raw:
        raise HTTPException(400, "非法素材名")
    path = _media_root() / raw
    if not path.is_file():
        raise HTTPException(404, "素材不存在")
    return path


async def _save_upload(upload: UploadFile) -> dict:
    original = Path(upload.filename or "file").name
    stem = re.sub(r"[^\w\u4e00-\u9fa5.-]+", "_", Path(original).stem).strip("._") or "file"
    suffix = Path(original).suffix.lower()
    name = f"{stem[:48]}-{uuid.uuid4().hex[:8]}{suffix}"
    path = _media_root() / name
    size = 0
    try:
        with path.open("wb") as fh:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(400, "文件超过 500MB 上限")
                fh.write(chunk)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(400, f"保存素材失败: {exc}") from exc
    finally:
        await upload.close()
    if size == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(400, "文件为空")
    return _media_public(name)


@app.post("/api/media/upload")
async def api_media_upload(file: UploadFile = File(...)):
    return {"ok": True, "item": await _save_upload(file)}


@app.get("/api/media/list")
def api_media_list():
    files = sorted(
        (p for p in _media_root().iterdir() if p.is_file() and not p.name.startswith(".")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:60]
    return {"ok": True, "items": [_media_public(p.name) for p in files]}


@app.get("/api/media/preview/{name}")
def api_media_preview(name: str):
    return FileResponse(_media_path(name))


# ===== 私信 =====
class CreateDmBody(BaseModel):
    target: str = ""
    text: str = ""
    media_name: str = ""
    media_kind: str = "text"  # text | image | video | file


def _dm_target_uid(auth, target: str) -> int:
    if target.isdigit():
        return int(target)
    try:
        uid, _sec, _nick, _referer = _resolve_user_ids(auth, target)
    except Exception as exc:
        raise HTTPException(400, f"目标用户解析失败：{exc}") from exc
    return int(uid)


@app.post("/api/create/dm")
def api_create_dm(body: CreateDmBody):
    target = (body.target or "").strip()
    if not target:
        raise HTTPException(400, "缺少目标用户（主页链接或 uid）")
    kind = (body.media_kind or "text").strip().lower()
    if kind not in {"text", "image", "video", "file"}:
        raise HTTPException(400, f"不支持的私信类型: {kind}")
    text = (body.text or "").strip()
    if kind == "text" and not text:
        raise HTTPException(400, "私信内容不能为空")
    path = None
    if kind != "text":
        path = _media_path(body.media_name)
        if _media_kind(path.name) != kind:
            raise HTTPException(400, f"素材 {path.name} 不是 {kind} 类型")
    auth = _action_auth()
    uid = _dm_target_uid(auth, target)
    try:
        conversation_id, conversation_short_id, ticket = DouyinAPI.create_conversation(auth, uid)
    except Exception as exc:
        raise HTTPException(400, f"创建会话失败：{exc}") from exc
    try:
        if kind == "text":
            ok = bool(DouyinAPI.send_msg(
                auth, conversation_id, conversation_short_id, ticket, text,
            ))
        elif kind == "image":
            ok = bool(DouyinAPI.send_image(
                auth, conversation_id, conversation_short_id, ticket, str(path),
            ))
        elif kind == "video":
            ok = bool(DouyinAPI.send_video(
                auth, conversation_id, conversation_short_id, ticket, str(path),
            ))
        else:
            ok = bool(DouyinAPI.send_file(
                auth, conversation_id, conversation_short_id, ticket, str(path),
            ))
    except Exception as exc:
        raise HTTPException(400, f"发送失败：{exc}") from exc
    return {
        "ok": ok,
        "message": "私信已发送" if ok else "私信发送失败（接口未返回 OK）",
        "conversation_id": conversation_id,
        "media_kind": kind,
    }


# ===== 发布视频 =====
@app.get("/api/create/publish/preflight")
def api_publish_preflight():
    """只做 create_v2 风控素材校验，不发送任何请求。"""
    from dy_apis.douyin_creator_api import DouyinCreatorAPI

    auth = _action_auth()
    try:
        DouyinCreatorAPI._require_publish_security(auth)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "message": "发布安全凭据校验通过"}


@app.post("/api/create/publish")
async def api_create_publish(
    file: UploadFile = File(...),
    title: str = Form(""),
    desc: str = Form(""),
    visibility: int = Form(1),
    allow_download: bool = Form(True),
):
    from dy_apis.douyin_creator_api import DouyinCreatorAPI

    auth = _action_auth()
    # 上传前先校验，避免几百 MB 视频白传一趟。
    try:
        DouyinCreatorAPI._require_publish_security(auth)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc

    if MEDIA_SUFFIX_KIND.get(Path(file.filename or "").suffix.lower()) != "video":
        raise HTTPException(400, "发布只接受视频文件（mp4/mov/avi/mkv/webm）")
    title = (title or "").strip()
    if len(title) > 20:
        raise HTTPException(400, "标题最多 20 字")
    desc = (desc or "").strip()
    vis = int(visibility)
    if vis not in (0, 1, 2):
        raise HTTPException(400, "可见范围只能是 0 / 1 / 2")

    item = await _save_upload(file)
    path = _media_root() / item["name"]
    try:
        ok, msg, res_json = DouyinCreatorAPI.post_video(
            auth, str(path),
            title=title,
            desc=desc,
            visibility=vis,
            allow_download=bool(allow_download),
        )
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "ok": bool(ok),
        "message": msg or ("发布成功" if ok else "发布失败"),
        "media": item,
        "detail": res_json,
    }


@app.get("/api/modules")
def api_modules():
    return {"modules": MODULES}


@app.get("/api/status")
def api_status():
    try:
        auth, base_path = _ensure_runtime()
        cookie = auth.cookie or {}
        uid = None
        try:
            uid = DouyinAPI.get_my_uid(auth)
        except Exception:
            uid = None
        excel_dir = Path(base_path["excel"])
        excels = sorted(
            (
                p
                for p in excel_dir.glob("*.xlsx")
                if not p.name.startswith("~$") and not p.name.startswith(".")
            ),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:30]
        return {
            "ok": True,
            "logged_in": bool(cookie.get("sessionid")),
            "uid": uid,
            "excel_dir": str(excel_dir),
            "media_dir": base_path["media"],
            "excels": [
                {"name": p.name, "size": p.stat().st_size, "mtime": p.stat().st_mtime}
                for p in excels
            ],
            "modules": MODULES,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "logged_in": False, "modules": MODULES}


@app.post("/api/jobs/run")
def api_run(body: JobBody):
    module = body.module
    if module not in RUNNERS:
        raise HTTPException(400, f"未知模块: {module}")
    return _start_job(module, RUNNERS[module], body.model_dump())


@app.post("/api/jobs/save")
def api_save(body: SaveBody):
    return _start_job("save", _run_save, body.model_dump())


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        return {k: v for k, v in job.items() if not str(k).startswith("_")}


@app.get("/api/excels/{name}")
def api_excel_download(name: str):
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "非法文件名")
    _, base_path = _ensure_runtime()
    path = Path(base_path["excel"]) / name
    if not path.is_file():
        # also allow json
        path = Path(base_path["excel"]) / name
        if not path.is_file():
            raise HTTPException(404, "文件不存在")
    return FileResponse(path, filename=name)


@app.get("/api/cover")
def api_cover_proxy(u: str = ""):
    """代理抖音封面（直连失败时的兜底）。保留签名查询串，避免二次解码破坏 x-signature。"""
    raw = (u or "").strip()
    if not raw or len(raw) > 2500:
        raise HTTPException(400, "无效封面地址")
    # FastAPI 已对 query 解码一次；签名里的 %2F 需保持，勿再 unquote
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(400, "无效封面地址")
    if not _cover_host_allowed(parsed.netloc):
        raise HTTPException(403, "域名不允许")
    try:
        # 用原始字符串请求，防止 requests 改写 query 编码
        resp = requests.get(
            raw,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.douyin.com/",
                "Origin": "https://www.douyin.com",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
            timeout=12,
            allow_redirects=True,
        )
        if resp.status_code >= 400:
            raise HTTPException(resp.status_code, "封面拉取失败")
        ctype = (resp.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
        if not ctype.startswith("image/"):
            ctype = "image/jpeg"
        data = resp.content[: 2 * 1024 * 1024]
        return Response(
            content=data,
            media_type=ctype,
            headers={
                "Cache-Control": "public, max-age=86400",
                "Content-Disposition": "inline",
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"封面代理失败: {exc}") from exc


def _qr_public() -> dict:
    with _qr_lock:
        status = _qr.get("status") or "idle"
        message = _qr.get("message") or ""
        url = _qr.get("qr_url") or ""
        images = _qr.get("_images") or {}
        cached = images.get(url, "") if url in images else None
    if url and cached is None:
        cached = _qr_png(url)
    return {
        "status": status,
        "message": message,
        "qr_url": url,
        "image": cached or "",
    }


def _qr_png(url: str) -> str:
    if not url:
        return ""
    cached = _qr.get("_images") or {}
    if url in cached:
        return cached[url]
    image = ""
    try:
        import base64
        from io import BytesIO
        import qrcode
        img = qrcode.make(url, border=1)
        buf = BytesIO()
        img.save(buf, format="PNG")
        image = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        image = ""
    cached = dict(cached)
    cached[url] = image
    if len(cached) > 4:
        cached = dict(list(cached.items())[-4:])
    with _qr_lock:
        _qr["_images"] = cached
    return image


def _set_qr(**fields):
    with _qr_lock:
        _qr.update(fields)


def _set_qr_for(generation: int, **fields):
    with _qr_lock:
        if generation != _qr_generation:
            return
        _qr.update(fields)


def _persist_login(auth):
    updates = {"DY_COOKIES": auth.cookie_str}
    for key, value in (
        ("DY_TICKET", getattr(auth, "ticket", None) or ""),
        ("DY_TS_SIGN", getattr(auth, "ts_sign", None) or ""),
        ("DY_CLIENT_CERT", getattr(auth, "client_cert", None) or ""),
        ("DY_PRIVATE_KEY", getattr(auth, "private_key", None) or ""),
    ):
        if value:
            updates[key] = value
    _write_env_values(updates)


def _qr_worker(generation: int):
    try:
        from dy_apis.login_api import DYLoginApi
        _refresh_fingerprint_bindings()
        proxies = proxies_from_url(os.getenv("DY_PROXY"))

        def on_qrcode(url):
            _set_qr_for(generation, status="waiting", qr_url=url or "", message="请用抖音 App 扫码")

        def on_status(info):
            status = info.get("status") or "waiting"
            message = {
                "waiting": "请用抖音 App 扫码",
                "scanned": "已扫码，请在手机上确认",
                "expired": "二维码已过期，正在换一张",
                "confirmed": "已确认，正在写入会话…",
                "throttled": info.get("message") or "访问频繁，稍后重试",
            }.get(status, status)
            fields = {"status": status, "message": message}
            if info.get("qr_url"):
                fields["qr_url"] = info["qr_url"]
            _set_qr_for(generation, **fields)

        auth = DYLoginApi().qrcode_login(
            timeout=180,
            show_qr=False,
            on_qrcode=on_qrcode,
            on_status=on_status,
            proxies=proxies,
        )
        with _qr_lock:
            if generation != _qr_generation:
                return
            _stamp_device_cookies(auth)
            _persist_login(auth)
        auth, _ = _reload_runtime_auth()
        uid = None
        try:
            uid = DouyinAPI.get_my_uid(auth)
        except Exception:
            uid = None
        message = "登录成功"
        if uid:
            message += f" · uid {uid}"
        _set_qr_for(generation, status="confirmed", message=message, qr_url="")
    except TimeoutError:
        _set_qr_for(generation, status="timeout", message="扫码超时，请重新生成", qr_url="")
    except Exception as exc:
        _set_qr_for(generation, status="error", message=str(exc))


class LiveStartBody(BaseModel):
    live: str = ""


@app.get("/api/login/qr")
def api_login_qr_status():
    return {"ok": True, **_qr_public()}


@app.post("/api/session/clear")
def api_session_clear(body: ConfigBody):
    """清掉登录 Cookie 和票据，保留当前表单里的指纹与代理。"""
    global _qr_generation
    updates = {key: "" for key in _SESSION_KEYS}
    ua = (body.ua or "").strip()
    browser_version = (body.browser_version or "").strip()
    engine_version = (body.engine_version or browser_version).strip()
    screen_width = (body.screen_width or "").strip()
    screen_height = (body.screen_height or "").strip()
    cpu_core_num = (body.cpu_core_num or "").strip()
    device_memory = (body.device_memory or "").strip()
    accept_language = (body.accept_language or "").strip()
    if ua:
        updates["DY_FP_UA"] = ua
    if browser_version:
        updates["DY_FP_BROWSER_VERSION"] = browser_version
    if engine_version:
        updates["DY_FP_ENGINE_VERSION"] = engine_version
    if screen_width:
        updates["DY_FP_SCREEN_WIDTH"] = screen_width
    if screen_height:
        updates["DY_FP_SCREEN_HEIGHT"] = screen_height
    if cpu_core_num:
        updates["DY_FP_CPU_CORE_NUM"] = cpu_core_num
    if device_memory:
        updates["DY_FP_DEVICE_MEMORY"] = device_memory
    if accept_language:
        updates["DY_FP_ACCEPT_LANGUAGE"] = accept_language
    updates["DY_PROXY"] = (body.proxy or "").strip()
    with _qr_lock:
        _qr_generation += 1
        _qr.update(
            status="idle",
            qr_url="",
            message="会话已清空，请重新生成二维码",
            _images={},
        )
        # 进行中的扫码若刚好写回 Cookie，也要在同一把锁里再清掉。
        _write_env_values(updates)
    try:
        _reload_runtime_auth()
        reloaded = True
        reload_error = ""
    except Exception as exc:
        reloaded = False
        reload_error = str(exc)
    return {
        "ok": True,
        "cleared": True,
        "reloaded": reloaded,
        "reload_error": reload_error,
        "logged_in": False,
        "uid": None,
        **_config_snapshot(),
        **_qr_public(),
        "message": "已清空登录。指纹和代理还在，请重新扫码。",
    }


@app.post("/api/login/qr")
def api_login_qr_start():
    global _qr_thread
    with _qr_lock:
        alive = _qr_thread is not None and _qr_thread.is_alive()
        if alive and _qr.get("status") not in {"confirmed", "error", "timeout", "idle"}:
            current = {
                "status": _qr.get("status") or "idle",
                "message": _qr.get("message") or "",
                "qr_url": _qr.get("qr_url") or "",
            }
        else:
            current = None
            _qr.update(status="starting", qr_url="", message="正在获取二维码…")
            _qr_thread = threading.Thread(
                target=_qr_worker, args=(_qr_generation,), daemon=True, name="qr-login",
            )
            _qr_thread.start()
    if current is not None:
        current["image"] = _qr_png(current.get("qr_url") or "")
        return {"ok": True, **current}
    return {"ok": True, **_qr_public()}


@app.post("/api/live/start")
def api_live_start(body: LiveStartBody):
    auth, _ = _ensure_runtime()
    if not (getattr(auth, "cookie", None) or {}).get("sessionid"):
        raise HTTPException(400, "请先在会话配置里粘贴 Cookie 或扫码登录")
    try:
        return {"ok": True, **_live.start(body.live, auth)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/live/stop")
def api_live_stop():
    return {"ok": True, **_live.stop()}


@app.get("/api/live")
def api_live_state(since: int = 0):
    return {"ok": True, **_live.snapshot(since)}


@app.get("/api/live/ranks")
def api_live_ranks():
    auth, _ = _ensure_runtime()
    try:
        ranks = fetch_ranks(auth, _live.snapshot()["room"])
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, **ranks}


@app.post("/api/live/export")
def api_live_export():
    rows = [row for row in _live.rows() if row.get("kind") != "heat"]
    if not rows:
        raise HTTPException(400, "还没有可导出的消息")
    _, base_path = _ensure_runtime()
    room = _live.snapshot().get("room") or {}
    name = f"live-{room.get('web_rid') or 'room'}.xlsx"
    path = Path(base_path["excel"]) / name
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "直播"
    ws.append(["时间", "类型", "用户", "内容"])
    for row in rows:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(row.get("ts") or time.time()))
        ws.append([
            stamp,
            KIND_LABEL.get(row.get("kind"), row.get("kind") or ""),
            row.get("user") or "",
            row.get("text") or "",
        ])
    wb.save(path)
    return {"ok": True, "name": path.name}


def main():
    import uvicorn
    _ensure_runtime()
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("DY_WEB_PORT") or "19527"),
                reload=False, log_level="info")


if __name__ == "__main__":
    main()
