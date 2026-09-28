from __future__ import annotations

import csv
import re
from pathlib import Path

from ab_test.models import RESULT_FIELDS, STATUS_ERROR, AdRow, Issue

HEADER_ALIASES = {
    "test_name": "test_name",
    "테스트명": "test_name",
    "테스트": "test_name",
    "variant": "variant",
    "변형": "variant",
    "variant명": "variant",
    "action": "action",
    "동작": "action",
    "작업": "action",
    "campaign_name": "campaign_name",
    "캠페인명": "campaign_name",
    "캠페인": "campaign_name",
    "objective": "objective",
    "목표": "objective",
    "daily_budget": "daily_budget",
    "일예산": "daily_budget",
    "일일예산": "daily_budget",
    "countries": "countries",
    "국가": "countries",
    "age_min": "age_min",
    "최소연령": "age_min",
    "age_max": "age_max",
    "최대연령": "age_max",
    "start_date": "start_date",
    "시작일": "start_date",
    "end_date": "end_date",
    "종료일": "end_date",
    "publisher_platforms": "publisher_platforms",
    "게재위치": "publisher_platforms",
    "ad_name": "ad_name",
    "광고명": "ad_name",
    "primary_text": "primary_text",
    "기본문구": "primary_text",
    "본문": "primary_text",
    "headline": "headline",
    "제목": "headline",
    "description": "description",
    "설명": "description",
    "link_url": "link_url",
    "링크": "link_url",
    "url": "link_url",
    "cta": "cta",
    "버튼": "cta",
    "creative_drive_file": "creative_drive_file",
    "소재파일": "creative_drive_file",
    "소재": "creative_drive_file",
    "thumbnail_drive_file": "thumbnail_drive_file",
    "썸네일파일": "thumbnail_drive_file",
    "썸네일": "thumbnail_drive_file",
    "page_id": "page_id",
    "페이지id": "page_id",
    "페이지": "page_id",
    "pixel_id": "pixel_id",
    "픽셀id": "pixel_id",
    "픽셀": "pixel_id",
    "custom_event_type": "custom_event_type",
    "전환이벤트": "custom_event_type",
    "optimization_goal": "optimization_goal",
    "최적화목표": "optimization_goal",
    "billing_event": "billing_event",
    "과금이벤트": "billing_event",
    "special_ad_category": "special_ad_category",
    "특수광고분류": "special_ad_category",
    "instagram_user_id": "instagram_user_id",
    "인스타그램id": "instagram_user_id",
    "status": "status",
    "상태": "status",
    "meta_campaign_id": "meta_campaign_id",
    "캠페인id": "meta_campaign_id",
    "meta_adset_id": "meta_adset_id",
    "광고세트id": "meta_adset_id",
    "meta_creative_id": "meta_creative_id",
    "소재id": "meta_creative_id",
    "meta_ad_id": "meta_ad_id",
    "광고id": "meta_ad_id",
    "meta_study_id": "meta_study_id",
    "실험id": "meta_study_id",
    "error": "error",
    "오류": "error",
}

OBJECTIVES = {
    "outcome_awareness": "OUTCOME_AWARENESS",
    "awareness": "OUTCOME_AWARENESS",
    "reach": "OUTCOME_AWARENESS",
    "인지도": "OUTCOME_AWARENESS",
    "도달": "OUTCOME_AWARENESS",
    "outcome_traffic": "OUTCOME_TRAFFIC",
    "traffic": "OUTCOME_TRAFFIC",
    "link_clicks": "OUTCOME_TRAFFIC",
    "트래픽": "OUTCOME_TRAFFIC",
    "링크클릭": "OUTCOME_TRAFFIC",
    "outcome_engagement": "OUTCOME_ENGAGEMENT",
    "engagement": "OUTCOME_ENGAGEMENT",
    "참여": "OUTCOME_ENGAGEMENT",
    "outcome_leads": "OUTCOME_LEADS",
    "leads": "OUTCOME_LEADS",
    "리드": "OUTCOME_LEADS",
    "잠재고객": "OUTCOME_LEADS",
    "outcome_app_promotion": "OUTCOME_APP_PROMOTION",
    "app_installs": "OUTCOME_APP_PROMOTION",
    "앱": "OUTCOME_APP_PROMOTION",
    "앱설치": "OUTCOME_APP_PROMOTION",
    "outcome_sales": "OUTCOME_SALES",
    "sales": "OUTCOME_SALES",
    "conversions": "OUTCOME_SALES",
    "매출": "OUTCOME_SALES",
    "전환": "OUTCOME_SALES",
    "구매": "OUTCOME_SALES",
}

