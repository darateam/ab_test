from __future__ import annotations

import json
import time
from typing import Any, Callable

import requests

from ab_test.models import AdSetPlan, CampaignPlan

RETRYABLE_CODES = {1, 2, 4, 17, 32, 613, 80004}


class MetaApiError(RuntimeError):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def campaign_body(plan: CampaignPlan) -> dict[str, Any]:
    categories = [plan.special_ad_category] if plan.special_ad_category else []
    return {
        "name": plan.campaign_name,
        "objective": plan.objective,
        "status": "PAUSED",
        "special_ad_categories": categories,
        "buying_type": "AUCTION",
    }


def adset_body(adset: AdSetPlan, campaign_id: str, objective: str, start_time: str, end_time: str) -> dict[str, Any]:
    targeting: dict[str, Any] = {
        "geo_locations": {"countries": adset.countries},
        "age_min": adset.age_min,
        "age_max": adset.age_max,
    }
    if adset.publisher_platforms:
        targeting["publisher_platforms"] = adset.publisher_platforms
    body: dict[str, Any] = {
        "name": adset.name,
        "campaign_id": campaign_id,
        "daily_budget": adset.daily_budget,
        "billing_event": adset.billing_event,
        "optimization_goal": adset.optimization_goal,
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "targeting": targeting,
        "status": "PAUSED",
    }
    if start_time:
        body["start_time"] = start_time
    if end_time:
        body["end_time"] = end_time
    if objective == "OUTCOME_TRAFFIC":
        body["destination_type"] = "WEBSITE"
    promoted = promoted_object(objective, adset)
    if promoted:
        body["promoted_object"] = promoted
    return body


def promoted_object(objective: str, adset: AdSetPlan) -> dict[str, str]:
    if objective == "OUTCOME_SALES" and adset.pixel_id:
        return {
            "pixel_id": adset.pixel_id,
            "custom_event_type": adset.custom_event_type or "PURCHASE",
        }
    if adset.page_id:
        return {"page_id": adset.page_id}
    return {}


def creative_body(
    *,
    name: str,
    page_id: str,
    primary_text: str,
    headline: str,
    description: str,
    link_url: str,
    cta: str,
    instagram_user_id: str = "",
    image_hash: str = "",
    video_id: str = "",
    thumbnail_hash: str = "",
) -> dict[str, Any]:
    call_to_action = {"type": cta or "LEARN_MORE", "value": {"link": link_url}}
    if video_id:
        video_data: dict[str, Any] = {
            "video_id": video_id,
            "message": primary_text,
            "title": headline,
            "call_to_action": call_to_action,
        }
        if description:
            video_data["link_description"] = description
        if thumbnail_hash:
            video_data["image_hash"] = thumbnail_hash
        story: dict[str, Any] = {"page_id": page_id, "video_data": video_data}
    else:
        link_data: dict[str, Any] = {
            "message": primary_text,
            "link": link_url,
            "name": headline,
            "image_hash": image_hash,
            "call_to_action": call_to_action,
        }
        if description:
            link_data["description"] = description
        story = {"page_id": page_id, "link_data": link_data}
    if instagram_user_id:
        story["instagram_user_id"] = instagram_user_id
    return {"name": name, "object_story_spec": story}


def ad_body(name: str, adset_id: str, creative_id: str) -> dict[str, Any]:
    return {
        "name": name,
        "adset_id": adset_id,
        "creative": {"creative_id": creative_id},
        "status": "PAUSED",
    }


def split_test_body(
    name: str,
    cells: list[dict[str, Any]],
    start_time: int,
    end_time: int,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": "구글 드라이브 시트에서 자동 생성된 A/B 테스트",
        "start_time": start_time,
        "end_time": end_time,
        "type": "SPLIT_TEST",
        "cells": cells,
    }


def _form(payload: dict[str, Any]) -> dict[str, str]:
    form: dict[str, str] = {}
    for key, value in payload.items():
        if value is None or value == "":
            continue
        if isinstance(value, (dict, list)):
            form[key] = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, bool):
            form[key] = "true" if value else "false"
        else:
            form[key] = str(value)
    return form


