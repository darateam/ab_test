import json

import pytest

from ab_test.meta import MetaApiError, MetaClient, creative_body, normalize_account_id


class Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)
        self.reason = "error"

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def request(self, method, url, data=None, params=None, files=None, timeout=None):
        self.calls.append({"method": method, "url": url, "data": data, "params": params, "files": files})
        return self.responses.pop(0)


def test_account_id_and_token_stay_out_of_the_url():
    session = FakeSession([Response({"id": "99"})])
    client = MetaClient("secret-token", "act_55", session=session, sleeper=lambda _seconds: None)
    assert client.create_campaign({"name": "봄", "special_ad_categories": [], "status": "PAUSED"}) == "99"
    call = session.calls[0]
    assert call["url"] == "https://graph.facebook.com/v25.0/act_55/campaigns"
    assert "secret-token" not in call["url"]
    assert "access_token" not in (call["data"] or {})
    assert session.headers["Authorization"] == "Bearer secret-token"
    assert json.loads(call["data"]["special_ad_categories"]) == []


def test_retries_rate_limit_then_uses_user_message():
    session = FakeSession(
        [
            Response({"error": {"message": "limit", "code": 17}}, status=400),
            Response({"error": {"message": "technical", "error_user_msg": "예산이 너무 작습니다", "code": 100}}, status=400),
        ]
    )
    delays = []
    client = MetaClient("token", "10", session=session, sleeper=delays.append)
    with pytest.raises(MetaApiError, match="예산이 너무 작습니다"):
        client.create_adset({"name": "세트", "daily_budget": 1})
    assert delays == [1]
    assert normalize_account_id("10") == "act_10"
    assert "/act_10/adsets" in session.calls[1]["url"]


def test_video_upload_uses_resumable_session():
    session = FakeSession(
        [
            Response(
                {
                    "upload_session_id": "sess",
                    "video_id": "vid_1",
                    "start_offset": "0",
                    "end_offset": "4",
                }
            ),
            Response({"start_offset": "4", "end_offset": "4"}),
            Response({"success": True}),
        ]
    )
    client = MetaClient("token", "10", session=session, sleeper=lambda _seconds: None)
    assert client.upload_video("clip.mp4", b"abcd", "video/mp4") == "vid_1"
    assert session.calls[0]["url"].startswith("https://graph-video.facebook.com/")
    assert "upload_phase" in session.calls[0]["data"]
    assert session.calls[1]["files"]["video_file_chunk"][1] == b"abcd"


def test_image_hash_and_creative_shape():
    session = FakeSession([Response({"images": {"a.png": {"hash": "h1"}}})])
    client = MetaClient("token", "10", session=session, sleeper=lambda _seconds: None)
    assert client.upload_image("a.png", b"png", "image/png") == "h1"
    body = creative_body(
        name="광고",
        page_id="page",
        primary_text="문구",
        headline="제목",
        description="",
        link_url="https://example.com",
        cta="LEARN_MORE",
        image_hash="h1",
    )
    assert body["object_story_spec"]["link_data"]["image_hash"] == "h1"
    assert "description" not in body["object_story_spec"]["link_data"]