ACTIONS = {
    "": "create",
    "create": "create",
    "생성": "create",
    "만들기": "create",
    "등록": "create",
    "pause": "pause",
    "일시중지": "pause",
    "중지": "pause",
    "activate": "activate",
    "활성화": "activate",
    "게시": "activate",
    "재개": "activate",
}

CTAS = {
    "learn_more": "LEARN_MORE",
    "더 알아보기": "LEARN_MORE",
    "더알아보기": "LEARN_MORE",
    "shop_now": "SHOP_NOW",
    "구매하기": "SHOP_NOW",
    "sign_up": "SIGN_UP",
    "가입하기": "SIGN_UP",
    "apply_now": "APPLY_NOW",
    "신청하기": "APPLY_NOW",
    "contact_us": "CONTACT_US",
    "문의하기": "CONTACT_US",
    "download": "DOWNLOAD",
    "다운로드": "DOWNLOAD",
    "book_travel": "BOOK_TRAVEL",
    "예약하기": "BOOK_TRAVEL",
    "order_now": "ORDER_NOW",
    "주문하기": "ORDER_NOW",
    "subscribe": "SUBSCRIBE",
    "구독하기": "SUBSCRIBE",
}

EVENTS = {
    "purchase": "PURCHASE",
    "구매": "PURCHASE",
    "add_to_cart": "ADD_TO_CART",
    "장바구니": "ADD_TO_CART",
    "lead": "LEAD",
    "리드": "LEAD",
    "complete_registration": "COMPLETE_REGISTRATION",
    "가입": "COMPLETE_REGISTRATION",
    "content_view": "CONTENT_VIEW",
    "콘텐츠조회": "CONTENT_VIEW",
}

PLATFORMS = {
    "facebook": "facebook",
    "페이스북": "facebook",
    "instagram": "instagram",
    "인스타": "instagram",
    "인스타그램": "instagram",
    "audience_network": "audience_network",
    "오디언스네트워크": "audience_network",
    "messenger": "messenger",
    "메신저": "messenger",
}

COUNTRIES = {
    "한국": "KR",
    "대한민국": "KR",
    "미국": "US",
    "일본": "JP",
    "대만": "TW",
    "영국": "GB",
    "중국": "CN",
    "홍콩": "HK",
    "싱가포르": "SG",
    "베트남": "VN",
    "태국": "TH",
}

SPECIAL_CATEGORIES = {
    "": "",
    "none": "",
    "없음": "",
    "housing": "HOUSING",
    "주택": "HOUSING",
    "employment": "EMPLOYMENT",
    "고용": "EMPLOYMENT",
    "credit": "CREDIT",
    "신용": "CREDIT",
    "issues_elections_politics": "ISSUES_ELECTIONS_POLITICS",
    "정치": "ISSUES_ELECTIONS_POLITICS",
}

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def canonical_header(raw: str) -> str:
    key = raw.strip().lstrip("\ufeff").lower()
    return HEADER_ALIASES.get(key, key)


