import csv
from datetime import datetime
from zoneinfo import ZoneInfo

from ab_test.cli import main
from ab_test.config import Settings
from ab_test.drive import LocalCreativeStore
from ab_test.planner import split_percentages
from ab_test.runner import Runner
from ab_test.sheet import CsvTable

HEADERS = [
    "테스트명",
    "변형",
    "동작",
    "캠페인명",
    "목표",
    "일예산",
    "국가",
    "최소연령",
    "최대연령",
    "시작일",
    "종료일",
    "게재위치",
    "광고명",
    "기본문구",
    "제목",
    "설명",
    "링크",
    "버튼",
    "소재파일",
    "썸네일파일",
    "페이지ID",
    "상태",
    "캠페인ID",
    "광고세트ID",
    "소재ID",
    "광고ID",
    "실험ID",
    "오류",
]


def settings(**overrides) -> Settings:
    values = dict(
        meta_access_token="token",
        meta_ad_account_id="act_1",
        meta_page_id="page_1",
        meta_business_id="biz_1",
        meta_api_version="v25.0",
        google_sheet_id="",
        google_sheet_range="",
        google_drive_folder_id="",
        google_service_account_file="",
        google_oauth_client_secrets="",
        google_oauth_token_file="token.json",
        sheet_path="",
        creatives_dir="",
        create_split_test=True,
        timezone="Asia/Seoul",
        apply=False,
        allow_active=False,
    )
    values.update(overrides)
    return Settings(**values)


class FakeMeta:
    def __init__(self):
        self.calls = []
        self.sequence = 0

    def _next(self, prefix):
        self.sequence += 1
        return f"{prefix}_{self.sequence}"

    def find_by_name(self, edge, name, extra_filters=None):
        self.calls.append(("find", edge, name, extra_filters))
        return None

    def create_campaign(self, payload):
        self.calls.append(("campaign", payload))
        return self._next("camp")

    def create_adset(self, payload):
        self.calls.append(("adset", payload))
        return self._next("adset")

    def upload_image(self, filename, data, mime):
        self.calls.append(("image", filename, mime))
        return "hash_" + filename

    def upload_video(self, filename, data, mime):
        self.calls.append(("video", filename, mime))
        return self._next("video")

    def create_creative(self, payload):
        self.calls.append(("creative", payload))
        return self._next("creative")

    def create_ad(self, payload):
        self.calls.append(("ad", payload))
        return self._next("ad")

    def set_status(self, object_id, status, entity_type=""):
        del entity_type
        self.calls.append(("status", object_id, status))

    def create_split_test(self, business_id, payload):
        self.calls.append(("study", business_id, payload))
        return self._next("study")


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in HEADERS})


def base_row(**overrides):
    row = {
        "테스트명": "여름세일",
        "변형": "A",
        "동작": "생성",
        "캠페인명": "여름세일_AB",
        "목표": "트래픽",
        "일예산": "20000",
        "국가": "한국",
        "최소연령": "18",
        "최대연령": "45",
        "시작일": "2026-10-01",
        "종료일": "2026-10-14",
        "게재위치": "페이스북,인스타그램",
        "광고명": "여름세일_A",
        "기본문구": "시원한 세일",
        "제목": "최대 50%",
        "설명": "이번 주만",
        "링크": "https://example.com/sale",
        "버튼": "더 알아보기",
        "소재파일": "a.png",
        "페이지ID": "111",
    }
    row.update(overrides)
    return row


def test_split_percentages_cover_one_hundred():
    assert split_percentages(2) == [50, 50]
    assert split_percentages(3) == [34, 33, 33]
    assert sum(split_percentages(5)) == 100


def test_template_previews_two_paused_variants():
    table = CsvTable(__import__("pathlib").Path("examples/ads_template.csv"))
    rows = table.load_rows()
    report = Runner(settings(create_split_test=True)).run(rows, table.parse_issues)
    assert report.ok
    assert report.dry_run
    assert len(rows) == 2
    assert all("일시중지" in item.message for item in report.results)
    assert any("A/B" in line for line in report.plan_lines)


def test_dry_run_does_not_touch_the_sheet(tmp_path):
    path = tmp_path / "ads.csv"
    write_csv(path, [base_row(), base_row(변형="B", 광고명="여름세일_B", 소재파일="b.png")])
    before = path.read_bytes()
    table = CsvTable(path)
    report = Runner(settings()).run(table.load_rows(), table.parse_issues)
    assert report.ok
    assert path.read_bytes() == before


