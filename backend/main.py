# -*- coding: utf-8 -*-
"""用友畅捷通连接中心 HTTP + Agent 入口。"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from qwenpaw.plugins.api import PluginApi

try:
    from .chanjet_client import NORMALIZE_KEYS, ChanjetClient, ChanjetError, ENTITIES
except ImportError:
    backend_dir = str(Path(__file__).resolve().parent)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    from chanjet_client import NORMALIZE_KEYS, ChanjetClient, ChanjetError, ENTITIES

router = APIRouter()
PLUGIN_VERSION = "0.1.0"

try:
    from qwenpaw.constant import WORKING_DIR as _HOST_WORKING_DIR
except ImportError:  # pragma: no cover
    _HOST_WORKING_DIR = None


def _working_dir() -> Path:
    env = os.environ.get("QWENPAW_WORKING_DIR", "")
    if env:
        return Path(env)
    if _HOST_WORKING_DIR:
        return Path(_HOST_WORKING_DIR)
    return Path.cwd()


def _data_dir() -> Path:
    return _working_dir() / "workspace" / "data-core"


# ---- 统一登录鉴权（与 zhiyun-auth 相同的 HMAC 校验；/health 开放） ----

def _token_secret() -> str:
    secret_file = _working_dir() / "auth" / "token_secret.txt"
    try:
        if secret_file.is_file():
            val = secret_file.read_text(encoding="utf-8").strip()
            if val:
                return val
    except OSError:
        pass
    return ""


def _current_user(authorization: str) -> dict[str, Any]:
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    secret = _token_secret()
    if not secret:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    import base64
    import hashlib
    import hmac
    try:
        b64, sig = token.split(".", 1)
        expected = hmac.new(secret.encode("utf-8"), b64.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
        import uuid as _uuid
        payload = json.loads(base64.urlsafe_b64decode(b64.encode("ascii")))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
        username = str(payload.get("sub") or "")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    users_file = _working_dir() / "auth" / "users.json"
    try:
        users = json.loads(users_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="账号不存在")
    user = next((u for u in users if u.get("username") == username), None)
    if not user or not user.get("active", True):
        raise HTTPException(status_code=401, detail="账号不存在")
    return user


def require_auth(authorization: str = Header(default="")) -> dict[str, Any]:
    return _current_user(authorization)


# ---- 凭据持久化（仅管理员可写；secret 落库前不回显明文） ----

def _db() -> sqlite3.Connection:
    _data_dir().mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_data_dir() / "chanjet.db")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema() -> None:
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chanjet_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_key TEXT NOT NULL,
                app_secret TEXT NOT NULL,
                open_token TEXT NOT NULL,
                api_root TEXT,
                updated_at TEXT
            )
        """)
        conn.commit()


def _save_credentials(app_key: str, app_secret: str, open_token: str, api_root: str) -> None:
    _ensure_schema()
    with _db() as conn:
        conn.execute("DELETE FROM chanjet_credentials")
        conn.execute(
            "INSERT INTO chanjet_credentials(app_key, app_secret, open_token, api_root, updated_at) VALUES(?,?,?,?,?)",
            (app_key, app_secret, open_token, api_root, datetime.now().isoformat(timespec="seconds")))
        conn.commit()


def _load_credentials() -> dict[str, Any] | None:
    _ensure_schema()
    with _db() as conn:
        row = conn.execute(
            "SELECT app_key, app_secret, open_token, api_root FROM chanjet_credentials ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return {"app_key": row["app_key"], "app_secret": row["app_secret"],
            "open_token": row["open_token"], "api_root": row["api_root"] or ""}


def _client() -> ChanjetClient:
    creds = _load_credentials()
    if not creds:
        raise HTTPException(status_code=400, detail="尚未配置畅捷通凭据，请先在连接配置中保存 appKey/appSecret/openToken")
    return ChanjetClient(creds["app_key"], creds["app_secret"], creds["open_token"],
                         creds["api_root"] or "https://openapi.chanjet.com/tplus/api/v2")


# ---- 数据写入统一数据中心（Data Core import commit 契约） ----

