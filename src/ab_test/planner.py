from __future__ import annotations

from ab_test.models import (
    AdPlan,
    AdRow,
    AdSetPlan,
    CampaignPlan,
    ControlAction,
    Issue,
)

VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v")


def split_percentages(count: int) -> list[int]:
    if count < 2 or count > 5:
        raise ValueError("A/B 실험은 변형이 2개에서 5개까지여야 합니다.")
    base, extra = divmod(100, count)
    return [base + (1 if index < extra else 0) for index in range(count)]


def build_plan(
    rows: list[AdRow], default_page_id: str
) -> tuple[list[CampaignPlan], list[ControlAction], list[Issue]]:
    issues: list[Issue] = []
    controls: list[ControlAction] = []
    grouped: dict[str, list[AdRow]] = {}

    for row in rows:
        if row.action == "pause":
            _append_control(row, "PAUSED", controls, issues)
            continue
        if row.action == "activate":
            _append_control(row, "ACTIVE", controls, issues)
            continue
        row_issues = validate_create_row(row, default_page_id)
        if row_issues:
            issues.extend(row_issues)
            continue
        grouped.setdefault(row.test_name, []).append(row)

    plans: list[CampaignPlan] = []
    for test_name, test_rows in grouped.items():
        conflicts = consistency_issues(test_rows)
        if conflicts:
            issues.extend(conflicts)
            flagged = {issue.row_number for issue in conflicts}
            for row in test_rows:
                if row.row_number not in flagged:
                    issues.append(
                        Issue(
                            "같은 테스트의 다른 행 설정이 맞지 않아 생성하지 않았습니다.",
                            test_name,
                            row.row_number,
                        )
                    )
            continue
        plans.append(_campaign(test_rows, default_page_id))
    return plans, controls, issues


def validate_create_row(row: AdRow, default_page_id: str) -> list[Issue]:
    messages: list[str] = []
    if not row.test_name:
        messages.append("테스트명이 필요합니다.")
    if not row.variant:
        messages.append("변형이 필요합니다.")
    if not row.objective:
        messages.append("목표가 필요합니다.")
    if row.daily_budget is None or row.daily_budget <= 0:
        messages.append("일예산은 0보다 큰 숫자여야 합니다.")
    if not row.countries:
        messages.append("국가가 필요합니다. 예: KR")
    if row.age_min < 13 or row.age_max > 65 or row.age_min > row.age_max:
        messages.append("연령은 13세 이상 65세 이하이고, 최소연령이 최대연령보다 클 수 없습니다.")
    if not row.primary_text:
        messages.append("기본문구가 필요합니다.")
    if not row.headline:
        messages.append("제목이 필요합니다.")
    if not row.link_url.startswith("http://") and not row.link_url.startswith("https://"):
        messages.append("링크는 http 또는 https로 시작해야 합니다.")
    if not row.creative_drive_file:
        messages.append("소재파일이 필요합니다.")
    if not row.resolved_page_id(default_page_id):
        messages.append("페이지 ID가 필요합니다. 시트 또는 META_PAGE_ID에 입력하세요.")
    if row.objective == "OUTCOME_SALES" and not row.pixel_id:
        messages.append("매출 목표는 픽셀 ID가 필요합니다.")
    if _is_video_name(row.creative_drive_file) and not row.thumbnail_drive_file:
        messages.append("동영상 소재는 썸네일파일이 필요합니다.")
    if row.start_date and row.end_date and row.start_date > row.end_date:
        messages.append("종료일은 시작일보다 빠를 수 없습니다.")
    return [Issue(message, row.test_name, row.row_number) for message in messages]