def column_letter(index: int) -> str:
    """1부터 시작하는 열 번호를 A1 표기 문자로 바꿉니다."""
    if index < 1:
        raise ValueError("열 번호는 1 이상이어야 합니다.")
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def quote_sheet_title(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


class TableStore:
    """시트 값을 메모리에 두고 결과 열만 다시 기록합니다."""

    def __init__(self, fieldnames: list[str], records: list[dict[str, str]]):
        self.fieldnames = list(fieldnames)
        self.records = records
        self.parse_issues: list[Issue] = []
        self._canonical = [canonical_header(name) for name in self.fieldnames]
        self._ensure_result_columns()

    def _ensure_result_columns(self) -> None:
        for field in RESULT_FIELDS:
            if field not in self._canonical:
                self.fieldnames.append(field)
                self._canonical.append(field)
                for record in self.records:
                    record[field] = ""

    def header_for(self, field: str) -> str:
        for original, canonical in zip(self.fieldnames, self._canonical):
            if canonical == field:
                return original
        raise KeyError(field)

    def load_rows(self) -> list[AdRow]:
        self.parse_issues = []
        rows: list[AdRow] = []
        for offset, record in enumerate(self.records):
            values = {
                canonical: str(record.get(original) or "").strip()
                for original, canonical in zip(self.fieldnames, self._canonical)
            }
            try:
                row = parse_row(offset + 2, values)
            except ValueError as exc:
                self.parse_issues.append(Issue(str(exc), row_number=offset + 2))
                continue
            if row is not None:
                rows.append(row)
        return rows

    def apply_result(self, row: AdRow) -> dict[str, str]:
        if row.row_number < 2 or row.row_number - 2 >= len(self.records):
            raise IndexError(f"{row.row_number}행을 시트에서 찾을 수 없습니다.")
        record = self.records[row.row_number - 2]
        written: dict[str, str] = {}
        for field in RESULT_FIELDS:
            header = self.header_for(field)
            value = str(getattr(row, field) or "")
            record[header] = value
            written[field] = value
        return written

    def mark_error(self, row_number: int, message: str) -> None:
        self._put(row_number, {"status": STATUS_ERROR, "error": message[:500]})
        self.persist_fields(row_number, ("status", "error"))

    def update(self, row: AdRow) -> None:
        self.apply_result(row)
        self.persist_fields(row.row_number, RESULT_FIELDS)

    def _put(self, row_number: int, fields: dict[str, str]) -> None:
        if row_number < 2 or row_number - 2 >= len(self.records):
            raise IndexError(f"{row_number}행을 시트에서 찾을 수 없습니다.")
        record = self.records[row_number - 2]
        for field, value in fields.items():
            record[self.header_for(field)] = value

    def persist_fields(self, row_number: int, fields: tuple[str, ...]) -> None:
        raise NotImplementedError


class CsvTable(TableStore):
    def __init__(self, path: Path):
        self.path = path
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError(f"{path}에 헤더 행이 없습니다.")
            records = [dict(row) for row in reader]
            super().__init__(list(reader.fieldnames), records)

    def persist_fields(self, row_number: int, fields: tuple[str, ...]) -> None:
        del row_number, fields
        self.write()

    def write(self) -> None:
        with self.path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.records)


def parse_row(row_number: int, values: dict[str, str]) -> AdRow | None:
    row = AdRow(
        row_number=row_number,
        test_name=values.get("test_name", ""),
        variant=values.get("variant", ""),
        action=_mapped(ACTIONS, values.get("action", ""), "동작", allow_unknown=False) or "create",
        campaign_name=values.get("campaign_name", "") or values.get("test_name", ""),
        objective=_objective(values.get("objective", "")),
        daily_budget=_budget(values.get("daily_budget", "")),
        countries=_countries(values.get("countries", "")),
        age_min=_int(values.get("age_min", ""), 18),
        age_max=_int(values.get("age_max", ""), 65),
        start_date=_date(values.get("start_date", "")),
        end_date=_date(values.get("end_date", "")),
        publisher_platforms=_platforms(values.get("publisher_platforms", "")),
        ad_name=values.get("ad_name", ""),
        primary_text=values.get("primary_text", ""),
        headline=values.get("headline", ""),
        description=values.get("description", ""),
        link_url=values.get("link_url", ""),
        cta=_mapped(CTAS, values.get("cta", ""), "버튼") or "LEARN_MORE",
        creative_drive_file=values.get("creative_drive_file", ""),
        thumbnail_drive_file=values.get("thumbnail_drive_file", ""),
        page_id=values.get("page_id", ""),
        pixel_id=values.get("pixel_id", ""),
        custom_event_type=_mapped(EVENTS, values.get("custom_event_type", ""), "전환이벤트"),
        optimization_goal=values.get("optimization_goal", "").upper(),
        billing_event=values.get("billing_event", "").upper(),
        special_ad_category=_mapped(
            SPECIAL_CATEGORIES, values.get("special_ad_category", ""), "특수광고분류"
        ),
        instagram_user_id=values.get("instagram_user_id", ""),
        status=values.get("status", ""),
        meta_campaign_id=values.get("meta_campaign_id", ""),
        meta_adset_id=values.get("meta_adset_id", ""),
        meta_creative_id=values.get("meta_creative_id", ""),
        meta_ad_id=values.get("meta_ad_id", ""),
        meta_study_id=values.get("meta_study_id", ""),
        error=values.get("error", ""),
    )
    if not row.ad_name and row.test_name and row.variant:
        row.ad_name = f"{row.test_name}_{row.variant}"
    if row.is_blank:
        return None
    return row


