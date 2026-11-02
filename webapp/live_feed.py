"""直播间只读监听：弹幕 / 礼物 / 进场 / 点赞，以及房间热度。"""
from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from dy_apis.douyin_api import DouyinAPI, LivePKAPIError, _live_web_rid
from dy_live.pk import PK_MESSAGES
from dy_live.server import DouyinLive
from dy_live.user_db import UserDB

ROOT = Path(__file__).resolve().parents[1]
STORE_DIR = ROOT / "datas" / "live_monitor"
MAX_EVENTS = 800

KIND_LABEL = {
    "chat": "弹幕",
    "gift": "礼物",
    "enter": "进场",
    "like": "点赞",
    "social": "关注",
    "emoji": "表情",
    "pk": "PK",
    "control": "状态",
    "system": "系统",
}


def _nick(message) -> str:
    user = getattr(message, "user", None)
    return str(getattr(user, "nickname", "") or "")


def _display(message, attr: str = "display_text") -> str:
    common = getattr(message, "common", None)
    text = getattr(common, attr, None) if common is not None else getattr(message, attr, None)
    if text is None:
        return ""
    try:
        from dy_live.utils.renderer import render_text
        return render_text(text) or ""
    except Exception:
        return ""


def summarize_message(name: str, message) -> dict | None:
    """把一条直播 protobuf 收成页面用的短事件。PK 原消息交给 on_pk_event。"""
    if name in PK_MESSAGES:
        return None
    if name == "ChatMessage":
        text = str(getattr(message, "content", "") or "")
        if not text:
            return None
        return {"kind": "chat", "user": _nick(message), "text": text}
    if name == "EmojiChatMessage":
        return {"kind": "emoji", "user": _nick(message), "text": _display(message, "emoji_content") or "表情"}
    if name == "GiftMessage":
        gift = getattr(message, "gift", None)
        gift_name = str(getattr(gift, "name", "") or "礼物")
        combo = int(getattr(message, "combo_count", 0) or 0)
        ended = bool(getattr(message, "repeat_end", 0))
        if combo > 1 and not ended:
            return None
        return {"kind": "gift", "user": _nick(message), "text": f"{gift_name} ×{combo or 1}"}
    if name == "BindingGiftMessage":
        text = str(getattr(getattr(message, "common", None), "describe", "") or "")
        if not text:
            return None
        return {"kind": "gift", "user": _nick(message), "text": text}
    if name == "LikeMessage":
        count = int(getattr(message, "count", 0) or 0)
        total = int(getattr(message, "total", 0) or 0)
        return {
            "kind": "like",
            "user": _nick(message),
            "text": f"点了 {count} 个赞",
            "total": total,
        }
    if name == "MemberMessage":
        action = int(getattr(message, "action", 0) or 0)
        text = _display(message)
        if action == 1:
            return {"kind": "enter", "user": _nick(message), "text": text or "进入直播间"}
        if action in (8, 20):
            return {"kind": "social", "user": _nick(message), "text": text or ("分享了直播间" if action == 8 else "关注了主播")}
        return None
    if name == "SocialMessage":
        text = _display(message)
        if not text:
            return None
        return {"kind": "social", "user": _nick(message), "text": text}
    if name in ("RoomUserSeqMessage", "RoomStatsMessage"):
        if name == "RoomUserSeqMessage":
            online = str(getattr(message, "total_str", "") or getattr(message, "total", "") or "")
        else:
            online = str(getattr(message, "display_middle", "") or getattr(message, "total", "") or "")
        if not online:
            return None
        return {"kind": "heat", "online": online}
    if name == "ControlMessage":
        action = int(getattr(message, "action", 0) or 0)
        if action in (3, 4, 6):
            return {"kind": "control", "text": str(getattr(message, "tips", "") or "直播已结束")}
        return None
    return None


def summarize_pk(event: dict) -> dict:
    labels = {
        "start": "PK 开始",
        "status": "PK 状态",
        "scores": "PK 比分",
        "armies": "PK 贡献",
        "finish": "PK 结束",
    }
    kind = event.get("type") or "status"
    parts = [labels.get(kind, "PK")]
    scores = event.get("scores") or []
    if scores:
        bits = []
        for row in scores:
            score = row.get("score_blur_text") or row.get("score") or ""
            bits.append(f"{row.get('anchor_id') or '主播'} {score}".strip())
        parts.append(" · ".join(bits))
    return {"kind": "pk", "text": " ".join(parts), "pk_type": kind}


