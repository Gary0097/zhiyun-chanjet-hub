# -*- coding: utf-8 -*-
"""畅捷通开放平台 T+ OpenAPI 轻客户端（纯标准库，可独立测试）。

鉴权：请求头携带 appKey/appSecret/openToken（平台文档规定的三件套）。
业务端点均为 POST JSON；分页 pageIndex 从 0 开始。
文档源：https://open.chanjet.com/docs/file/apiFile/tcloud
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

API_ROOT = "https://openapi.chanjet.com/tplus/api/v2"

# 核心取数实体（单据列表查询 FindVoucherList）
ENTITIES: dict[str, dict[str, str]] = {
    "sales_delivery": {"org": "SalesDelivery", "label": "销售发货单"},
    "sales_order": {"org": "SaleOrder", "label": "销售订单"},
    "purchase_order": {"org": "PurchaseOrder", "label": "采购订单"},
    "purchase_receipt": {"org": "PurchaseReceipt", "label": "采购入库单"},
    "sale_out": {"org": "SaleOut", "label": "销售出库单"},
}

# 各实体常用查询字段（明细行需加前缀，见文档"单据列表查询辅助接口"）
ENTITY_FIELDS: dict[str, list[str]] = {
    "sales_delivery": ["SalesDelivery.ID", "SalesDelivery.VoucherDate", "SalesDelivery.Code",
                       "SalesDelivery.CustomerCode", "SalesDelivery.CustomerName",
                       "SalesDelivery.TotalAmount", "SalesDelivery.Status"],
    "sales_order": ["SaleOrder.ID", "SaleOrder.VoucherDate", "SaleOrder.Code",
                    "SaleOrder.CustomerCode", "SaleOrder.CustomerName",
                    "SaleOrder.TotalAmount", "SaleOrder.Status"],
    "purchase_order": ["PurchaseOrder.ID", "PurchaseOrder.VoucherDate", "PurchaseOrder.Code",
                       "PurchaseOrder.SupplierCode", "PurchaseOrder.SupplierName",
                       "PurchaseOrder.TotalAmount", "PurchaseOrder.Status"],
    "purchase_receipt": ["PurchaseReceipt.ID", "PurchaseReceipt.VoucherDate", "PurchaseReceipt.Code",
                         "PurchaseReceipt.SupplierCode", "PurchaseReceipt.SupplierName",
                         "PurchaseReceipt.TotalAmount", "PurchaseReceipt.Status"],
    "sale_out": ["SaleOut.ID", "SaleOut.VoucherDate", "SaleOut.Code",
                 "SaleOut.CustomerCode", "SaleOut.CustomerName",
                 "SaleOut.TotalAmount", "SaleOut.Status"],
}

# 归一化到统一数据中心 orders 契约的字段映射
NORMALIZE_KEYS = ["order_no", "customer_name", "order_date", "status", "total_amount"]


class ChanjetError(Exception):
    pass


class ChanjetClient:
    def __init__(self, app_key: str, app_secret: str, open_token: str, api_root: str = API_ROOT):
        if not (app_key and app_secret and open_token):
            raise ChanjetError("appKey / appSecret / openToken 均不能为空")
        self.app_key = app_key
        self.app_secret = app_secret
        self.open_token = open_token
        self.api_root = api_root.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "appKey": self.app_key,
            "appSecret": self.app_secret,
            "openToken": self.open_token,
            "Content-Type": "application/json",
        }

    def post(self, path: str, payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
        request = urllib.request.Request(
            self.api_root + "/" + path.lstrip("/"),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise ChanjetError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ChanjetError(f"连接失败：{exc.reason}") from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ChanjetError(f"响应非 JSON：{body[:200]}") from exc

    def find_voucher_list(self, org_code: str, select_fields: list[str],
                          param_dic: dict[str, Any] | None = None,
                          page_size: int = 20, page_index: int = 0) -> dict[str, Any]:
        return self.post(f"{org_code}/FindVoucherList", {
            "pageSize": max(1, min(page_size, 200)),
            "pageIndex": max(0, page_index),
            "selectFields": select_fields,
            "paramDic": param_dic or {},
        })

    def list_entity(self, entity_key: str, page_size: int = 20, page_index: int = 0,
                    date_from: str = "", date_to: str = "") -> dict[str, Any]:
        """按实体取单据列表；日期区间映射到单据日期字段的 from/to。"""
        if entity_key not in ENTITIES:
            raise ChanjetError(f"不支持的实体：{entity_key}（可选：{', '.join(ENTITIES)}）")
        meta = ENTITIES[entity_key]
        param_dic: dict[str, Any] = {}
        date_field = next((f for f in ENTITY_FIELDS[entity_key] if f.endswith("VoucherDate")), "")
        if (date_from or date_to) and date_field:
            cond: dict[str, str] = {}
            if date_from:
                cond["from"] = date_from
            if date_to:
                cond["to"] = date_to
            param_dic[date_field] = cond
        return self.find_voucher_list(meta["org"], ENTITY_FIELDS[entity_key], param_dic,
                                      page_size, page_index)


def normalize_rows(entity_key: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """把 T+ 返回结构归一化为统一数据中心 orders 契约行。"""
    if entity_key not in ENTITY_FIELDS:
        raise ChanjetError(f"不支持的实体：{entity_key}")
    rows_out: list[dict[str, Any]] = []
    for line in payload.get("data") or payload.get("Records") or []:
        if not isinstance(line, dict):
            continue
        flat: dict[str, Any] = {}

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if isinstance(value, (dict, list)):
                        walk(value)
                    else:
                        flat[key] = value
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(line)
        fields = ENTITY_FIELDS[entity_key]
        code_key = next((f.split(".")[-1] for f in fields if f.endswith("Code")), "Code")
        name_key = next((f.split(".")[-1] for f in fields if f.endswith("Name")), "Name")
        date_key = next((f.split(".")[-1] for f in fields if f.endswith("VoucherDate")), "VoucherDate")
        amount_key = next((f.split(".")[-1] for f in fields if f.endswith("TotalAmount")), "TotalAmount")
        status_key = next((f.split(".")[-1] for f in fields if f.endswith("Status")), "Status")
        rows_out.append({
            "order_no": str(flat.get(code_key) or "")[:80],
            "customer_name": str(flat.get(name_key) or "")[:120],
            "order_date": str(flat.get(date_key) or "")[:10],
            "status": str(flat.get(status_key) or "")[:40],
            "total_amount": flat.get(amount_key),
        })
    return rows_out
