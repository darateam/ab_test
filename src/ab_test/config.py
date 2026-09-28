from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class Settings:
    meta_access_token: str
    meta_ad_account_id: str
    meta_page_id: str
    meta_business_id: str
    meta_api_version: str
    google_sheet_id: str
    google_sheet_range: str
    google_drive_folder_id: str
    google_service_account_file: str
    google_oauth_client_secrets: str
    google_oauth_token_file: str
    sheet_path: str
    creatives_dir: str
    create_split_test: bool
    timezone: str
    apply: bool = False
    allow_active: bool = False

    @property
    def uses_google_sheet(self) -> bool:
        return bool(self.google_sheet_id)

    @property
    def uses_google_drive(self) -> bool:
        return bool(self.google_drive_folder_id)


def load_settings() -> Settings:
    load_dotenv()
    business_id = os.getenv("META_BUSINESS_ID", "").strip()
    return Settings(
        meta_access_token=os.getenv("META_ACCESS_TOKEN", "").strip(),
        meta_ad_account_id=os.getenv("META_AD_ACCOUNT_ID", "").strip(),
        meta_page_id=os.getenv("META_PAGE_ID", "").strip(),
        meta_business_id=business_id,
        meta_api_version=os.getenv("META_API_VERSION", "v25.0").strip() or "v25.0",
        google_sheet_id=os.getenv("GOOGLE_SHEET_ID", "").strip(),
        google_sheet_range=os.getenv("GOOGLE_SHEET_RANGE", "").strip(),
        google_drive_folder_id=os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip(),
        google_service_account_file=os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip(),
        google_oauth_client_secrets=os.getenv("GOOGLE_OAUTH_CLIENT_SECRETS", "").strip(),
        google_oauth_token_file=os.getenv("GOOGLE_OAUTH_TOKEN_FILE", "token.json").strip(),
        sheet_path=os.getenv("SHEET_PATH", "").strip(),
        creatives_dir=os.getenv("CREATIVES_DIR", "").strip(),
        create_split_test=_flag("CREATE_SPLIT_TEST", bool(business_id)),
        timezone=os.getenv("TIMEZONE", "Asia/Seoul").strip() or "Asia/Seoul",
    )


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]