def test_apply_creates_paused_ads_and_split_test(tmp_path):
    path = tmp_path / "ads.csv"
    creatives = tmp_path / "creatives"
    creatives.mkdir()
    (creatives / "a.png").write_bytes(b"png-a")
    (creatives / "b.png").write_bytes(b"png-b")
    write_csv(path, [base_row(), base_row(변형="B", 광고명="여름세일_B", 소재파일="b.png")])
    table = CsvTable(path)
    meta = FakeMeta()
    clock = lambda: datetime(2026, 9, 28, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    report = Runner(
        settings(apply=True),
        meta=meta,
        creatives=LocalCreativeStore(creatives),
        writer=table,
        clock=clock,
    ).run(table.load_rows(), table.parse_issues)

    assert report.ok, report.results
    kinds = [call[0] for call in meta.calls]
    assert kinds.count("campaign") == 1
    assert kinds.count("adset") == 2
    assert kinds.count("ad") == 2
    assert kinds.count("study") == 1
    campaign = next(call[1] for call in meta.calls if call[0] == "campaign")
    assert campaign["status"] == "PAUSED"
    assert campaign["objective"] == "OUTCOME_TRAFFIC"
    assert campaign["special_ad_categories"] == []
    ads = [call[1] for call in meta.calls if call[0] == "ad"]
    assert {ad["status"] for ad in ads} == {"PAUSED"}
    adset = next(call[1] for call in meta.calls if call[0] == "adset")
    assert adset["promoted_object"] == {"page_id": "111"}
    assert adset["destination_type"] == "WEBSITE"
    assert adset["targeting"]["geo_locations"]["countries"] == ["KR"]
    assert adset["start_time"].startswith("2026-10-01T00:00:00+09:00")
    study = next(call for call in meta.calls if call[0] == "study")
    assert study[1] == "biz_1"
    assert sum(cell["treatment_percentage"] for cell in study[2]["cells"]) == 100

    saved = CsvTable(path).load_rows()
    assert len({row.meta_ad_id for row in saved if row.meta_ad_id}) == 2
    assert len({row.meta_campaign_id for row in saved}) == 1
    assert saved[0].meta_study_id == saved[1].meta_study_id
    assert saved[0].status == "생성됨"
    assert saved[0].error == ""

    meta.calls.clear()
    meta.create_campaign = lambda payload: (_ for _ in ()).throw(AssertionError("duplicate campaign"))
    second = CsvTable(path)
    again = Runner(
        settings(apply=True),
        meta=meta,
        creatives=LocalCreativeStore(creatives),
        writer=second,
        clock=clock,
    ).run(second.load_rows(), second.parse_issues)
    assert again.ok
    assert meta.calls == []


def test_missing_creative_does_not_create_a_campaign(tmp_path):
    path = tmp_path / "ads.csv"
    write_csv(path, [base_row()])
    table = CsvTable(path)
    meta = FakeMeta()
    report = Runner(
        settings(apply=True, create_split_test=False, meta_business_id=""),
        meta=meta,
        creatives=LocalCreativeStore(tmp_path / "empty"),
        writer=table,
    ).run(table.load_rows(), table.parse_issues)
    assert not report.ok
    assert meta.calls == []
    assert "소재" in CsvTable(path).load_rows()[0].error or "폴더" in CsvTable(path).records[0]["오류"]


def test_conflicting_objectives_block_the_whole_test(tmp_path):
    path = tmp_path / "ads.csv"
    write_csv(
        path,
        [
            base_row(),
            base_row(변형="B", 광고명="여름세일_B", 소재파일="b.png", 목표="인지도"),
        ],
    )
    table = CsvTable(path)
    report = Runner(settings(apply=False)).run(table.load_rows(), table.parse_issues)
    assert not report.ok
    assert sum(1 for item in report.results if not item.ok) == 2


def test_video_without_thumbnail_uses_a_generated_frame(tmp_path, monkeypatch):
    path = tmp_path / "ads.csv"
    creatives = tmp_path / "creatives"
    creatives.mkdir()
    (creatives / "clip.mp4").write_bytes(b"video-bytes")
    write_csv(path, [base_row(소재파일="clip.mp4", 썸네일파일="")])
    monkeypatch.setattr("ab_test.runner.jpeg_thumbnail", lambda data, filename: b"jpeg-frame")
    table = CsvTable(path)
    meta = FakeMeta()
    report = Runner(
        settings(apply=True, create_split_test=False, meta_business_id=""),
        meta=meta,
        creatives=LocalCreativeStore(creatives),
        writer=table,
    ).run(table.load_rows(), table.parse_issues)
    assert report.ok, report.results
    assert ("video", "clip.mp4", "video/mp4") in [(call[0], call[1], call[2]) for call in meta.calls if call[0] == "video"]
    assert any(call[0] == "image" and call[1] == "clip.jpg" for call in meta.calls)


def test_pause_and_activate_guard(tmp_path):
    path = tmp_path / "ads.csv"
    write_csv(
        path,
        [
            base_row(동작="일시중지", 캠페인ID="c1", 광고세트ID="s1", 광고ID="a1"),
            base_row(변형="B", 광고명="여름세일_B", 동작="게시", 캠페인ID="c1", 광고세트ID="s2", 광고ID="a2"),
        ],
    )
    table = CsvTable(path)
    meta = FakeMeta()
    blocked = Runner(settings(apply=True), meta=meta, writer=table).run(table.load_rows(), table.parse_issues)
    assert not blocked.ok
    assert [call for call in meta.calls if call[0] == "status"] == [
        ("status", "s1", "PAUSED"),
        ("status", "a1", "PAUSED"),
    ]

    meta.calls.clear()
    table = CsvTable(path)
    allowed = Runner(settings(apply=True, allow_active=True), meta=meta, writer=table).run(
        table.load_rows(), table.parse_issues
    )
    statuses = [call for call in meta.calls if call[0] == "status"]
    assert ("status", "s2", "ACTIVE") in statuses
    assert ("status", "a2", "ACTIVE") in statuses
    assert ("status", "c1", "ACTIVE") in statuses
    assert allowed.results[-1].ok


def test_blank_page_id_uses_the_env_value(tmp_path):
    path = tmp_path / "ads.csv"
    creatives = tmp_path / "creatives"
    creatives.mkdir()
    (creatives / "a.png").write_bytes(b"png")
    write_csv(path, [base_row(페이지ID="")])
    table = CsvTable(path)
    meta = FakeMeta()
    report = Runner(
        settings(apply=True, create_split_test=False, meta_business_id=""),
        meta=meta,
        creatives=LocalCreativeStore(creatives),
        writer=table,
    ).run(table.load_rows(), table.parse_issues)
    assert report.ok, report.results
    adset = next(call[1] for call in meta.calls if call[0] == "adset")
    assert adset["promoted_object"] == {"page_id": "page_1"}
    assert not any(call[0] == "study" for call in meta.calls)


def test_sales_requires_pixel(tmp_path):
    path = tmp_path / "ads.csv"
    write_csv(path, [base_row(목표="매출")])
    table = CsvTable(path)
    report = Runner(settings()).run(table.load_rows(), table.parse_issues)
    assert not report.ok
    assert "픽셀" in report.results[0].message


def test_cli_runs_only_the_named_test(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.delenv("META_BUSINESS_ID", raising=False)
    path = tmp_path / "ads.csv"
    other = base_row(테스트명="겨울세일", 변형="A", 캠페인명="겨울세일_AB", 광고명="겨울세일_A", 소재파일="winter.png")
    write_csv(path, [base_row(), base_row(변형="B", 광고명="여름세일_B", 소재파일="b.png"), other])
    code = main(["run", "--sheet", str(path), "--test", "겨울세일"])
    assert code == 0
    output = capsys.readouterr().out
    assert "겨울세일_AB" in output
    assert "여름세일_AB" not in output


def test_cli_rejects_an_unknown_test_name(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    path = tmp_path / "ads.csv"
    write_csv(path, [base_row()])
    code = main(["run", "--sheet", str(path), "--test", "없는실험"])
    assert code == 2
    assert "없는실험" in capsys.readouterr().out


def test_cli_dry_run_on_template(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.delenv("META_BUSINESS_ID", raising=False)
    output = tmp_path / "plan.json"
    code = main(["run", "--sheet", "examples/ads_template.csv", "--output", str(output)])
    assert code == 0
    saved = output.read_text(encoding="utf-8")
    assert "여름세일_AB" in saved
