from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from dy_apis.douyin_api import DouyinAPI


class _Auth:
    cookie = {"s_v_web_id": "fp", "UIFID": "uifid"}
    webid = "webid"
    msToken = "mstoken"


class SearchFilterTests(TestCase):
    def test_general_search_sends_selected_filter_values(self):
        response = SimpleNamespace(
            text="{}",
            status_code=200,
            headers={},
            json=lambda: {"data": []},
        )
        with patch("dy_apis.douyin_api.generate_a_bogus_pure", return_value="ab"), \
                patch("dy_apis.douyin_api.requests.get", return_value=response) as request:
            DouyinAPI.search_general_work(
                _Auth(), "猫", sort_type="2", publish_time="7",
                filter_duration="1-5", search_range="3", content_type="2",
            )

        query = request.call_args.kwargs["params"]
        self.assertEqual(query["search_source"], "tab_search")
        self.assertEqual(query["is_filter_search"], "1")
        self.assertEqual(query["filter_selected"], (
            '{"sort_type":"2","publish_time":"7",'
            '"filter_duration":"1-5","search_range":"3","content_type":"2"}'
        ))

    def test_general_search_default_zero_filters_are_not_active(self):
        response = SimpleNamespace(
            text="{}",
            status_code=200,
            headers={},
            json=lambda: {"data": []},
        )
        with patch("dy_apis.douyin_api.generate_a_bogus_pure", return_value="ab"), \
                patch("dy_apis.douyin_api.requests.get", return_value=response) as request:
            DouyinAPI.search_general_work(
                _Auth(), "猫", sort_type="0", publish_time="0",
                filter_duration="", search_range="0", content_type="0",
            )
        self.assertEqual(request.call_args.kwargs["params"]["is_filter_search"], "0")

    def test_search_some_general_work_missing_data_raises_readable_error(self):
        with patch.object(DouyinAPI, "search_general_work",
                          return_value={"status_code": 2483, "status_msg": "请先登录，再继续搜索吧"}):
            with self.assertRaisesRegex(RuntimeError, r"搜作品失败.*会话有效.*重贴 Cookie|搜作品失败.*重新复制 Cookie"):
                DouyinAPI.search_some_general_work(_Auth(), "猫", 10, "0", "0")

    def test_search_some_general_work_skips_non_aweme_rows(self):
        with patch.object(DouyinAPI, "search_general_work", return_value={
            "status_code": 0,
            "data": [{"type": 1}, {"aweme_info": {"aweme_id": "1"}}],
            "has_more": 0,
        }):
            rows = DouyinAPI.search_some_general_work(_Auth(), "猫", 10, "0", "0")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["aweme_info"]["aweme_id"], "1")
