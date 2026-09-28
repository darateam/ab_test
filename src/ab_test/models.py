from __future__ import annotations

from dataclasses import dataclass, field


STATUS_CREATED = "생성됨"
STATUS_PAUSED = "일시중지"
STATUS_ACTIVE = "게시됨"
STATUS_ERROR = "오류"

RESULT_FIELDS = (
    "status",
    "meta_campaign_id",
    "meta_adset_id",
    "meta_creative_id",
    "meta_ad_id",
    "meta_study_id",
    "error",
)

OBJECTIVE_DELIVERY = {
    "OUTCOME_AWARENESS": ("REACH", "IMPRESSIONS"),
    "OUTCOME_TRAFFIC": ("LINK_CLICKS", "IMPRESSIONS"),
    "OUTCOME_ENGAGEMENT": ("POST_ENGAGEMENT", "IMPRESSIONS"),
    "OUTCOME_LEADS": ("LEAD_GENERATION", "IMPRESSIONS"),
    "OUTCOME_APP_PROMOTION": ("APP_INSTALLS", "IMPRESSIONS"),
    "OUTCOME_SALES": ("OFFSITE_CONVERSIONS", "IMPRESSIONS"),
}


@dataclass
class AdRow:
    row_number: int
    test_name: str = ""
    variant: str = ""
    action: str = "create"
    campaign_name: str = ""
    objective: str = ""
    daily_budget: int | None = None
    countries: list[str] = field(default_factory=list)
    age_min: int = 18
    age_max: int = 65
    start_date: str = ""
    end_date: str = ""
    publisher_platforms: list[str] = field(default_factory=list)
    ad_name: str = ""
    primary_text: str = ""
    headline: str = ""
    description: str = ""
    link_url: str = ""
    cta: str = "LEARN_MORE"
    creative_drive_file: str = ""
    thumbnail_drive_file: str = ""
    page_id: str = ""
    pixel_id: str = ""
    custom_event_type: str = ""
    optimization_goal: str = ""
    billing_event: str = ""
    special_ad_category: str = ""
    instagram_user_id: str = ""
    status: str = ""
    meta_campaign_id: str = ""
    meta_adset_id: str = ""
    meta_creative_id: str = ""
    meta_ad_id: str = ""
    meta_study_id: str = ""
    error: str = ""

    @property
    def is_blank(self) -> bool:
        return not any(
            (
                self.test_name,
                self.variant,
                self.campaign_name,
                self.ad_name,
                self.creative_drive_file,
                self.primary_text,
            )
        )

    def resolved_page_id(self, default_page_id: str) -> str:
        return self.page_id or default_page_id

    def delivery(self) -> tuple[str, str]:
        goal, billing = OBJECTIVE_DELIVERY.get(
            self.objective, ("LINK_CLICKS", "IMPRESSIONS")
        )
        return self.optimization_goal or goal, self.billing_event or billing


@dataclass
class Issue:
    message: str
    test_name: str = ""
    row_number: int | None = None
    blocking_test: bool = False


@dataclass
class AdPlan:
    row: AdRow
    create: bool


@dataclass
class AdSetPlan:
    variant: str
    name: str
    daily_budget: int
    countries: list[str]
    age_min: int
    age_max: int
    start_date: str
    end_date: str
    publisher_platforms: list[str]
    optimization_goal: str
    billing_event: str
    pixel_id: str
    custom_event_type: str
    page_id: str
    ads: list[AdPlan]


@dataclass
class CampaignPlan:
    test_name: str
    campaign_name: str
    objective: str
    special_ad_category: str
    adsets: list[AdSetPlan]

    def existing_campaign_id(self) -> str:
        for adset in self.adsets:
            for ad in adset.ads:
                if ad.row.meta_campaign_id:
                    return ad.row.meta_campaign_id
        return ""


@dataclass
class ControlAction:
    row: AdRow
    status: str


@dataclass
class RowResult:
    row_number: int
    ok: bool
    message: str


@dataclass
class RunReport:
    dry_run: bool
    results: list[RowResult]
    plan_lines: list[str]

    @property
    def ok(self) -> bool:
        return all(item.ok for item in self.results)