class MetaClient:
    def __init__(
        self,
        access_token: str,
        ad_account_id: str,
        api_version: str = "v25.0",
        session: requests.Session | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        if not access_token:
            raise MetaApiError("META_ACCESS_TOKEN이 비어 있습니다.")
        if not ad_account_id:
            raise MetaApiError("META_AD_ACCOUNT_ID가 비어 있습니다.")
        self.account_id = normalize_account_id(ad_account_id)
        self.version = api_version
        self.session = session or requests.Session()
        self.session.headers["Authorization"] = f"Bearer {access_token}"
        self.sleeper = sleeper

    def create_campaign(self, payload: dict[str, Any]) -> str:
        return self._id(self._request("POST", f"{self.account_id}/campaigns", data=_form(payload)))

    def create_adset(self, payload: dict[str, Any]) -> str:
        return self._id(self._request("POST", f"{self.account_id}/adsets", data=_form(payload)))

    def create_creative(self, payload: dict[str, Any]) -> str:
        return self._id(self._request("POST", f"{self.account_id}/adcreatives", data=_form(payload)))

    def create_ad(self, payload: dict[str, Any]) -> str:
        return self._id(self._request("POST", f"{self.account_id}/ads", data=_form(payload)))

    def upload_image(self, filename: str, data: bytes, mime: str) -> str:
        body = self._request(
            "POST",
            f"{self.account_id}/adimages",
            files={"filename": (filename, data, mime)},
        )
        images = body.get("images") or {}
        if not images:
            raise MetaApiError("이미지 업로드 응답에 hash가 없습니다.")
        image = next(iter(images.values()))
        image_hash = image.get("hash")
        if not image_hash:
            raise MetaApiError("이미지 업로드 응답에 hash가 없습니다.")
        return str(image_hash)

    def upload_video(self, filename: str, data: bytes, mime: str) -> str:
        started = self._request(
            "POST",
            f"{self.account_id}/advideos",
            data=_form({"upload_phase": "start", "file_size": len(data)}),
            host="https://graph-video.facebook.com",
            timeout=300,
        )
        session_id = started.get("upload_session_id")
        video_id = started.get("video_id") or started.get("id")
        if not session_id or not video_id:
            raise MetaApiError("동영상 업로드 시작 응답에 세션 정보가 없습니다.")
        start_offset = int(started.get("start_offset") or 0)
        end_offset = int(started.get("end_offset") or 0)
        while start_offset < end_offset:
            chunk = data[start_offset:end_offset]
            transferred = self._request(
                "POST",
                f"{self.account_id}/advideos",
                data=_form(
                    {
                        "upload_phase": "transfer",
                        "upload_session_id": session_id,
                        "start_offset": start_offset,
                    }
                ),
                files={"video_file_chunk": (filename, chunk, mime or "video/mp4")},
                host="https://graph-video.facebook.com",
                timeout=300,
            )
            next_start = int(transferred.get("start_offset") or 0)
            next_end = int(transferred.get("end_offset") or 0)
            if next_start <= start_offset and next_end == end_offset:
                raise MetaApiError("동영상 업로드가 진행되지 않습니다.")
            start_offset, end_offset = next_start, next_end
        self._request(
            "POST",
            f"{self.account_id}/advideos",
            data=_form({"upload_phase": "finish", "upload_session_id": session_id}),
            host="https://graph-video.facebook.com",
            timeout=300,
        )
        return str(video_id)

    def set_status(self, object_id: str, status: str, entity_type: str = "") -> None:
        del entity_type
        self._request("POST", object_id, data={"status": status})

    def create_split_test(self, business_id: str, payload: dict[str, Any]) -> str:
        if not business_id:
            raise MetaApiError("META_BUSINESS_ID가 없어 A/B 실험을 만들 수 없습니다.")
        return self._id(self._request("POST", f"{business_id}/ad_studies", data=_form(payload)))

    def find_by_name(
        self,
        edge: str,
        name: str,
        extra_filters: list[dict[str, Any]] | None = None,
    ) -> str | None:
        filtering: list[dict[str, Any]] = [{"field": "name", "operator": "EQUAL", "value": name}]
        if extra_filters:
            filtering.extend(extra_filters)
        body = self._request(
            "GET",
            f"{self.account_id}/{edge}",
            params={"fields": "id,name", "filtering": json.dumps(filtering, ensure_ascii=False), "limit": "2"},
        )
        matches = body.get("data") or []
        if not matches:
            return None
        if len(matches) > 1:
            raise MetaApiError(f"이름이 '{name}'인 항목이 여러 개입니다. 시트에 ID를 입력하세요.")
        return str(matches[0]["id"])

    def _id(self, body: dict[str, Any]) -> str:
        if "id" not in body:
            raise MetaApiError("Meta 응답에 id가 없습니다.")
        return str(body["id"])

    def _request(
        self,
        method: str,
        path: str,
        data: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        files: dict | None = None,
        host: str = "https://graph.facebook.com",
        timeout: int = 60,
    ) -> dict[str, Any]:
        url = f"{host.rstrip('/')}/{self.version}/{path.lstrip('/')}"
        last_error: MetaApiError | None = None
        for attempt in range(3):
            response = self.session.request(method, url, data=data, params=params, files=files, timeout=timeout)
            try:
                body = response.json()
            except ValueError:
                body = {"error": {"message": (response.text or response.reason or "응답을 읽지 못했습니다")[:300]}}
            if response.status_code < 400 and "error" not in body:
                return body
            error = body.get("error") or {}
            code = error.get("code")
            message = error.get("error_user_msg") or error.get("message") or response.reason or "Meta API 오류"
            last_error = MetaApiError(str(message), code if isinstance(code, int) else None)
            if attempt < 2 and (response.status_code >= 500 or code in RETRYABLE_CODES):
                self.sleeper(2**attempt)
                continue
            raise last_error
        assert last_error is not None
        raise last_error


def normalize_account_id(raw: str) -> str:
    text = raw.strip()
    if text.startswith("act_"):
        return text
    return f"act_{text}"
