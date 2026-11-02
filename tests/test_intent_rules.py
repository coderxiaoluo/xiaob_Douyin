"""评论意向规则打分。"""
import tempfile
import unittest
from pathlib import Path

from webapp.intent_rules import (
    attach_intent,
    bonus_words_from_agent,
    default_rules,
    load_intent_rules,
    save_intent_rules,
    score_intent_text,
)


class IntentRulesTests(unittest.TestCase):
    def test_positive_hit_marks_intent(self):
        scored = score_intent_text("多少钱一套，求带", default_rules())
        self.assertTrue(scored["is_intent"])
        self.assertGreaterEqual(scored["intent_score"], 1)
        self.assertIn("意向", scored["intent_labels"])

    def test_negative_blocks_intent(self):
        scored = score_intent_text("求带 互粉一下", default_rules())
        self.assertFalse(scored["is_intent"])
        self.assertIn("风险", scored["intent_labels"])

    def test_bonus_words_from_agent(self):
        words = bonus_words_from_agent({
            "goal": {"category": "逆水寒手游", "brief": "碎梦 pvp"},
        })
        self.assertTrue(any("逆水寒" in w or w == "碎梦" or w == "pvp" for w in words))

    def test_attach_and_persist(self):
        row = attach_intent({"text": "私聊一下怎么买"})
        self.assertTrue(row["is_intent"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "intent_rules.json"
            saved = save_intent_rules(path, {
                "enabled": True,
                "threshold": 1,
                "positive": ["专属词"],
                "negative": [],
            })
            self.assertEqual(saved["positive"], ["专属词"])
            loaded = load_intent_rules(path)
            self.assertEqual(loaded["positive"], ["专属词"])
            scored = score_intent_text("专属词来了", loaded)
            self.assertTrue(scored["is_intent"])


if __name__ == "__main__":
    unittest.main()
