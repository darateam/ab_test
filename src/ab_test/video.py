from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def jpeg_thumbnail(data: bytes, filename: str) -> bytes:
    """동영상 첫 장면을 JPEG으로 뽑습니다. 썸네일 파일을 따로 두지 않아도 됩니다."""
    if shutil.which("ffmpeg") is None:
        raise ValueError("동영상을 쓰려면 ffmpeg가 필요하거나 썸네일파일 열에 이미지를 지정하세요.")
    suffix = Path(filename).suffix if Path(filename).suffix else ".mp4"
    with tempfile.TemporaryDirectory() as temporary:
        source = Path(temporary) / f"source{suffix}"
        image = Path(temporary) / "thumb.jpg"
        source.write_bytes(data)
        completed = subprocess.run(
            ["ffmpeg", "-y", "-i", str(source), "-ss", "0", "-frames:v", "1", str(image)],
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0 or not image.is_file():
            detail = completed.stderr.decode("utf-8", errors="replace")[-300:]
            raise ValueError(f"동영상에서 썸네일을 만들지 못했습니다. {detail}".strip())
        return image.read_bytes()
