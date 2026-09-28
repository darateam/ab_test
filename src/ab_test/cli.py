from __future__ import annotations

import argparse
import json
from pathlib import Path

from ab_test.config import Settings, load_settings
from ab_test.drive import DriveError, LocalCreativeStore
from ab_test.meta import MetaApiError, MetaClient
from ab_test.runner import Runner
from ab_test.sheet import CsvTable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ab-test",
        description="구글 드라이브의 광고 시트를 읽어 Meta 광고 A/B 테스트를 만듭니다.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="시트를 읽고 광고를 만들거나 상태를 바꿉니다.")
    run.add_argument("--apply", action="store_true", help="Meta에 실제로 반영합니다. 없으면 미리보기만 합니다.")
    run.add_argument(
        "--allow-active",
        action="store_true",
        help="동작이 게시인 행만 실제로 켭니다. 광고비가 지출될 수 있습니다.",
    )
    run.add_argument("--sheet", help="로컬 CSV 경로. 지정하면 구글 시트 대신 이 파일을 읽습니다.")
    run.add_argument("--creatives", help="로컬 소재 폴더. 지정하면 드라이브 폴더 대신 사용합니다.")
    run.add_argument("--output", help="실행 결과를 저장할 JSON 경로")

    sub.add_parser("auth-google", help="내 구글 드라이브용 OAuth 토큰을 저장합니다.")

    args = parser.parse_args(argv)
    settings = load_settings()
    try:
        if args.command == "auth-google":
            from ab_test.google_io import authorize_user

            path = authorize_user(settings)
            print(f"구글 토큰을 저장했습니다: {path}")
            return 0
        return _run(settings, args)
    except (MetaApiError, DriveError, OSError, ValueError) as exc:
        print(f"오류: {exc}")
        return 2


def _run(settings: Settings, args) -> int:
    if args.sheet:
        settings.google_sheet_id = ""
        settings.sheet_path = args.sheet
    if args.creatives:
        settings.google_drive_folder_id = ""
        settings.creatives_dir = args.creatives
    settings.apply = bool(args.apply)
    settings.allow_active = bool(args.allow_active)

    table = _open_table(settings)
    rows = table.load_rows()
    creatives = _open_creatives(settings) if settings.apply else None
    meta = _open_meta(settings) if settings.apply else None
    report = Runner(settings, meta=meta, creatives=creatives, writer=table).run(rows, table.parse_issues)

    for line in report.plan_lines:
        print(line)
    failures = [item for item in report.results if not item.ok]
    successes = [item for item in report.results if item.ok]
    for item in report.results:
        state = "성공" if item.ok else "실패"
        prefix = f"{item.row_number}행" if item.row_number else "시트"
        print(f"{state} {prefix}: {item.message}")
    print(f"완료: 성공 {len(successes)}건, 실패 {len(failures)}건")
    if args.output:
        destination = Path(args.output)
        destination.write_text(
            json.dumps(
                {
                    "dry_run": report.dry_run,
                    "ok": report.ok,
                    "plan": report.plan_lines,
                    "results": [
                        {"row": item.row_number, "ok": item.ok, "message": item.message} for item in report.results
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0 if report.ok else 2


def _open_table(settings: Settings):
    if settings.uses_google_sheet:
        from ab_test.google_io import open_google_sheet

        return open_google_sheet(settings)
    if not settings.sheet_path:
        raise ValueError("GOOGLE_SHEET_ID 또는 SHEET_PATH가 필요합니다.")
    path = Path(settings.sheet_path)
    if not path.is_file():
        raise ValueError(f"시트 파일이 없습니다: {path}")
    return CsvTable(path)


def _open_creatives(settings: Settings):
    if settings.uses_google_drive:
        from ab_test.google_io import open_google_creatives

        return open_google_creatives(settings)
    if settings.creatives_dir:
        return LocalCreativeStore(Path(settings.creatives_dir))
    return None


def _open_meta(settings: Settings):
    if settings.meta_transport == "graph":
        return MetaClient(
            settings.meta_access_token,
            settings.meta_ad_account_id,
            settings.meta_api_version,
        )
    from ab_test.mcp_ads import McpAds

    return McpAds(
        settings.meta_access_token,
        settings.meta_ad_account_id,
        api_version=settings.meta_api_version,
        url=settings.meta_mcp_url,
    )
