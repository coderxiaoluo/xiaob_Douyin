import unittest
from types import SimpleNamespace

from utils.proxy import proxies_from_url, websocket_proxy_kwargs
from webapp.live_feed import flatten_rank_users, public_pk_rank, summarize_message, summarize_pk


class ProxyHelperTest(unittest.TestCase):
    def test_blank_proxy_is_direct(self):
        self.assertIsNone(proxies_from_url("  "))
        self.assertEqual(websocket_proxy_kwargs(None), {})

    def test_http_proxy_reaches_websocket_kwargs(self):
        proxies = proxies_from_url("127.0.0.1:7890")
        self.assertEqual(proxies["https"], "http://127.0.0.1:7890")
        self.assertEqual(websocket_proxy_kwargs(proxies), {
            "http_proxy_host": "127.0.0.1",
            "http_proxy_port": 7890,
            "proxy_type": "http",
        })


class LiveEventTest(unittest.TestCase):
    def test_chat_gift_and_combo_tick(self):
        chat = SimpleNamespace(content="你好", user=SimpleNamespace(nickname="甲"))
        self.assertEqual(summarize_message("ChatMessage", chat)["kind"], "chat")
        ticking = SimpleNamespace(
            user=SimpleNamespace(nickname="乙"),
            gift=SimpleNamespace(name="玫瑰"),
            combo_count=3,
            repeat_end=0,
        )
        self.assertIsNone(summarize_message("GiftMessage", ticking))
        ended = SimpleNamespace(
            user=SimpleNamespace(nickname="乙"),
            gift=SimpleNamespace(name="玫瑰"),
            combo_count=3,
            repeat_end=1,
        )
        gift = summarize_message("GiftMessage", ended)
        self.assertEqual(gift["text"], "玫瑰 ×3")

    def test_enter_and_heat(self):
        entered = SimpleNamespace(
            action=1,
            user=SimpleNamespace(nickname="丙"),
            common=SimpleNamespace(display_text=None),
        )
        self.assertEqual(summarize_message("MemberMessage", entered)["kind"], "enter")
        heat = summarize_message("RoomUserSeqMessage", SimpleNamespace(total_str="1.2万", total=12000))
        self.assertEqual(heat["online"], "1.2万")
        self.assertIsNone(summarize_message("LinkMicBattleMethod", SimpleNamespace()))

    def test_pk_and_rank_rows(self):
        text = summarize_pk({"type": "scores", "scores": [{"anchor_id": "1", "score": "20"}]})
        self.assertIn("PK 比分", text["text"])
        payload = {"status_code": 0, "data": {"users": [
            {"user": {"nickname": "贡献用户"}, "score": 0, "score_blur_text": ""},
        ]}}
        rows = flatten_rank_users(payload)
        self.assertEqual(rows[0]["nickname"], "贡献用户")
        public = public_pk_rank({
            "state": "not_in_pk",
            "context": {"battle_id": None, "anchors": []},
            "ranks": {},
        })
        self.assertEqual(public["message"], "当前没有进行中的 PK")


if __name__ == "__main__":
    unittest.main()
