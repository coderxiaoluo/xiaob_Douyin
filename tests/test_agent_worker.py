"""只读 Worker：搜作品/拉评论候选，不写抖音。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from webapp.agent_config import default_agent_config
from webapp.agent_plan import build_plan_from_agent
from webapp.agent_queue import decide_queue_item, load_queue, sync_queue_from_plan
from webapp.agent_worker import (
    apply_candidate_filters,
    run_readonly_prep,
    run_write_drafts,
    run_write_execute,
    update_candidate_selection,
)
from webapp import server as web_server


class AgentWorkerUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue_path = Path(self.tmp.name) / "agent_queue.json"
        self.agent = default_agent_config()
        self.agent["enabled"] = True
        self.agent["goal"]["category"] = "逆水寒手游"
        self.agent["goal"]["brief"] = "pvp"
        self.agent["tools"]["comment"] = True
        plan = build_plan_from_agent(self.agent)
        created = sync_queue_from_plan(self.queue_path, plan)["created"][0]
        decide_queue_item(self.queue_path, created["id"], approve=True)
        self.item_id = created["id"]

    def test_readonly_prep_attaches_candidates(self):
        fake_works = [{"aweme_info": {"aweme_id": "1", "desc": "测试作品"}}]
        fake_info = {
            "work_id": "1", "title": "测试作品", "nickname": "作者",
            "video_cover": "", "work_url": "https://www.douyin.com/video/1",
            "digg_count": 1, "comment_count": 2, "create_time": 0,
        }
        fake_comments = {
            "comments": [{"cid": "c1", "text": "热评一条", "user": {"nickname": "粉"}, "digg_count": 9}],
            "cursor": "0", "has_more": 0,
        }
        with patch("dy_apis.douyin_api.DouyinAPI.search_some_general_work", return_value=fake_works), \
             patch("utils.data_util.handle_work_info", return_value=fake_info), \
             patch("dy_apis.douyin_api.DouyinAPI.get_work_out_comment", return_value=fake_comments):
            result = run_readonly_prep(
                queue_path=self.queue_path,
                agent=self.agent,
                auth=object(),
            )
        self.assertTrue(result["ok"])
        item = load_queue(self.queue_path)["items"][0]
        self.assertEqual(item["worker_status"], "prepared")
        self.assertEqual(item["worker_result"]["works"][0]["work_id"], "1")
        self.assertEqual(item["worker_result"]["comments"][0]["text"], "热评一条")

    def test_comment_filter_by_digg_and_keyword(self):
        works = [
            {"work_id": "1", "title": "A", "digg_count": 10, "selected": True},
            {"work_id": "2", "title": "B", "digg_count": 1, "selected": True},
        ]
        comments = [
            {"cid": "c1", "text": "碎梦求带", "digg_count": 20, "work_id": "1", "selected": True},
            {"cid": "c2", "text": "广告私聊", "digg_count": 50, "work_id": "1", "selected": True},
            {"cid": "c3", "text": "碎梦日常", "digg_count": 2, "work_id": "1", "selected": True},
        ]
        fw, fc = apply_candidate_filters(
            works, comments,
            work_min_digg=5,
            comment_min_digg=5,
            comment_keyword="碎梦",
            comment_exclude="广告",
            max_comments_per_work=5,
        )
        self.assertTrue(fw[0]["selected"] and not fw[0]["filtered_out"])
        self.assertTrue(fw[1]["filtered_out"] and not fw[1]["selected"])
        picked = [c for c in fc if c["selected"] and not c["filtered_out"]]
        self.assertEqual([c["cid"] for c in picked], ["c1"])

    def test_intent_only_filter(self):
        comments = [
            {"cid": "a", "text": "求带", "digg_count": 9, "work_id": "1", "is_intent": True, "selected": True},
            {"cid": "b", "text": "哈哈哈", "digg_count": 9, "work_id": "1", "is_intent": False, "selected": True},
        ]
        _, fc = apply_candidate_filters(
            [], comments, intent_only=True, max_comments_per_work=5,
        )
        picked = [c["cid"] for c in fc if c["selected"] and not c["filtered_out"]]
        self.assertEqual(picked, ["a"])

    def test_write_draft_and_dry_run_execute(self):
        item = load_queue(self.queue_path)["items"][0]
        from webapp.agent_queue import update_queue_item
        update_queue_item(
            self.queue_path,
            item["id"],
            worker_status="prepared",
            worker_result={
                "mode": "readonly_prep",
                "works": [{"work_id": "11", "title": "碎梦技巧", "selected": True}],
                "comments": [{
                    "cid": "c9", "text": "问闪现", "nickname": "粉",
                    "work_id": "11", "selected": True, "digg_count": 3,
                }],
            },
        )
        drafted = run_write_drafts(queue_path=self.queue_path, agent=self.agent)
        self.assertTrue(drafted["ok"])
        item = load_queue(self.queue_path)["items"][0]
        self.assertEqual(item["write_status"], "drafted")
        self.assertTrue(item["write_draft"]["drafts"])

        executed = run_write_execute(
            queue_path=self.queue_path,
            agent=self.agent,
            auth=object(),
            dry_run=True,
        )
        self.assertTrue(executed["ok"])
        item = load_queue(self.queue_path)["items"][0]
        self.assertEqual(item["write_status"], "done")
        self.assertTrue(item["write_result"]["results"][0]["dry_run"])


class AgentWorkerApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.agent_path = Path(self.tmp.name) / "agent_config.json"
        self.queue_path = Path(self.tmp.name) / "agent_queue.json"
        self.client = TestClient(web_server.app)

    def test_worker_run_endpoint(self):
        payload = default_agent_config()
        payload["enabled"] = True
        payload["goal"]["category"] = "本地生活"
        payload["tools"]["comment"] = True
        fake_auth = type("A", (), {"cookie": {"sessionid": "x"}})()
        with patch.object(web_server, "AGENT_PATH", self.agent_path), \
             patch.object(web_server, "AGENT_EXAMPLE_PATH", Path("missing.json")), \
             patch.object(web_server, "AGENT_QUEUE_PATH", self.queue_path), \
             patch.object(web_server, "_ensure_runtime", return_value=(fake_auth, {})), \
             patch("webapp.agent_worker.run_readonly_prep", return_value={
                 "ok": True, "ran": [], "message": "ok",
             }) as runner:
            self.client.post("/api/agent", json=payload)
            preview = self.client.post("/api/agent/plan", json=payload)
            item_id = preview.json()["queue"]["pending"][0]["id"]
            self.client.post(f"/api/agent/queue/{item_id}", json={"action": "approve"})
            ran = self.client.post("/api/agent/worker/run", json={})
            self.assertEqual(ran.status_code, 200, ran.text)
            self.assertTrue(ran.json()["ok"])
            runner.assert_called_once()

    def test_worker_write_endpoint_draft(self):
        payload = default_agent_config()
        payload["enabled"] = True
        payload["goal"]["category"] = "本地生活"
        payload["tools"]["comment"] = True
        with patch.object(web_server, "AGENT_PATH", self.agent_path), \
             patch.object(web_server, "AGENT_EXAMPLE_PATH", Path("missing.json")), \
             patch.object(web_server, "AGENT_QUEUE_PATH", self.queue_path), \
             patch("webapp.agent_worker.run_write_drafts", return_value={
                 "ok": True, "ran": [], "message": "drafted",
             }) as drafter:
            self.client.post("/api/agent", json=payload)
            preview = self.client.post("/api/agent/plan", json=payload)
            item_id = preview.json()["queue"]["pending"][0]["id"]
            self.client.post(f"/api/agent/queue/{item_id}", json={"action": "approve"})
            res = self.client.post("/api/agent/worker/write", json={"action": "draft"})
            self.assertEqual(res.status_code, 200, res.text)
            self.assertTrue(res.json()["ok"])
            drafter.assert_called_once()


if __name__ == "__main__":
    unittest.main()
