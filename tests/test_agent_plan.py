"""plan.v1 生成与 API 预览。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from webapp.agent_config import default_agent_config
from webapp.agent_plan import PLAN_SCHEMA, build_plan_from_agent
from webapp import server as web_server


class AgentPlanTests(unittest.TestCase):
    def test_build_plan_from_comment_strategy(self):
        agent = default_agent_config()
        agent["enabled"] = True
        agent["goal"] = {
            "category": "逆水寒手游",
            "daily_videos": 1,
            "funnel": "comment",
            "brief": "逆水寒手游pvp",
        }
        agent["tools"]["comment"] = True
        plan = build_plan_from_agent(agent)
        self.assertEqual(plan["schema"], PLAN_SCHEMA)
        self.assertFalse(plan["executable"])
        self.assertEqual(plan["enabled_tools"], ["comment"])
        self.assertEqual(len(plan["steps"]), 1)
        self.assertEqual(plan["steps"][0]["tool"], "comment")
        self.assertEqual(plan["steps"][0]["status"], "needs_confirm")
        self.assertIn("逆水寒手游", plan["summary"])

    def test_disabled_strategy_blocks_steps(self):
        agent = default_agent_config()
        agent["enabled"] = False
        agent["tools"]["comment"] = True
        plan = build_plan_from_agent(agent)
        self.assertEqual(plan["steps"][0]["status"], "blocked")
        self.assertTrue(any("未启用" in w for w in plan["warnings"]))

    def test_empty_tools_warning(self):
        plan = build_plan_from_agent(default_agent_config())
        self.assertEqual(plan["steps"], [])
        self.assertTrue(any("能力" in w for w in plan["warnings"]))


class AgentPlanApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "agent_config.json"
        self.client = TestClient(web_server.app)

    def test_plan_preview_and_get(self):
        payload = default_agent_config()
        payload["enabled"] = True
        payload["goal"]["category"] = "本地生活"
        payload["goal"]["brief"] = "今日测计划"
        payload["tools"]["comment"] = True
        with patch.object(web_server, "AGENT_PATH", self.path), \
             patch.object(web_server, "AGENT_EXAMPLE_PATH", Path("missing.json")):
            preview = self.client.post("/api/agent/plan", json=payload)
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(preview.json()["plan"]["schema"], PLAN_SCHEMA)
            self.assertTrue(preview.json().get("draft"))

            saved = self.client.post("/api/agent", json=payload)
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertIn("plan", saved.json())

            got = self.client.get("/api/agent/plan")
            self.assertEqual(got.status_code, 200)
            self.assertEqual(got.json()["plan"]["enabled_tools"], ["comment"])


if __name__ == "__main__":
    unittest.main()