def _mapped(table: dict[str, str], raw: str, label: str, allow_unknown: bool = True) -> str:
    text = raw.strip()
    if text.lower() in table:
        return table[text.lower()]
    if text in table:
        return table[text]
    if not text:
        return ""
    if allow_unknown and text.upper() == text and " " not in text:
        return text
    if not allow_unknown:
        known = ", ".join(sorted({value for value in table.values() if value}))
        raise ValueError(f"{label} 값 '{raw}'을 알 수 없습니다. 사용할 수 있는 값: {known}")
    return text


def _objective(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if text.upper().startswith("OUTCOME_"):
        return text.upper()
    key = text.lower()
    if key in OBJECTIVES:
        return OBJECTIVES[key]
    if text in OBJECTIVES:
        return OBJECTIVES[text]
    raise ValueError(f"목표 '{raw}'을 알 수 없습니다. 트래픽, 매출, 리드, 인지도, 참여, 앱설치 중 하나를 쓰세요.")


def _budget(raw: str) -> int | None:
    text = raw.strip().replace(",", "").replace("원", "").replace(" ", "")
    if not text:
        return None
    if not text.isdigit():
        raise ValueError(f"일예산 '{raw}'은 숫자여야 합니다. 원화는 원 단위, 달러 계정은 센트 단위입니다.")
    return int(text)


def _int(raw: str, default: int) -> int:
    text = raw.strip()
    if not text:
        return default
    if not text.isdigit():
        raise ValueError(f"숫자 값 '{raw}'을 읽지 못했습니다.")
    return int(text)


def _date(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if not _DATE.match(text):
        raise ValueError(f"날짜 '{raw}'은 YYYY-MM-DD 형식이어야 합니다.")
    return text


def _split(raw: str) -> list[str]:
    text = raw.replace("，", ",").replace("、", ",")
    return [part.strip() for part in text.split(",") if part.strip()]


def _countries(raw: str) -> list[str]:
    found = []
    for part in _split(raw):
        if part in COUNTRIES:
            found.append(COUNTRIES[part])
        elif part.lower() in {code.lower() for code in ("kr", "us", "jp")}:
            found.append(part.upper())
        elif re.fullmatch(r"[A-Za-z]{2}", part):
            found.append(part.upper())
        else:
            mapped = COUNTRIES.get(part)
            if mapped:
                found.append(mapped)
            else:
                raise ValueError(f"국가 '{part}'을 알 수 없습니다. KR 같은 국가 코드를 쓰세요.")
    return found


def _platforms(raw: str) -> list[str]:
    found = []
    for part in _split(raw):
        key = part.lower()
        if key in PLATFORMS:
            found.append(PLATFORMS[key])
        elif part in PLATFORMS:
            found.append(PLATFORMS[part])
        else:
            raise ValueError(f"게재위치 '{part}'을 알 수 없습니다.")
    return found
