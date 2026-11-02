"""确认队列：同步、批准、拒绝。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from webapp.agent_config import default_agent_config
from webapp.agent_plan import build_plan_from_agent
from webapp.agent_queue import apply_queue_to_plan, decide_queue_item, sync_queue_from_plan
from webapp import server as web_server


class AgentQueueUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "agent_queue.json"

    def _plan(self):
        agent = default_agent_config()
        agent["enabled"] = True
        agent["tools"]["comment"] = True
        return build_plan_from_agent(agent)

    def test_sync_and_approve(self):
        plan = self._plan()
        result = sync_queue_from_plan(self.path, plan)
        self.assertEqual(len(result["created"]), 1)
        item_id = result["created"][0]["id"]
        decided = decide_queue_item(self.path, item_id, approve=True)
        self.assertEqual(decided["status"], "approved")
        merged = apply_queue_to_plan(plan, result["queue"] if False else {
            "items": [decided],
        })
        # reload after decide
        from webapp.agent_queue import load_queue
        merged = apply_queue_to_plan(plan, load_queue(self.path))
        self.assertEqual(merged["steps"][0]["status"], "approved")

    def test_reject(self):
        plan = self._plan()
        created = sync_queue_from_plan(self.path, plan)["created"][0]
        decide_queue_item(self.path, created["id"], approve=False)
        from webapp.agent_queue import load_queue
        merged = apply_queue_to_plan(plan, load_queue(self.path))
        self.assertEqual(merged["steps"][0]["status"], "rejected")


class AgentQueueApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.agent_path = Path(self.tmp.name) / "agent_config.json"
        self.queue_path = Path(self.tmp.name) / "agent_queue.json"
        self.client = TestClient(web_server.app)

    def test_preview_syncs_queue_and_decide(self):
        payload = default_agent_config()
        payload["enabled"] = True
        payload["goal"]["category"] = "逆水寒手游"
        payload["tools"]["comment"] = True
        with patch.object(web_server, "AGENT_PATH", self.agent_path), \
             patch.object(web_server, "AGENT_EXAMPLE_PATH", Path("missing.json")), \
             patch.object(web_server, "AGENT_QUEUE_PATH", self.queue_path):
            preview = self.client.post("/api/agent/plan", json=payload)
            self.assertEqual(preview.status_code, 200, preview.text)
            pending = preview.json()["queue"]["pending"]
            self.assertEqual(len(pending), 1)
            item_id = pending[0]["id"]

            self.client.post("/api/agent", json=payload)
            decided = self.client.post(f"/api/agent/queue/{item_id}", json={"action": "approve"})
            self.assertEqual(decided.status_code, 200, decided.text)
            self.assertEqual(decided.json()["item"]["status"], "approved")
            self.assertEqual(decided.json()["plan"]["steps"][0]["status"], "approved")


if __name__ == "__main__":
    unittest.main()