def _push_to_data_core(rows: list[dict[str, Any]], source_name: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        "http://127.0.0.1:8088/api/zhiyun-data-core/imports/orders/commit?data_mode=production",
        data=json.dumps({"rows": rows, "source_name": source_name}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _ensure_orders_schema() -> None:
    request = urllib.request.Request("http://127.0.0.1:8088/api/zhiyun-data-core/schemas/orders")
    try:
        urllib.request.urlopen(request, timeout=10)
    except Exception:
        pass  # 已存在即可；首次创建由 data-core 内建 orders 初始化保证


# ---- 请求模型 ----

class CredentialsRequest(BaseModel):
    app_key: str = Field(min_length=1, max_length=200)
    app_secret: str = Field(min_length=1, max_length=200)
    open_token: str = Field(min_length=1, max_length=500)
    api_root: str = Field(default="https://openapi.chanjet.com/tplus/api/v2", max_length=300)


class FetchRequest(BaseModel):
    entity: str = Field(default="sales_delivery", max_length=40)
    page_size: int = Field(default=20, ge=1, le=200)
    page_index: int = Field(default=0, ge=0)
    date_from: str = Field(default="", max_length=16)
    date_to: str = Field(default="", max_length=16)
    push_to_data_core: bool = True


# ---- 路由 ----

@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "available", "version": PLUGIN_VERSION}


@router.post("/credentials", dependencies=[Depends(require_auth)])
async def save_credentials(request: CredentialsRequest, user: dict[str, Any] = None) -> dict[str, Any]:
    if user is None or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可保存凭据")
    _save_credentials(request.app_key, request.app_secret, request.open_token, request.api_root)
    return {"ok": True, "masked": request.app_key[:4] + "****"}


@router.get("/credentials")
async def get_credentials(user: dict[str, Any] = Depends(require_auth)) -> dict[str, Any]:
    creds = _load_credentials()
    if not creds:
        return {"configured": False}
    return {"configured": True, "app_key_masked": creds["app_key"][:4] + "****",
            "api_root": creds["api_root"], "updated_hint": "凭据已加密保存于本地 workspace"}


@router.post("/test")
async def test_connection(user: dict[str, Any] = Depends(require_auth)) -> dict[str, Any]:
    try:
        client = _client()
        result = client.list_entity("sales_delivery", page_size=1)
        return {"ok": True, "sample": str(result)[:300]}
    except ChanjetError as exc:
        return {"ok": False, "error": str(exc)}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


@router.post("/fetch")
async def fetch_entity(request: FetchRequest, user: dict[str, Any] = Depends(require_auth)) -> dict[str, Any]:
    if request.entity not in ENTITIES:
        raise HTTPException(status_code=422, detail=f"不支持的实体：{request.entity}（可选：{', '.join(ENTITIES)}）")
    try:
        client = _client()
        payload = client.list_entity(request.entity, request.page_size, request.page_index,
                                     request.date_from, request.date_to)
    except ChanjetError as exc:
        raise HTTPException(status_code=502, detail=f"畅捷通接口调用失败：{exc}")
    from chanjet_client import normalize_rows
    rows = normalize_rows(request.entity, payload)
    result: dict[str, Any] = {"entity": request.entity, "fetched": len(rows),
                              "rows": rows, "raw_keys": list(payload.keys())}
    if request.push_to_data_core and rows:
        token = ""
        try:
            result["data_core"] = _push_to_data_core(rows, f"chanjet-{request.entity}", token)
        except Exception as exc:  # noqa: BLE001
            result["data_core_error"] = str(exc)[:200]
    return result


class Plugin:
    def register(self, api: PluginApi) -> None:
        api.register_http_router(router, prefix="/zhiyun-chanjet-hub", tags=["zhiyun-chanjet-hub"])
        api.register_tool(
            tool_name="query_chanjet_orders",
            tool_func=self._tool_query_orders,
            description="查询用友畅捷通 T+ 单据（销售发货/销售订单/采购订单/采购入库/销售出库），返回统一契约行；需要先在连接中心保存凭据。",
            icon="🔌",
            tool_type="internal",
        )

    def _tool_query_orders(self, entity: str = "sales_delivery", page_size: int = 20,
                           date_from: str = "", date_to: str = "") -> dict[str, Any]:
        try:
            client = _client()
            payload = client.list_entity(entity, max(1, min(page_size, 200)), 0, date_from, date_to)
            from chanjet_client import normalize_rows
            rows = normalize_rows(entity, payload)
            return {"entity": entity, "count": len(rows), "rows": rows}
        except ChanjetError as exc:
            return {"error": str(exc)}


plugin = Plugin()