def flatten_rank_users(payload, limit: int = 30) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    rows = []
    if isinstance(data, dict):
        for key in ("ranks", "rank_list", "user_list", "users", "seats"):
            if isinstance(data.get(key), list):
                rows = data[key]
                break
    elif isinstance(data, list):
        rows = data
    out = []
    for index, row in enumerate(rows[:limit]):
        if not isinstance(row, dict):
            continue
        user = row.get("user") or row.get("user_info") or {}
        if not isinstance(user, dict):
            user = {}
        nickname = user.get("nickname") or user.get("nick_name") or row.get("nickname") or ""
        score = row.get("score")
        blur = row.get("score_blur_text") or row.get("score_str") or ""
        if score in (None, "") and not blur and not nickname:
            continue
        out.append({
            "rank": row.get("rank") or index + 1,
            "nickname": nickname or "未知用户",
            "score": blur or ("" if score is None else score),
        })
    return out


def public_pk_rank(result: dict) -> dict:
    state = result.get("state") or "not_in_pk"
    context = result.get("context") or {}
    names = {
        str(item.get("anchor_id")): item.get("nickname") or ""
        for item in (context.get("anchors") or [])
    }
    sides = []
    for anchor_id, raw in (result.get("ranks") or {}).items():
        raw = raw if isinstance(raw, dict) else {}
        sides.append({
            "anchor_id": str(anchor_id),
            "nickname": names.get(str(anchor_id)) or str(anchor_id),
            "ok": raw.get("status_code") == 0,
            "users": flatten_rank_users(raw),
        })
    messages = {
        "not_in_pk": "当前没有进行中的 PK",
        "ok": "PK 榜已更新",
        "context_changed": "对局刚刚切换，请再拉一次",
        "api_error": "榜单接口返回错误",
    }
    return {
        "state": state,
        "battle_id": context.get("battle_id"),
        "finished": context.get("finished"),
        "sides": sides,
        "message": messages.get(state, state),
    }


class _WorkbenchLive(DouyinLive):
    def __init__(self, live_id: str, auth, on_event, store_dir: Path):
        super().__init__(live_id, auth, on_pk_event=self._on_pk, record=False)
        self._on_event = on_event
        self.store_dir = store_dir
        self._stopped = False
        wrapped = {}
        for name, fn in list(self.message_readers.items()):
            wrapped[name] = self._wrap(name, fn)
        self.message_readers = wrapped

    def _wrap(self, name, fn):
        def inner(message):
            try:
                event = summarize_message(name, message)
            except Exception:
                event = None
            if event:
                self._on_event(event)
            return fn(message)
        return inner

    def _on_pk(self, event):
        try:
            self._on_event(summarize_pk(event))
        except Exception:
            pass
        return True

    def _init_live_files(self, room_id):
        if self.live_name:
            return
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.live_name = str(self.store_dir / f"live.{self.live_id}.{room_id}")
        self.live_start = datetime.now()
        self.live_finished = False
        self.user_db = UserDB(self.live_name + ".user")

    def request_stop(self):
        self._stopped = True
        ws = self.ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        self.notify_stop()


