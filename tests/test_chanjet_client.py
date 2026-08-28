# -*- coding: utf-8 -*-
"""畅捷通客户端单元测试（离线，不发真实网络请求）。"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from chanjet_client import ChanjetClient, ChanjetError, ENTITIES, normalize_rows  # noqa: E402


class FakeClient(ChanjetClient):
    """拦截网络请求，返回 T+ 真实响应结构的样例。"""

    def __init__(self):
        super().__init__("k", "s", "t")
        self.last_payload = None

    def post(self, path, payload, timeout=30):
        self.last_payload = {"path": path, **payload}
        return {
            "data": [
                {"SalesDelivery": {
                    "ID": 1, "Code": "SD-001", "VoucherDate": "2026-08-01",
                    "CustomerName": "海川制造", "CustomerCode": "C001",
                    "TotalAmount": 12000.0, "Status": "审核",
                }},
                {"SalesDelivery": {
                    "ID": 2, "Code": "SD-002", "VoucherDate": "2026-08-15",
                    "CustomerName": "星联科技", "CustomerCode": "C002",
                    "TotalAmount": 8000.0, "Status": "未审核",
                }},
            ]
        }


class ClientTests(unittest.TestCase):
    def test_missing_credentials_rejected(self):
        with self.assertRaises(ChanjetError):
            ChanjetClient("", "s", "t")

    def test_list_entity_builds_date_filter(self):
        client = FakeClient()
        client.list_entity("sales_delivery", date_from="2026-08-01", date_to="2026-08-31")
        pdic = client.last_payload["paramDic"]
        self.assertEqual(pdic["SalesDelivery.VoucherDate"],
                         {"from": "2026-08-01", "to": "2026-08-31"})
        self.assertEqual(client.last_payload["path"], "SalesDelivery/FindVoucherList")
        self.assertIn("SalesDelivery.CustomerName", client.last_payload["selectFields"])

    def test_unknown_entity_rejected(self):
        client = FakeClient()
        with self.assertRaises(ChanjetError):
            client.list_entity("nope")

    def test_normalize_rows_maps_contract(self):
        client = FakeClient()
        payload = client.list_entity("sales_delivery")
        rows = normalize_rows("sales_delivery", payload)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["order_no"], "SD-001")
        self.assertEqual(rows[0]["customer_name"], "海川制造")
        self.assertEqual(rows[0]["order_date"], "2026-08-01")
        self.assertIn("total_amount", rows[0])
        self.assertIn("status", rows[0])

    def test_normalize_rejects_unknown(self):
        with self.assertRaises(ChanjetError):
            normalize_rows("nope", {})


if __name__ == "__main__":
    unittest.main()
