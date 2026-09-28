from __future__ import annotations

import csv
import io
import json
import urllib.request
from pathlib import Path

from ab_test.google_io import spreadsheet_id
from ab_test.sheet import TableStore


class PublicGoogleSheet(TableStore):
    """링크가 열린 구글 시트를 읽고, 생성된 ID는 로컬 상태에 기억합니다."""

    def __init__(self, spreadsheet_id_value: str, fieldnames: list[str], records: list[dict[str, str]], state_path: Path):
        super().__init__(fieldnames, records)
        self.spreadsheet_id = spreadsheet_id_value
        self.state_path = state_path
        self._overlay_state()

    def persist_fields(self, row_number: int, fields: tuple[str, ...]) -> None:
        del row_number, fields
        payload = {}
        for index, record in enumerate(self.records):
            number = str(index + 2)
            payload[number] = {
                field: record.get(self.header_for(field), "")
                for field in self._canonical
                if field in {
                    "status",
                    "meta_campaign_id",
                    "meta_adset_id",
                    "meta_creative_id",
                    "meta_ad_id",
                    "meta_study_id",
                    "error",
                }
            }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _overlay_state(self) -> None:
        if not self.state_path.is_file():
            return
        saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        for number, fields in saved.items():
            if not str(number).isdigit():
                continue
            row_number = int(number)
            if row_number < 2 or row_number - 2 >= len(self.records):
                continue
            self._put(row_number, {key: str(value) for key, value in fields.items()})


def open_public_google_sheet(spreadsheet: str, state_dir: Path | None = None) -> PublicGoogleSheet:
    sheet_id = spreadsheet_id(spreadsheet)
    request = urllib.request.Request(
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv",
        headers={"User-Agent": "ab-test"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read().decode("utf-8-sig")
    return table_from_csv_text(sheet_id, text, state_dir or Path(".ab-test-state"))


def table_from_csv_text(sheet_id: str, text: str, state_dir: Path) -> PublicGoogleSheet:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("구글 시트에 헤더 행이 없습니다.")
    records = [dict(row) for row in reader]
    return PublicGoogleSheet(sheet_id, list(reader.fieldnames), records, state_dir / f"{sheet_id}.json")
