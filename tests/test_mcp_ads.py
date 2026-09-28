import json

import pytest

from ab_test.mcp_ads import McpAds, McpClient, McpError, select_arguments


class Response:
    def __init__(self, payload, content_type="application/json", headers=None):
        if isinstance(payload, str):
            self.text = payload
            self._payload = None
        else:
            self.text = json.dumps(payload)
            self._payload = payload
        self.status_code = 200
        self.reason = "OK"
        self.headers = {"Content-Type": content_type, **(headers or {})}

    def json(self):
        if self._payload is None:
            return json.loads(self.text)
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def request(self, method, url, data=None, params=None, files=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "data": data, "headers": headers})
        return self.responses.pop(0)


SCHEMA = {
    "ads_create_campaign": {
        "type": "object",
        "properties": {
            "account_id": {},
            "name": {},
            "objective": {},
            "status": {},
            "special_ad_categories": {},
        },
        "required": ["account_id", "name", "objective"],
    },
    "ads_activate_entity": {
        "type": "object",
        "properties": {"account_id": {}, "entity_id": {}, "entity_type": {}},
        "required": ["entity_id"],
    },
    "ads_get_ad_entities": {
        "type": "object",
        "properties": {"account_id": {}, "level": {}, "name": {}},
    },
}


def test_select_arguments_keeps_only_schema_fields():
    selected = select_arguments(
        {
            "account_id": "act_1",
            "name": "여름",
            "objective": "OUTCOME_TRAFFIC",
            "buying_type": "AUCTION",
            "special_ad_categories": [],
        },
        SCHEMA["ads_create_campaign"],
    )
    assert selected["special_ad_categories"] == []
    assert "buying_type" not in selected


def test_missing_required_argument_is_reported():
    with pytest.raises(McpError, match="name"):
        select_arguments({"objective": "OUTCOME_TRAFFIC"}, SCHEMA["ads_create_campaign"])


def test_campaign_call_stays_paused_and_reuses_session():
    session = FakeSession(
        [
            Response({"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {"id": "camp_1"}}}, headers={"Mcp-Session-Id": "sess"}),
        ]
    )
    ads = McpAds("secret-token", "act_55", session=session, auto_initialize=False)
    ads.mcp._schemas = SCHEMA
    assert ads.create_campaign({"name": "여름", "objective": "OUTCOME_TRAFFIC", "buying_type": "AUCTION"}) == "camp_1"
    sent = json.loads(session.calls[0]["data"])
    assert sent["method"] == "tools/call"
    assert sent["params"]["name"] == "ads_create_campaign"
    assert sent["params"]["arguments"]["status"] == "PAUSED"
    assert sent["params"]["arguments"]["account_id"] == "act_55"
    assert "buying_type" not in sent["params"]["arguments"]
    assert "secret-token" not in session.calls[0]["url"]
    assert session.calls[0]["headers"]["Authorization"] == "Bearer secret-token"

    session.responses.append(Response({"jsonrpc": "2.0", "id": 2, "result": {"structuredContent": {"ok": True}}}))
    ads.set_status("camp_1", "ACTIVE", entity_type="campaign")
    second = json.loads(session.calls[1]["data"])
    assert second["params"]["name"] == "ads_activate_entity"
    assert session.calls[1]["headers"]["Mcp-Session-Id"] == "sess"


def test_find_by_name_and_event_stream():
    session = FakeSession(
        [
            Response(
                'data: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"{\\"data\\":[{\\"id\\":\\"9\\",\\"name\\":\\"여름\\"}]}"}]}}\n\n',
                content_type="text/event-stream",
            )
        ]
    )
    client = McpClient("token", session=session, auto_initialize=False)
    client._schemas = SCHEMA
    found = client.call_tool("ads_get_ad_entities", {"account_id": "act_1", "level": "campaign", "name": "여름"})
    assert found["data"][0]["id"] == "9"

    ads = McpAds("token", "act_1", session=session, auto_initialize=False)
    ads.mcp._schemas = SCHEMA
    session.responses.append(
        Response({"jsonrpc": "2.0", "id": 2, "result": {"structuredContent": {"data": [{"id": "9", "name": "여름"}]}}})
    )
    assert ads.find_by_name("campaigns", "여름") == "9"
