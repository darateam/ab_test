from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ab_test.config import Settings
from ab_test.drive import CreativeBlob
from ab_test.meta import (
    ad_body,
    adset_body,
    campaign_body,
    creative_body,
    split_test_body,
)
from ab_test.models import (
    STATUS_ACTIVE,
    STATUS_CREATED,
    STATUS_ERROR,
    STATUS_PAUSED,
    AdSetPlan,
    CampaignPlan,
    ControlAction,
    Issue,
    RowResult,
    RunReport,
)
from ab_test.planner import build_plan, split_percentages


class Runner:
    def __init__(self, settings: Settings, meta=None, creatives=None, writer=None, clock=None):
        self.settings = settings
        self.meta = meta
        self.creatives = creatives
        self.writer = writer
        self.clock = clock or (lambda: datetime.now(ZoneInfo(settings.timezone)))
        self.results: list[RowResult] = []
        self.lines: list[str] = []

    def run(self, rows, parse_issues: list[Issue] | None = None) -> RunReport:
        plans, controls, issues = build_plan(rows, self.settings.meta_page_id)
        for issue in list(parse_issues or []) + issues:
            self._record_issue(issue)

        for plan in plans:
            self._describe(plan)
            if self.settings.apply:
                self._execute(plan)
            else:
                self._preview(plan)

        for action in controls:
            self._describe_control(action)
            if self.settings.apply:
                self._execute_control(action)
            else:
                self._preview_control(action)

        if not self.results and not self.lines:
            self.lines.append("처리할 광고 행이 없습니다.")
        return RunReport(dry_run=not self.settings.apply, results=self.results, plan_lines=self.lines)

    def _describe(self, plan: CampaignPlan) -> None:
        prefix = "실행" if self.settings.apply else "미리보기"
        self.lines.append(f"[{prefix}] 캠페인 '{plan.campaign_name}' / {plan.objective}")
        for adset in plan.adsets:
            pending = [ad for ad in adset.ads if ad.create]
            countries = ",".join(adset.countries)
            self.lines.append(
                f"  광고세트 '{adset.name}' 일예산 {adset.daily_budget:,} 국가 {countries} 신규 {len(pending)}개"
            )
            for ad in pending:
                self.lines.append(f"    {ad.row.row_number}행 {ad.row.ad_name} ← {ad.row.creative_drive_file}")
        self._describe_study(plan)

    def _describe_study(self, plan: CampaignPlan) -> None:
        if len(plan.adsets) < 2:
            return
        if any(ad.row.meta_study_id for adset in plan.adsets for ad in adset.ads):
            self.lines.append("  A/B 실험 ID가 있어 다시 만들지 않습니다.")
            return
        if not self.settings.meta_business_id:
            self.lines.append("  META_BUSINESS_ID가 없어 A/B 실험을 만들지 않습니다.")
            return
        if not self.settings.create_split_test:
            self.lines.append("  A/B 실험은 만들지 않습니다. CREATE_SPLIT_TEST가 꺼져 있습니다.")
            return
        self.lines.append("  변형이 둘 이상이면 A/B 실험을 만듭니다.")

    def _preview(self, plan: CampaignPlan) -> None:
        for adset in plan.adsets:
            for ad in adset.ads:
                if ad.create:
                    self._ok(ad.row.row_number, "미리보기: 광고는 일시중지 상태로 만들어지며 광고비는 지출되지 않습니다.")
                else:
                    self._ok(ad.row.row_number, "이미 광고 ID가 있어 다시 만들지 않습니다.")

    def _execute(self, plan: CampaignPlan) -> None:
        for adset in plan.adsets:
            self._execute_adset(plan, adset)
        self._maybe_study(plan)

    def _execute_adset(self, plan: CampaignPlan, adset: AdSetPlan) -> None:
        for ad in adset.ads:
            if not ad.create:
                self._ok(ad.row.row_number, "이미 광고 ID가 있어 다시 만들지 않습니다.")
        pending = [ad for ad in adset.ads if ad.create]
        if not pending:
            return
        loaded = []
        for ad in pending:
            try:
                loaded.append((ad, self._load(ad.row)))
            except Exception as exc:
                self._fail(ad.row, str(exc))
        if not loaded:
            return
        try:
            campaign_id = self._ensure_campaign(plan)
            adset_id = self._ensure_adset(plan, adset, campaign_id)
        except Exception as exc:
            for ad, _assets in loaded:
                self._fail(ad.row, str(exc))
            return
        for ad, assets in loaded:
            try:
                self._create_ad(adset, adset_id, ad, assets)
            except Exception as exc:
                self._fail(ad.row, str(exc))

    def _create_ad(self, adset: AdSetPlan, adset_id: str, ad, assets) -> None:
        row = ad.row
        existing = self.meta.find_by_name(
            "ads",
            row.ad_name,
            [{"field": "adset.id", "operator": "EQUAL", "value": adset_id}],
        )
        if existing:
            row.meta_ad_id = existing
            row.status = STATUS_CREATED
            row.error = ""
            self._save(row)
            self._ok(row.row_number, f"같은 이름의 광고가 있어 재사용합니다: {existing}")
            return
        blob, thumbnail = assets
        if row.meta_creative_id:
            creative_id = row.meta_creative_id
        else:
            creative_id = self.meta.create_creative(self._creative_payload(adset, row, blob, thumbnail))
            self._assign([row], meta_creative_id=creative_id)
        ad_id = self.meta.create_ad(ad_body(row.ad_name, adset_id, creative_id))
        row.meta_ad_id = ad_id
        row.status = STATUS_CREATED
        row.error = ""
        self._save(row)
        self._ok(row.row_number, f"일시중지 상태로 광고를 만들었습니다: {ad_id}")

    def _creative_payload(self, adset: AdSetPlan, row, blob: CreativeBlob, thumbnail: CreativeBlob | None) -> dict:
        if blob.is_video:
            if thumbnail is None:
                raise ValueError("동영상 소재는 썸네일파일이 필요합니다.")
            video_id = self.meta.upload_video(blob.name, blob.data, blob.mime)
            thumbnail_hash = self.meta.upload_image(thumbnail.name, thumbnail.data, thumbnail.mime)
            return creative_body(
                name=row.ad_name,
                page_id=adset.page_id,
                primary_text=row.primary_text,
                headline=row.headline,
                description=row.description,
                link_url=row.link_url,
                cta=row.cta,
                instagram_user_id=row.instagram_user_id,
                video_id=video_id,
                thumbnail_hash=thumbnail_hash,
            )
        image_hash = self.meta.upload_image(blob.name, blob.data, blob.mime)
        return creative_body(
            name=row.ad_name,
            page_id=adset.page_id,
            primary_text=row.primary_text,
            headline=row.headline,
            description=row.description,
            link_url=row.link_url,
            cta=row.cta,
            instagram_user_id=row.instagram_user_id,
            image_hash=image_hash,
        )

    def _load(self, row) -> tuple[CreativeBlob, CreativeBlob | None]:
        if self.creatives is None:
            raise ValueError("소재 위치가 없습니다. GOOGLE_DRIVE_FOLDER_ID 또는 CREATIVES_DIR를 설정하세요.")
        blob = self.creatives.fetch(row.creative_drive_file)
        if not blob.is_video:
            return blob, None
        if not row.thumbnail_drive_file:
            raise ValueError("동영상 소재는 썸네일파일이 필요합니다.")
        return blob, self.creatives.fetch(row.thumbnail_drive_file)

    def _ensure_campaign(self, plan: CampaignPlan) -> str:
        rows = _rows(plan)
        existing = plan.existing_campaign_id()
        if existing:
            self._assign(rows, meta_campaign_id=existing)
            return existing
        found = self.meta.find_by_name("campaigns", plan.campaign_name)
        if found:
            self._assign(rows, meta_campaign_id=found)
            return found
        created = self.meta.create_campaign(campaign_body(plan))
        self._assign(rows, meta_campaign_id=created)
        return created

    def _ensure_adset(self, plan: CampaignPlan, adset: AdSetPlan, campaign_id: str) -> str:
        rows = [ad.row for ad in adset.ads]
        existing = next((row.meta_adset_id for row in rows if row.meta_adset_id), "")
        if existing:
            self._assign(rows, meta_adset_id=existing)
            return existing
        found = self.meta.find_by_name(
            "adsets",
            adset.name,
            [{"field": "campaign.id", "operator": "EQUAL", "value": campaign_id}],
        )
        if found:
            self._assign(rows, meta_adset_id=found)
            return found
        start_time, end_time = self._schedule(adset)
        created = self.meta.create_adset(adset_body(adset, campaign_id, plan.objective, start_time, end_time))
        self._assign(rows, meta_adset_id=created)
        return created

    def _maybe_study(self, plan: CampaignPlan) -> None:
        if not self.settings.create_split_test or not self.settings.meta_business_id:
            return
        if any(ad.row.meta_study_id for adset in plan.adsets for ad in adset.ads):
            return
        ready = []
        for adset in plan.adsets:
            adset_id = next((ad.row.meta_adset_id for ad in adset.ads if ad.row.meta_adset_id), "")
            if adset_id:
                ready.append((adset, adset_id))
        if len(ready) < 2:
            self.lines.append("  광고세트가 2개 미만이라 A/B 실험을 만들지 않았습니다.")
            return
        if len(ready) > 5:
            self._note_study_error(plan, "A/B 실험은 변형이 2개에서 5개까지입니다.")
            return
        try:
            percentages = split_percentages(len(ready))
            cells = [
                {"name": adset.variant, "treatment_percentage": percent, "adsets": [adset_id]}
                for (adset, adset_id), percent in zip(ready, percentages)
            ]
            start_time, end_time = self._study_window(plan)
            study_id = self.meta.create_split_test(
                self.settings.meta_business_id,
                split_test_body(f"{plan.campaign_name} A/B", cells, start_time, end_time),
            )
        except Exception as exc:
            self._note_study_error(plan, f"실험 생성 실패: {exc}")
            return
        self._assign(_rows(plan), meta_study_id=study_id)
        self.lines.append(f"  A/B 실험 {study_id}")
        self._ok(_rows(plan)[0].row_number, f"A/B 실험을 만들었습니다: {study_id}")

    def _execute_control(self, action: ControlAction) -> None:
        row = action.row
        if action.status == "ACTIVE" and not self.settings.allow_active:
            self._fail(
                row,
                "게시는 --allow-active 가 필요합니다. 광고비가 지출되지 않도록 막아 둔 안전장치입니다.",
            )
            return
        try:
            if action.status == "ACTIVE" and row.meta_campaign_id:
                self.meta.set_status(row.meta_campaign_id, "ACTIVE", entity_type="campaign")
            if row.meta_adset_id:
                self.meta.set_status(row.meta_adset_id, action.status, entity_type="adset")
            if row.meta_ad_id:
                self.meta.set_status(row.meta_ad_id, action.status, entity_type="ad")
        except Exception as exc:
            self._fail(row, str(exc))
            return
        row.status = STATUS_ACTIVE if action.status == "ACTIVE" else STATUS_PAUSED
        row.error = ""
        self._save(row)
        label = "게시" if action.status == "ACTIVE" else "일시중지"
        self._ok(row.row_number, f"광고를 {label}했습니다.")

    def _preview_control(self, action: ControlAction) -> None:
        if action.status == "ACTIVE" and not self.settings.allow_active:
            self.results.append(
                RowResult(
                    action.row.row_number,
                    False,
                    "미리보기: 게시는 --allow-active 가 있어야 실행됩니다.",
                )
            )
            return
        label = "게시" if action.status == "ACTIVE" else "일시중지"
        self._ok(action.row.row_number, f"미리보기: 광고를 {label}합니다.")

    def _describe_control(self, action: ControlAction) -> None:
        label = "게시" if action.status == "ACTIVE" else "일시중지"
        self.lines.append(f"{action.row.row_number}행 {action.row.ad_name or action.row.test_name} {label}")

    def _schedule(self, adset: AdSetPlan) -> tuple[str, str]:
        return (
            _clock_text(adset.start_date, False, self.settings.timezone),
            _clock_text(adset.end_date, True, self.settings.timezone),
        )

    def _study_window(self, plan: CampaignPlan) -> tuple[int, int]:
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=ZoneInfo(self.settings.timezone))
        starts = [adset.start_date for adset in plan.adsets if adset.start_date]
        ends = [adset.end_date for adset in plan.adsets if adset.end_date]
        if starts:
            start = datetime.fromisoformat(_clock_text(min(starts), False, self.settings.timezone))
            if start < now + timedelta(minutes=30):
                start = now + timedelta(hours=1)
        else:
            start = now + timedelta(hours=1)
        if ends:
            end = datetime.fromisoformat(_clock_text(max(ends), True, self.settings.timezone))
        else:
            end = start + timedelta(days=7)
        if end <= start + timedelta(hours=24):
            end = start + timedelta(days=7)
        return int(start.timestamp()), int(end.timestamp())

    def _assign(self, rows, **fields) -> None:
        for row in rows:
            changed = False
            for key, value in fields.items():
                if getattr(row, key) != value:
                    setattr(row, key, value)
                    changed = True
            if changed:
                self._save(row)

    def _save(self, row) -> None:
        if self.settings.apply and self.writer is not None:
            self.writer.update(row)

    def _record_issue(self, issue: Issue) -> None:
        self.results.append(RowResult(issue.row_number or 0, False, issue.message))
        if self.settings.apply and self.writer is not None and issue.row_number:
            self.writer.mark_error(issue.row_number, issue.message)

    def _note_study_error(self, plan: CampaignPlan, message: str) -> None:
        text = message[:500]
        for row in _rows(plan):
            if row.status == STATUS_ERROR or row.error:
                continue
            row.error = text
            self._save(row)
        first = _rows(plan)[0]
        self.results.append(RowResult(first.row_number, False, text))
        self.lines.append(f"  {text}")

    def _ok(self, row_number: int, message: str) -> None:
        self.results.append(RowResult(row_number, True, message))

    def _fail(self, row, message: str) -> None:
        text = str(message)[:500]
        row.status = STATUS_ERROR
        row.error = text
        self._save(row)
        self.results.append(RowResult(row.row_number, False, text))


def _rows(plan: CampaignPlan):
    return [ad.row for adset in plan.adsets for ad in adset.ads]


def _clock_text(date_text: str, end: bool, timezone: str) -> str:
    if not date_text:
        return ""
    year, month, day = (int(part) for part in date_text.split("-"))
    hour, minute, second = (23, 59, 59) if end else (0, 0, 0)
    moment = datetime(year, month, day, hour, minute, second, tzinfo=ZoneInfo(timezone))
    return moment.isoformat()
