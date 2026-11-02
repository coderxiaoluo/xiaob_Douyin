"""粉丝/关注列表聚合：兼容 followers=null，并给出可读错误。"""
import unittest
from unittest.mock import patch

from dy_apis.douyin_api import DouyinAPI


class FollowerListTests(unittest.TestCase):
    def test_null_followers_raises_readable_error(self):
        with patch.object(DouyinAPI, "get_user_follower_list",
                          return_value={"status_code": 0, "followers": None, "has_more": 0}):
            with self.assertRaisesRegex(RuntimeError, "粉丝列表不可用"):
                DouyinAPI.get_some_user_follower_list(object(), "1", "sec", 10)

    def test_paginates_until_enough(self):
        pages = [
            {"status_code": 0, "followers": [{"uid": "a"}], "has_more": 1, "min_time": "100"},
            {"status_code": 0, "followers": [{"uid": "b"}, {"uid": "c"}], "has_more": 0},
        ]
        with patch.object(DouyinAPI, "get_user_follower_list", side_effect=pages):
            rows = DouyinAPI.get_some_user_follower_list(object(), "1", "sec", 2)
        self.assertEqual([row["uid"] for row in rows], ["a", "b"])

    def test_null_followings_raises_readable_error(self):
        with patch.object(DouyinAPI, "get_user_following_list",
                          return_value={"status_code": 8, "followings": None, "status_msg": "denied"}):
            with self.assertRaisesRegex(RuntimeError, "关注列表不可用"):
                DouyinAPI.get_some_user_following_list(object(), "1", "sec", 10)


if __name__ == "__main__":
    unittest.main()
