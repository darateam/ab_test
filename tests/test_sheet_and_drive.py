from ab_test.drive import parse_drive_ref
from ab_test.google_io import GoogleSheetTable, spreadsheet_id
from ab_test.sheet import CsvTable, column_letter, quote_sheet_title


def test_korean_headers_and_aliases(tmp_path):
    path = tmp_path / "ads.csv"
    path.write_text(
        "\ufeff테스트명,변형,동작,목표,일예산,국가,기본문구,제목,링크,버튼,소재파일\n"
        "봄,A,생성,매출,\"10,000\",한국,문구,제목,https://shop.example,구매하기,a.png\n"
        "봄,B,게시,트래픽,1000,US,문구,제목,https://shop.example,더 알아보기,b.png\n",
        encoding="utf-8",
    )
    table = CsvTable(path)
    rows = table.load_rows()
    assert rows[0].objective == "OUTCOME_SALES"
    assert rows[0].daily_budget == 10000
    assert rows[0].countries == ["KR"]
    assert rows[0].cta == "SHOP_NOW"
    assert rows[0].action == "create"
    assert rows[1].action == "activate"
    assert rows[1].objective == "OUTCOME_TRAFFIC"


def test_bad_budget_is_a_row_issue(tmp_path):
    path = tmp_path / "ads.csv"
    path.write_text("테스트명,일예산\n봄,많음\n", encoding="utf-8-sig")
    table = CsvTable(path)
    assert table.load_rows() == []
    assert table.parse_issues[0].row_number == 2
    assert "일예산" in table.parse_issues[0].message


class _Values:
    def __init__(self):
        self.body = None
        self.spreadsheet_id = None

    def batchUpdate(self, spreadsheetId, body):
        self.spreadsheet_id = spreadsheetId
        self.body = body
        return self

    def execute(self):
        return {}


class _Sheets:
    def __init__(self):
        self._values = _Values()

    def spreadsheets(self):
        return self

    def values(self):
        return self._values


def test_google_sheet_writes_result_columns_by_header_name():
    service = _Sheets()
    table = GoogleSheetTable(service, "sheet123", "광고", ["테스트명", "상태", "오류"], [{"테스트명": "봄", "상태": "", "오류": ""}])
    table.mark_error(2, "페이지 ID가 필요합니다.")
    ranges = {item["range"]: item["values"][0][0] for item in service._values.body["data"]}
    assert service._values.spreadsheet_id == "sheet123"
    assert ranges["'광고'!B2"] == "오류"
    assert ranges["'광고'!C2"] == "페이지 ID가 필요합니다."


def test_column_letter_and_sheet_names():
    assert column_letter(1) == "A"
    assert column_letter(26) == "Z"
    assert column_letter(27) == "AA"
    assert quote_sheet_title("A's") == "'A''s'"


def test_drive_and_sheet_refs():
    assert parse_drive_ref("https://drive.google.com/file/d/abcDEF_1234567890abcd/view") == (
        "id",
        "abcDEF_1234567890abcd",
    )
    assert parse_drive_ref("https://drive.google.com/drive/folders/folder1234567890abcdef") == (
        "id",
        "folder1234567890abcdef",
    )
    assert parse_drive_ref("summer_a.png") == ("name", "summer_a.png")
    assert spreadsheet_id("https://docs.google.com/spreadsheets/d/sheet123/edit#gid=0") == "sheet123"
    assert spreadsheet_id("sheet123") == "sheet123"