def consistency_issues(rows: list[AdRow]) -> list[Issue]:
    issues: list[Issue] = []
    first = rows[0]
    for row in rows[1:]:
        if row.campaign_name != first.campaign_name or row.objective != first.objective:
            issues.append(
                Issue(
                    "같은 테스트의 캠페인명과 목표는 같아야 합니다.",
                    first.test_name,
                    row.row_number,
                    blocking_test=True,
                )
            )
            break
        if row.special_ad_category != first.special_ad_category:
            issues.append(
                Issue(
                    "같은 테스트의 특수광고분류는 같아야 합니다.",
                    first.test_name,
                    row.row_number,
                    blocking_test=True,
                )
            )
            break
    campaign_ids = {row.meta_campaign_id for row in rows if row.meta_campaign_id}
    if len(campaign_ids) > 1:
        issues.append(
            Issue(
                "같은 테스트에 서로 다른 캠페인 ID가 있습니다.",
                first.test_name,
                first.row_number,
                blocking_test=True,
            )
        )

    by_variant: dict[str, list[AdRow]] = {}
    for row in rows:
        by_variant.setdefault(row.variant, []).append(row)
    for variant, variant_rows in by_variant.items():
        anchor = variant_rows[0]
        for row in variant_rows[1:]:
            if _adset_signature(row) != _adset_signature(anchor):
                issues.append(
                    Issue(
                        f"변형 {variant}의 예산, 국가, 연령, 기간, 게재위치가 행마다 다릅니다.",
                        first.test_name,
                        row.row_number,
                        blocking_test=True,
                    )
                )
                break
        adset_ids = {row.meta_adset_id for row in variant_rows if row.meta_adset_id}
        if len(adset_ids) > 1:
            issues.append(
                Issue(
                    f"변형 {variant}에 서로 다른 광고세트 ID가 있습니다.",
                    first.test_name,
                    anchor.row_number,
                    blocking_test=True,
                )
            )
    return issues


def _append_control(
    row: AdRow,
    status: str,
    controls: list[ControlAction],
    issues: list[Issue],
) -> None:
    if not row.meta_ad_id and not row.meta_adset_id:
        issues.append(
            Issue(
                "메타 광고 ID가 없어 상태를 바꿀 수 없습니다. 먼저 생성하세요.",
                row.test_name,
                row.row_number,
            )
        )
        return
    controls.append(ControlAction(row, status))


def _campaign(rows: list[AdRow], default_page_id: str) -> CampaignPlan:
    first = rows[0]
    by_variant: dict[str, list[AdRow]] = {}
    for row in rows:
        by_variant.setdefault(row.variant, []).append(row)
    adsets = []
    for variant, variant_rows in by_variant.items():
        anchor = variant_rows[0]
        goal, billing = anchor.delivery()
        adsets.append(
            AdSetPlan(
                variant=variant,
                name=f"{anchor.campaign_name} / {variant}",
                daily_budget=anchor.daily_budget or 0,
                countries=list(anchor.countries),
                age_min=anchor.age_min,
                age_max=anchor.age_max,
                start_date=anchor.start_date,
                end_date=anchor.end_date,
                publisher_platforms=list(anchor.publisher_platforms),
                optimization_goal=goal,
                billing_event=billing,
                pixel_id=anchor.pixel_id,
                custom_event_type=anchor.custom_event_type,
                page_id=anchor.resolved_page_id(default_page_id),
                ads=[AdPlan(row=item, create=not item.meta_ad_id) for item in variant_rows],
            )
        )
    return CampaignPlan(
        test_name=first.test_name,
        campaign_name=first.campaign_name,
        objective=first.objective,
        special_ad_category=first.special_ad_category,
        adsets=adsets,
    )


def _adset_signature(row: AdRow) -> tuple:
    return (
        row.daily_budget,
        tuple(row.countries),
        row.age_min,
        row.age_max,
        row.start_date,
        row.end_date,
        tuple(row.publisher_platforms),
        row.optimization_goal,
        row.billing_event,
        row.pixel_id,
        row.custom_event_type,
        row.page_id,
    )


def _is_video_name(name: str) -> bool:
    lowered = name.lower().split("?")[0]
    return lowered.endswith(VIDEO_EXTENSIONS)
