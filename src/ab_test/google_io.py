from __future__ import annotations

import io
import re
from pathlib import Path

from ab_test.config import Settings
from ab_test.drive import CreativeBlob, DriveError, parse_drive_ref
from ab_test.sheet import TableStore, column_letter, quote_sheet_title

SHEET_URL = re.compile(r"/spreadsheets/d/([A-Za-z0-9-_]+)")


def spreadsheet_id(raw: str) -> str:
    match = SHEET_URL.search(raw)
    if match:
        return match.group(1)
    return raw.strip()


SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
)


def build_credentials(settings: Settings):
    if settings.google_service_account_file:
        from google.oauth2 import service_account

        path = Path(settings.google_service_account_file)
        if not path.is_file():
            raise DriveError(f"서비스 계정 파일이 없습니다: {path}")
        return service_account.Credentials.from_service_account_file(str(path), scopes=SCOPES)

    token_path = Path(settings.google_oauth_token_file)
    if token_path.is_file():
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(str(token_path), list(SCOPES))
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    raise DriveError(
        "구글 인증이 없습니다. GOOGLE_SERVICE_ACCOUNT_FILE을 지정하거나 "
        "`ab-test auth-google`로 token.json을 만드세요."
    )


def _sheets(creds):
    from googleapiclient.discovery import build

    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _drive(creds):
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def resolve_sheet_range(service, settings: Settings) -> tuple[str, str]:
    meta = (
        service.spreadsheets()
        .get(spreadsheetId=settings.google_sheet_id, fields="sheets.properties.title")
        .execute()
    )
    sheets = meta.get("sheets") or []
    if not sheets:
        raise DriveError("구글 스프레드시트에 시트가 없습니다.")
    first = sheets[0]["properties"]["title"]
    raw = settings.google_sheet_range
    if not raw:
        return first, f"{quote_sheet_title(first)}!A:AZ"
    if "!" in raw:
        title = raw.split("!", 1)[0].strip().strip("'")
        return title, raw
    return first, f"{quote_sheet_title(first)}!{raw}"


class GoogleSheetTable(TableStore):
    def __init__(self, service, spreadsheet_id: str, sheet_title: str, fieldnames: list[str], records: list[dict[str, str]]):
        super().__init__(fieldnames, records)
        self.service = service
        self.spreadsheet_id = spreadsheet_id
        self.sheet_title = sheet_title

    def persist_fields(self, row_number: int, fields: tuple[str, ...]) -> None:
        record = self.records[row_number - 2]
        data = []
        for field in fields:
            column = self._canonical.index(field) + 1
            cell = f"{quote_sheet_title(self.sheet_title)}!{column_letter(column)}{row_number}"
            data.append({"range": cell, "values": [[record.get(self.header_for(field), "")]]})
        (
            self.service.spreadsheets()
            .values()
            .batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"valueInputOption": "RAW", "data": data},
            )
            .execute()
        )


def open_google_sheet(settings: Settings) -> GoogleSheetTable:
    settings.google_sheet_id = spreadsheet_id(settings.google_sheet_id)
    creds = build_credentials(settings)
    service = _sheets(creds)
    title, range_name = resolve_sheet_range(service, settings)
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=settings.google_sheet_id, range=range_name)
        .execute()
    )
    values = result.get("values") or []
    if not values:
        raise DriveError("구글 시트가 비어 있습니다.")
    headers = [str(cell) for cell in values[0]]
    records = []
    width = len(headers)
    for raw in values[1:]:
        padded = [str(cell) for cell in raw] + [""] * (width - len(raw))
        records.append({headers[index]: padded[index] for index in range(width)})
    return GoogleSheetTable(service, settings.google_sheet_id, title, headers, records)


class GoogleCreativeStore:
    def __init__(self, service, folder_id: str):
        self.service = service
        kind, value = parse_drive_ref(folder_id)
        self.folder_id = value if kind == "id" else folder_id

    def fetch(self, ref: str) -> CreativeBlob:
        kind, value = parse_drive_ref(ref)
        file_id = value if kind == "id" else self._find_id(value)
        meta = (
            self.service.files()
            .get(fileId=file_id, fields="id,name,mimeType", supportsAllDrives=True)
            .execute()
        )
        mime = meta.get("mimeType") or "application/octet-stream"
        if mime.startswith("application/vnd.google-apps."):
            raise DriveError(f"구글 문서 형식은 소재로 쓸 수 없습니다: {meta.get('name')}")
        return CreativeBlob(meta.get("name") or file_id, _download(self.service, file_id), mime)

    def _find_id(self, name: str) -> str:
        escaped = name.replace("\\", "\\\\").replace("'", "\\'")
        query = f"name = '{escaped}' and '{self.folder_id}' in parents and trashed = false"
        result = (
            self.service.files()
            .list(
                q=query,
                fields="files(id,name)",
                pageSize=10,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = result.get("files") or []
        if not files:
            raise DriveError(f"드라이브 폴더에서 소재를 찾지 못했습니다: {name}")
        if len(files) > 1:
            raise DriveError(f"드라이브 폴더에 같은 이름의 소재가 여러 개입니다: {name}")
        return files[0]["id"]


def open_google_creatives(settings: Settings) -> GoogleCreativeStore:
    creds = build_credentials(settings)
    return GoogleCreativeStore(_drive(creds), settings.google_drive_folder_id)


def _download(service, file_id: str) -> bytes:
    from googleapiclient.http import MediaIoBaseDownload

    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


def authorize_user(settings: Settings) -> Path:
    if not settings.google_oauth_client_secrets:
        raise DriveError("GOOGLE_OAUTH_CLIENT_SECRETS 경로가 필요합니다.")
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(settings.google_oauth_client_secrets, list(SCOPES))
    creds = flow.run_local_server(port=0)
    destination = Path(settings.google_oauth_token_file)
    destination.write_text(creds.to_json(), encoding="utf-8")
    return destination
