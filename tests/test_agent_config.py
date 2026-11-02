"""引流 Agent 配置校验与 Web API。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from webapp.agent_config import (
    DEFAULT_AGENT, default_agent_config, normalize_agent_config, validate_agent_config,
)
from webapp import server as web_server


class AgentConfigTests(unittest.TestCase):
    def test_normalize_fills_missing_sections(self):
        data = normalize_agent_config({"enabled": True, "goal": {"category": "本地生活"}})
        self.assertTrue(data["enabled"])
        self.assertEqual(data["goal"]["category"], "本地生活")
        self.assertEqual(data["goal"]["funnel"], DEFAULT_AGENT["goal"]["funnel"])
        self.assertEqual(data["tools"], DEFAULT_AGENT["tools"])

    def test_dm_requires_manual_confirm(self):
        payload = default_agent_config()
        payload["tools"]["dm_reply"] = True
        payload["safety"]["require_manual_confirm"] = False
        with self.assertRaisesRegex(ValueError, "人工确认"):
            validate_agent_config(payload)

    def test_daily_videos_cannot_exceed_publish_quota_when_enabled(self):
        payload = default_agent_config()
        payload["enabled"] = True
        payload["goal"]["daily_videos"] = 5
        payload["quotas"]["max_publish_per_day"] = 3
        with self.assertRaisesRegex(ValueError, "日发布上限"):
            validate_agent_config(payload)


class AgentApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "agent_config.json"
        self.client = TestClient(web_server.app)

    def test_get_default_and_save_round_trip(self):
        with patch.object(web_server, "AGENT_PATH", self.path), \
             patch.object(web_server, "AGENT_EXAMPLE_PATH", Path("missing.json")):
            got = self.client.get("/api/agent")
            self.assertEqual(got.status_code, 200)
            self.assertFalse(got.json()["agent"]["enabled"])

            payload = default_agent_config()
            payload["enabled"] = True
            payload["goal"] = {
                "category": "职场效率", "daily_videos": 2, "funnel": "comment",
                "brief": "日更两条",
            }
            payload["tools"]["comment"] = True
            saved = self.client.post("/api/agent", json=payload)
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(saved.json()["agent"]["goal"]["category"], "职场效率")
            disk = json.loads(self.path.read_text(encoding="utf-8"))
            self.assertTrue(disk["tools"]["comment"])

            denied = self.client.post("/api/agent", json={
                **payload,
                "tools": {**payload["tools"], "dm_reply": True},
                "safety": {**payload["safety"], "require_manual_confirm": False},
            })
            self.assertEqual(denied.status_code, 400)


if __name__ == "__main__":
    unittest.main()
