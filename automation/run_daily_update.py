import os
import shutil
import subprocess
import sys
import argparse
import sqlite3
from pathlib import Path

from init_culture_db import DB_PATH, OUTPUTS_DIR, initialize_database


REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_INDEX = REPO_ROOT / "public" / "index.html"
BUILD_SCRIPT = REPO_ROOT / "tools" / "build-protected-site.js"
VERIFY_SCRIPT = REPO_ROOT / "tools" / "verify-protected-site.js"
CARD_HTML = OUTPUTS_DIR / "culture-card-gallery.html"
RECOMMENDATION_HTML = OUTPUTS_DIR / "keyword-recommendation-report.html"
CLOUD_REPORT = OUTPUTS_DIR / "weekly-culture-update-report.md"


def run(command, cwd=None):
    print("+ " + " ".join(str(part) for part in command))
    subprocess.run(command, cwd=cwd, check=True)


def node_command():
    found = shutil.which("node")
    if found:
        return found
    bundled = (
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "node"
        / "bin"
        / ("node.exe" if os.name == "nt" else "node")
    )
    if bundled.exists():
        return str(bundled)
    raise FileNotFoundError("Node.js executable was not found")


def require_password():
    if not os.environ.get("CULTURE_ALERT_SITE_PASSWORD"):
        raise RuntimeError(
            "CULTURE_ALERT_SITE_PASSWORD secret is required to build the protected site."
        )


def selected_sources(scraper):
    configured = os.environ.get("CULTURE_ALERT_SOURCES", "").strip()
    if configured:
        return [item.strip() for item in configured.split(",") if item.strip()]
    sources = sorted(scraper.SCRAPERS)
    if os.environ.get("CULTURE_ALERT_INCLUDE_OFFICIAL_MONITOR") != "1":
        sources = [source for source in sources if source != "official-page-monitor"]
    return sources


def run_collection_and_render():
    sys.path.insert(0, str(OUTPUTS_DIR))
    import culture_alert_scraper as scraper
    import culture_card_gallery
    import culture_keyword_tagger
    from priority_seoul_scrapers import reconcile_priority_events
    from refresh_event_statuses import refresh_statuses

    source_names = selected_sources(scraper)
    results = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        scraper.ensure_schema(conn)
        for name in source_names:
            try:
                events = scraper.SCRAPERS[name]()
                inserted, updated = scraper.upsert_events(conn, events)
                ended = reconcile_priority_events(conn, name, events)
                results.append(
                    {
                        "source": name,
                        "fetched": len(events),
                        "inserted": inserted,
                        "updated": updated,
                        "ended": ended,
                        "error": "",
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "source": name,
                        "fetched": 0,
                        "inserted": 0,
                        "updated": 0,
                        "ended": 0,
                        "error": str(exc),
                    }
                )

    status_updated, status_counts = refresh_statuses(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        summary = culture_keyword_tagger.tag_events(conn)
        scored = culture_keyword_tagger.score_recommendations(
            conn, culture_keyword_tagger.DEFAULT_PERSON
        )
        culture_keyword_tagger.write_report(
            summary, scored, culture_keyword_tagger.DEFAULT_PERSON
        )
    total_cards, counts = culture_card_gallery.render()
    shutil.copyfile(CARD_HTML, RECOMMENDATION_HTML)
    write_cloud_report(results, status_updated, status_counts, total_cards, counts, scored)


def write_cloud_report(results, status_updated, status_counts, total_cards, counts, scored):
    lines = [
        "# 클라우드 문화 일정 업데이트 리포트",
        "",
        f"- 실행 수집기: {len(results)}개",
        f"- 실패 수집기: {sum(1 for item in results if item['error'])}개",
        f"- 상태 갱신: {status_updated}건",
        f"- 카드 재생성: {total_cards}건",
        f"- 추천 점수 반영: {len([item for item in scored if item[0] > 0])}건",
        f"- 공식 페이지 모니터: {'포함' if os.environ.get('CULTURE_ALERT_INCLUDE_OFFICIAL_MONITOR') == '1' else '제외'}",
        "",
        "## 수집기별 결과",
        "",
    ]
    for item in results:
        if item["error"]:
            lines.append(f"- {item['source']}: 실패 - {item['error']}")
        else:
            lines.append(
                f"- {item['source']}: 발견 {item['fetched']}건, 신규 {item['inserted']}건, "
                f"갱신 {item['updated']}건, 종료 정리 {item['ended']}건"
            )
    lines.extend(["", "## 상태별 일정 수", ""])
    for status, count in sorted(status_counts.items()):
        lines.append(f"- {status}: {count}건")
    lines.extend(["", "## 카드 유형", ""])
    for content_type, count in counts.items():
        lines.append(f"- {content_type}: {count}건")
    CLOUD_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(description="Run cloud culture-alert update")
    parser.add_argument("--output", type=Path, default=PUBLIC_INDEX)
    parser.add_argument(
        "--skip-collection",
        action="store_true",
        help="Only encrypt an already existing keyword-recommendation-report.html",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    require_password()
    output_path = args.output.resolve()

    if not args.skip_collection:
        # Keep the last successful rows so a temporary source failure does not
        # erase an institution from the report. Status refresh handles expiry.
        initialize_database(reset=False)
        run_collection_and_render()
        run([sys.executable, "culture_data_audit.py"], cwd=OUTPUTS_DIR)
        run(
            [sys.executable, "official_facility_directory.py", "--from-csv", "--audit-only"],
            cwd=OUTPUTS_DIR,
        )
        run([sys.executable, "institution_coverage_audit.py"], cwd=OUTPUTS_DIR)
        run([sys.executable, "culture_ui_audit.py"], cwd=OUTPUTS_DIR)

        if os.environ.get("RUN_IMAGE_AUDIT") == "1":
            run([sys.executable, "culture_image_audit.py"], cwd=OUTPUTS_DIR)

        if CARD_HTML.exists():
            shutil.copyfile(CARD_HTML, RECOMMENDATION_HTML)
    if not RECOMMENDATION_HTML.exists():
        raise FileNotFoundError(f"final report not found: {RECOMMENDATION_HTML}")

    run(
        [
            node_command(),
            str(BUILD_SCRIPT),
            "--input",
            str(RECOMMENDATION_HTML),
            "--output",
            str(output_path),
        ],
        cwd=REPO_ROOT,
    )
    run(
        [
            node_command(),
            str(VERIFY_SCRIPT),
            "--html",
            str(output_path),
            "--leak",
            "국립중앙박물관",
            "--leak",
            "feature-card",
        ],
        cwd=REPO_ROOT,
    )

    print(f"db={DB_PATH}")
    print(f"encrypted_html={output_path}")


if __name__ == "__main__":
    main()