class LiveSession:
    def __init__(self):
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._client: _WorkbenchLive | None = None
        self.status = "idle"
        self.message = ""
        self.room: dict = {}
        self.events: list[dict] = []
        self.seq = 0
        self.stats = {"chat": 0, "gift": 0, "enter": 0, "like": 0, "social": 0, "online": ""}

    def snapshot(self, since: int = 0) -> dict:
        with self._lock:
            if since <= 0:
                events = list(self.events[-200:])
            else:
                events = [item for item in self.events if item["seq"] > since]
            return {
                "status": self.status,
                "message": self.message,
                "room": dict(self.room),
                "stats": dict(self.stats),
                "seq": self.seq,
                "events": events,
            }

    def rows(self) -> list[dict]:
        with self._lock:
            return list(self.events)

    def start(self, live_id: str, auth) -> dict:
        web_rid = _live_web_rid(live_id)
        with self._lock:
            if self.status in {"connecting", "live"} and self._thread and self._thread.is_alive():
                raise RuntimeError("已有一场监听在进行，请先停止")
            self.status = "connecting"
            self.message = "正在进入直播间…"
            self.room = {"web_rid": web_rid}
            self.events = []
            self.seq = 0
            self.stats = {"chat": 0, "gift": 0, "enter": 0, "like": 0, "social": 0, "online": ""}
            client = _WorkbenchLive(web_rid, auth, self._push, STORE_DIR)
            self._client = client
            self._thread = threading.Thread(
                target=self._run, args=(client, auth, web_rid), daemon=True, name="live-monitor",
            )
            self._thread.start()
        return self.snapshot()

    def stop(self) -> dict:
        with self._lock:
            client = self._client
            if self.status in {"connecting", "live"}:
                self.message = "正在停止…"
        if client is not None:
            client.request_stop()
        thread = self._thread
        if thread is not None and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=3)
        with self._lock:
            if self.status in {"connecting", "live"}:
                self.status = "stopped"
                self.message = "已停止"
        return self.snapshot()

    def _push(self, event: dict):
        kind = event.get("kind") or "system"
        with self._lock:
            if kind == "heat":
                online = str(event.get("online") or "")
                if online:
                    self.stats["online"] = online
                return
            if kind in self.stats and kind != "online":
                self.stats[kind] = int(self.stats.get(kind) or 0) + 1
            if kind == "like" and event.get("total"):
                self.stats["like_total"] = event["total"]
            self.seq += 1
            row = {
                "seq": self.seq,
                "ts": time.time(),
                "kind": kind,
                "user": event.get("user") or "",
                "text": event.get("text") or "",
            }
            self.events.append(row)
            if len(self.events) > MAX_EVENTS:
                del self.events[:-MAX_EVENTS]
            if kind == "control":
                self.status = "stopped"
                self.message = row["text"] or "直播已结束"

    def _run(self, client: _WorkbenchLive, auth, web_rid: str):
        try:
            room_info, data = DouyinAPI.get_live_info(auth, web_rid)
            if client._stopped:
                with self._lock:
                    if self._client is client:
                        self.status = "stopped"
                        self.message = "已停止"
                return
            room_status = room_info.get("room_status")
            if str(room_status) != "2":
                with self._lock:
                    if self._client is client:
                        self.status = "error"
                        self.message = "未开播或直播已结束"
                return
            nickname = ""
            try:
                nickname = data["roomStore"]["roomInfo"]["room"]["owner"]["nickname"]
            except Exception:
                nickname = ""
            room = {
                "web_rid": web_rid,
                "room_id": str(room_info.get("room_id") or ""),
                "anchor_id": str(room_info.get("anchor_id") or ""),
                "sec_uid": str(room_info.get("sec_uid") or ""),
                "title": room_info.get("room_title") or "",
                "nickname": nickname,
                "room_status": room_status,
            }
            with self._lock:
                if self._client is not client:
                    return
                self.room = room
                self.status = "live"
                self.message = f"{nickname or '主播'} · {room['title'] or web_rid}"
            client._init_live_files(room["room_id"])
            if client._stopped:
                with self._lock:
                    if self._client is client:
                        self.status = "stopped"
                        self.message = "已停止"
                return
            self._push({
                "kind": "system",
                "text": f"已连接 {nickname or room['anchor_id']} · {room['title'] or '直播间'}",
            })
            client.start_ws(room_info, reconnect=0)
        except Exception as exc:
            with self._lock:
                if self._client is client and self.status != "stopped":
                    self.status = "error"
                    self.message = str(exc)
            traceback.print_exc()
        finally:
            try:
                client._finish_live_files()
            except Exception:
                pass
            with self._lock:
                if self._client is client and self.status == "live":
                    self.status = "stopped"
                    if not self.message or self.message.startswith("正在"):
                        self.message = "监听已结束"


def fetch_ranks(auth, room: dict) -> dict:
    web_rid = str(room.get("web_rid") or "")
    if not web_rid:
        raise RuntimeError("请先开始监听，或填写直播间号")
    pk_payload = {"state": "error", "message": "", "sides": []}
    contribution = {"state": "error", "message": "", "users": []}
    try:
        pk_payload = public_pk_rank(DouyinAPI.get_live_pk_rank(auth, web_rid, side="both"))
    except LivePKAPIError as exc:
        pk_payload = {"state": "api_error", "message": str(exc), "sides": []}
    except Exception as exc:
        pk_payload = {"state": "error", "message": str(exc), "sides": []}

    room_id = str(room.get("room_id") or "")
    anchor_id = str(room.get("anchor_id") or "")
    sec_uid = str(room.get("sec_uid") or "")
    if room_id and anchor_id and sec_uid:
        try:
            raw = DouyinAPI.get_live_contribution_rank(
                auth, room_id, anchor_id, sec_uid, web_rid=web_rid,
            )
            ok = raw.get("status_code") == 0
            contribution = {
                "state": "ok" if ok else "api_error",
                "status_code": raw.get("status_code"),
                "message": "贡献榜已更新" if ok else f"贡献榜失败 status_code={raw.get('status_code')}",
                "users": flatten_rank_users(raw),
            }
        except Exception as exc:
            contribution = {"state": "error", "message": str(exc), "users": []}
    else:
        contribution = {"state": "error", "message": "还没有房间资料，请先开始监听", "users": []}
    return {"pk": pk_payload, "contribution": contribution}
