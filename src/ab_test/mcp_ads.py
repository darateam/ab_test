from __future__ import annotations

import json
from typing import Any

import requests

from ab_test.meta import MetaApiError, MetaClient, normalize_account_id

DEFAULT_MCP_URL = "https://mcp.facebook.com/ads"


class McpError(MetaApiError):
    pass


def select_arguments(values: dict[str, Any], schema: dict[str, Any] | None) -> dict[str, Any]:
    cleaned = {key: value for key, value in values.items() if value is not None and value != ""}
    properties = (schema or {}).get("properties") or {}
    if not properties:
        return cleaned
    selected = {key: value for key, value in cleaned.items() if key in properties}
    missing = [name for name in schema.get("required") or [] if name not in selected]
    if missing:
        raise McpError("MCP 도구에 필요한 값이 없습니다: " + ", ".join(missing))
    return selected


def entity_id(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("id", "campaign_id", "adset_id", "ad_set_id", "ad_id", "creative_id", "study_id", "test_id"):
            value = payload.get(key)
            if value not in (None, "", {}, []):
                return str(value)
        for value in payload.values():
            found = entity_id(value)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = entity_id(item)
            if found:
                return found
    return ""


def named_ids(payload: Any, name: str) -> list[str]:
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            node_name = node.get("name")
            node_id = node.get("id")
            if node_name == name and node_id not in (None, ""):
                found.append(str(node_id))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return list(dict.fromkeys(found))


class McpClient:
    def __init__(
        self,
        access_token: str,
        url: str = DEFAULT_MCP_URL,
        session: requests.Session | None = None,
        auto_initialize: bool = True,
    ):
        if not access_token:
            raise McpError("META_ACCESS_TOKEN이 비어 있습니다.")
        self.url = url
        self.token = access_token
        self.session = session or requests.Session()
        self.auto_initialize = auto_initialize
        self.ready = not auto_initialize
        self.session_id = ""
        self._next_id = 1
        self._schemas: dict[str, dict[str, Any]] | None = None

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self._ensure_ready()
        selected = select_arguments(arguments, self.schemas().get(name))
        body = self._rpc("tools/call", {"name": name, "arguments": selected})
        if body.get("isError"):
            raise McpError(_content_text(body) or f"{name} 호출에 실패했습니다.")
        structured = body.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        text = _content_text(body)
        if not text:
            return body
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}

    def schemas(self) -> dict[str, dict[str, Any]]:
        if self._schemas is not None:
            return self._schemas
        self._ensure_ready()
        listed = self._rpc("tools/list", {})
        tools = listed.get("tools") if isinstance(listed, dict) else None
        self._schemas = {
            tool.get("name", ""): tool.get("inputSchema") or {}
            for tool in tools or []
            if tool.get("name")
        }
        return self._schemas

    def _ensure_ready(self) -> None:
        if self.ready:
            return
        try:
            self._rpc(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "ab-test", "version": "0.1.0"},
                },
            )
        except McpError as exc:
            text = str(exc).lower()
            if "not found" not in text and "already" not in text:
                raise
        self._notify("notifications/initialized")
        self.ready = True

    def _notify(self, method: str) -> None:
        self.session.request(
            "POST",
            self.url,
            data=json.dumps({"jsonrpc": "2.0", "method": method}),
            headers=self._headers(),
            timeout=60,
        )

    def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        request_id = self._next_id
        self._next_id += 1
        response = self.session.request(
            "POST",
            self.url,
            data=json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}),
            headers=self._headers(),
            timeout=60,
        )
        session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id")
        if session_id:
            self.session_id = session_id
        body = _decode_response(response)
        if isinstance(body, dict) and body.get("error"):
            error = body["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise McpError(message or "MCP 호출에 실패했습니다.")
        if response.status_code >= 400:
            raise McpError(getattr(response, "reason", None) or f"MCP HTTP {response.status_code}")
        if isinstance(body, dict) and "result" in body:
            return body["result"]
        return body

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers


class McpAds:
    """Meta 광고 MCP 서버로 캠페인, 광고, A/B 실험을 만듭니다."""

    def __init__(
        self,
        access_token: str,
        ad_account_id: str,
        api_version: str = "v25.0",
        url: str = DEFAULT_MCP_URL,
        session: requests.Session | None = None,
        auto_initialize: bool = True,
        media_client: MetaClient | None = None,
    ):
        if not ad_account_id:
            raise McpError("META_AD_ACCOUNT_ID가 비어 있습니다.")
        self.account_id = normalize_account_id(ad_account_id)
        self.mcp = McpClient(access_token, url=url, session=session, auto_initialize=auto_initialize)
        self.media = media_client or MetaClient(access_token, self.account_id, api_version, session=session)

    def create_campaign(self, payload: dict[str, Any]) -> str:
        return self._id("ads_create_campaign", {**payload, "account_id": self.account_id, "status": "PAUSED"})

    def create_adset(self, payload: dict[str, Any]) -> str:
        return self._id(
            "ads_create_ad_set",
            {**payload, "account_id": self.account_id, "ad_set_id": payload.get("id"), "status": "PAUSED"},
        )

    def create_creative(self, payload: dict[str, Any]) -> str:
        return self._id("ads_create_creative", {**_creative_arguments(payload), "account_id": self.account_id})

    def create_ad(self, payload: dict[str, Any]) -> str:
        creative = payload.get("creative") or {}
        creative_id = creative.get("creative_id", "")
        return self._id(
            "ads_create_ad",
            {
                **payload,
                "account_id": self.account_id,
                "ad_set_id": payload.get("adset_id", ""),
                "creative_id": creative_id,
                "status": "PAUSED",
            },
        )

    def upload_image(self, filename: str, data: bytes, mime: str) -> str:
        return self.media.upload_image(filename, data, mime)

    def upload_video(self, filename: str, data: bytes, mime: str) -> str:
        return self.media.upload_video(filename, data, mime)

    def set_status(self, object_id: str, status: str, entity_type: str = "") -> None:
        tool = "ads_activate_entity" if status == "ACTIVE" else "ads_update_entity"
        self.mcp.call_tool(
            tool,
            {
                "account_id": self.account_id,
                "id": object_id,
                "entity_id": object_id,
                "status": status,
                "entity_type": entity_type,
                "level": entity_type,
            },
        )

    def create_split_test(self, business_id: str, payload: dict[str, Any]) -> str:
        return self._id(
            "ads_experiment_abtest_create_test",
            {**payload, "account_id": self.account_id, "business_id": business_id},
        )

    def find_by_name(
        self,
        edge: str,
        name: str,
        extra_filters: list[dict[str, Any]] | None = None,
    ) -> str | None:
        level = {"campaigns": "campaign", "adsets": "adset", "ads": "ad"}.get(edge, edge)
        try:
            result = self.mcp.call_tool(
                "ads_get_ad_entities",
                {
                    "account_id": self.account_id,
                    "level": level,
                    "entity_type": level,
                    "name": name,
                    "filtering": extra_filters or [],
                    "limit": 10,
                },
            )
        except McpError:
            return None
        matches = named_ids(result, name)
        if not matches:
            return None
        if len(matches) > 1:
            raise McpError(f"이름이 '{name}'인 항목이 여러 개입니다. 시트에 ID를 입력하세요.")
        return matches[0]

    def _id(self, tool: str, arguments: dict[str, Any]) -> str:
        found = entity_id(self.mcp.call_tool(tool, arguments))
        if not found:
            raise McpError(f"{tool} 응답에 id가 없습니다.")
        return found


def _creative_arguments(payload: dict[str, Any]) -> dict[str, Any]:
    story = payload.get("object_story_spec") or {}
    link = story.get("link_data") or {}
    video = story.get("video_data") or {}
    source = link or video
    action = source.get("call_to_action") or {}
    action_value = action.get("value") or {}
    return {
        "name": payload.get("name", ""),
        "page_id": story.get("page_id", ""),
        "instagram_user_id": story.get("instagram_user_id", ""),
        "object_story_spec": story,
        "message": link.get("message") or video.get("message") or "",
        "headline": link.get("name") or video.get("title") or "",
        "description": link.get("description") or video.get("link_description") or "",
        "link": link.get("link") or action_value.get("link") or "",
        "image_hash": link.get("image_hash") or video.get("image_hash") or "",
        "video_id": video.get("video_id") or "",
        "call_to_action": action.get("type") or "",
    }


def _content_text(result: Any) -> str:
    if not isinstance(result, dict):
        return str(result or "")
    chunks = []
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("text"):
            chunks.append(str(item["text"]))
        elif isinstance(item, str):
            chunks.append(item)
    if chunks:
        return "\n".join(chunks)
    if result.get("text"):
        return str(result["text"])
    return ""


def _decode_response(response: Any) -> Any:
    content_type = ""
    headers = getattr(response, "headers", {}) or {}
    if hasattr(headers, "get"):
        content_type = headers.get("Content-Type") or headers.get("content-type") or ""
    text = getattr(response, "text", "") or ""
    if "text/event-stream" in content_type:
        for chunk in text.split("\n\n"):
            data = "\n".join(line[5:].strip() for line in chunk.splitlines() if line.startswith("data:"))
            if not data or data == "[DONE]":
                continue
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                continue
        raise McpError("MCP 이벤트 응답을 읽지 못했습니다.")
    try:
        return response.json()
    except ValueError:
        raise McpError((text or getattr(response, "reason", "") or "MCP 응답을 읽지 못했습니다")[:300])
