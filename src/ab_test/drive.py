from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

DRIVE_URL_ID = re.compile(r"/d/([A-Za-z0-9_-]+)")
DRIVE_FOLDER_URL = re.compile(r"/folders/([A-Za-z0-9_-]+)")
DRIVE_QUERY_ID = re.compile(r"[?&]id=([A-Za-z0-9_-]+)")
DRIVE_FILE_ID = re.compile(r"^[A-Za-z0-9_-]{25,}$")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".m4v")


class DriveError(RuntimeError):
    pass


@dataclass
class CreativeBlob:
    name: str
    data: bytes
    mime: str

    @property
    def is_video(self) -> bool:
        if self.mime.startswith("video/"):
            return True
        return self.name.lower().endswith(VIDEO_EXTENSIONS)


def parse_drive_ref(ref: str) -> tuple[str, str]:
    """파일 참조를 ('id', 파일ID) 또는 ('name', 파일명)으로 나눕니다."""
    text = ref.strip()
    url_match = DRIVE_URL_ID.search(text) or DRIVE_FOLDER_URL.search(text) or DRIVE_QUERY_ID.search(text)
    if url_match:
        return "id", url_match.group(1)
    if DRIVE_FILE_ID.match(text):
        return "id", text
    return "name", text


class LocalCreativeStore:
    def __init__(self, folder: Path):
        self.folder = folder

    def fetch(self, ref: str) -> CreativeBlob:
        kind, value = parse_drive_ref(ref)
        if kind == "id":
            raise DriveError(
                "로컬 소재 폴더에서는 드라이브 파일 ID를 열 수 없습니다. "
                "파일명을 쓰거나 GOOGLE_DRIVE_FOLDER_ID를 설정하세요."
            )
        path = self._find(value)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return CreativeBlob(path.name, path.read_bytes(), mime)

    def _find(self, name: str) -> Path:
        direct = self.folder / name
        if direct.is_file():
            return direct
        if not self.folder.is_dir():
            raise DriveError(f"소재 폴더가 없습니다: {self.folder}")
        matches = [path for path in self.folder.iterdir() if path.is_file() and path.name.lower() == name.lower()]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise DriveError(f"소재 파일을 찾지 못했습니다: {name}")
        raise DriveError(f"같은 이름의 소재 파일이 여러 개입니다: {name}")
