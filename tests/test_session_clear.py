"""清空会话只去掉登录材料，指纹和代理留在配置里。"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from webapp import server as web_server


class SessionClearTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env_path = Path(self.tmp.name) / ".env"
        self.env_path.write_text(
            "\n".join([
                'DY_COOKIES="sessionid=abc; ttwid=old"',
                'DY_TICKET="ticket"',
                'DY_FP_UA="Mozilla/5.0 Chrome/155.0.0.0"',
                'DY_FP_SCREEN_WIDTH="2560"',
                'DY_PROXY=""',
            ]) + "\n",
            encoding="utf-8",
        )
        self.client = TestClient(web_server.app)
        self._env_backup = {
            key: os.environ.get(key)
            for key in (
                "DY_COOKIES", "DY_TICKET", "DY_FP_UA", "DY_FP_SCREEN_WIDTH",
                "DY_FP_SCREEN_HEIGHT", "DY_FP_CPU_CORE_NUM", "DY_FP_DEVICE_MEMORY",
                "DY_FP_BROWSER_VERSION", "DY_FP_ENGINE_VERSION",
                "DY_FP_ACCEPT_LANGUAGE", "DY_PROXY",
            )
        }
        self._qr_generation = web_server._qr_generation
        self._qr = dict(web_server._qr)

    def tearDown(self):
        web_server._qr_generation = self._qr_generation
        web_server._qr.clear()
        web_server._qr.update(self._qr)
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_clear_drops_login_and_keeps_form_fingerprint(self):
        with patch.object(web_server, "ENV_PATH", self.env_path), \
             patch.object(web_server, "_reload_runtime_auth", return_value=(None, {})):
            res = self.client.post("/api/session/clear", json={
                "ua": "Mozilla/5.0 Chrome/156.0.0.0",
                "browser_version": "156.0.0.0",
                "engine_version": "156.0.0.0",
                "screen_width": "1536",
                "screen_height": "864",
                "cpu_core_num": "12",
                "device_memory": "16",
                "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
                "proxy": "http://127.0.0.1:7890",
            })
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertTrue(body["cleared"])
        self.assertFalse(body["has_sessionid"])
        self.assertEqual(body["fp"]["screen_width"], "1536")
        self.assertEqual(body["proxy"], "http://127.0.0.1:7890")
        text = self.env_path.read_text(encoding="utf-8")
        self.assertNotIn("sessionid=abc", text)
        self.assertIn("1536", text)
        self.assertIn("http://127.0.0.1:7890", text)
        self.assertEqual(body["message"], "已清空登录。指纹和代理还在，请重新扫码。")

    def test_stale_qr_cannot_mark_cleared_session_confirmed(self):
        web_server._qr_generation = 3
        web_server._qr.update(status="idle", message="会话已清空，请重新生成二维码")
        web_server._set_qr_for(2, status="confirmed", message="登录成功")
        self.assertEqual(web_server._qr["status"], "idle")
        web_server._set_qr_for(3, status="waiting", message="请用抖音 App 扫码")
        self.assertEqual(web_server._qr["status"], "waiting")


if __name__ == "__main__":
    unittest.main()
