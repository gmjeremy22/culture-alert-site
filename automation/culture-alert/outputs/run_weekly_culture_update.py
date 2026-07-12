import shutil
import sqlite3
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "culture-alert.sqlite"
CARD_HTML = BASE_DIR / "culture-card-gallery.html"
RECOMMENDATION_HTML = BASE_DIR / "keyword-recommendation-report.html"
REPORT_PATH = BASE_DIR / "weekly-culture-update-report.md"

sys.path.insert(0, str(BASE_DIR))

import culture_alert_scraper as scraper
import culture_card_gallery
import culture_keyword_tagger
from culture_db_maintenance import cleanup_images
from refresh_event_statuses import refresh_statuses
from priority_seoul_scrapers import reconcile_priority_events


WEEKLY_SOURCES = sorted(scraper.SCRAPERS)

PROMOTED_B_INSTITUTIONS = [
    "서울생활사박물관",
    "청계천박물관",
    "서울우리소리박물관",
    "실학박물관",
    "전곡선사박물관",
    "경기도어린이박물관",
]

REPLACED_PLACEHOLDER_EVENTS = [
    ("성북구립미술관", "성북구립미술관 전시 일정 모니터"),
]


def cleanup_promoted_backfill_rows(conn):
    removed = 0
    for name in PROMOTED_B_INSTITUTIONS:
        row = conn.execute("SELECT id FROM institutions WHERE name = ?", (name,)).fetchone()
        if not row:
            continue
        event_ids = [
            item[0]
            for item in conn.execute(
                """
                SELECT id
                FROM cultural_events
                WHERE institution_id = ?
                  AND raw_text LIKE 'B등급 보강 수집.%'
                """,
                (row[0],),
            ).fetchall()
        ]
        if not event_ids:
            continue
        placeholders = ",".join("?" for _ in event_ids)
        for table in ("event_occurrences", "event_keywords", "recommendations", "related_links"):
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            if exists:
                conn.execute(f"DELETE FROM {table} WHERE event_id IN ({placeholders})", event_ids)
        cursor = conn.execute(
            f"DELETE FROM cultural_events WHERE id IN ({placeholders})",
            event_ids,
        )
        removed += cursor.rowcount
    for name, title in REPLACED_PLACEHOLDER_EVENTS:
        row = conn.execute("SELECT id FROM institutions WHERE name = ?", (name,)).fetchone()
        if not row:
            continue
        event_ids = [
            item[0]
            for item in conn.execute(
                """
                SELECT id
                FROM cultural_events
                WHERE institution_id = ? AND title = ?
                """,
                (row[0], title),
            ).fetchall()
        ]
        if not event_ids:
            continue
        placeholders = ",".join("?" for _ in event_ids)
        for table in ("event_occurrences", "event_keywords", "recommendations", "related_links"):
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            if exists:
                conn.execute(f"DELETE FROM {table} WHERE event_id IN ({placeholders})", event_ids)
        cursor = conn.execute(
            f"DELETE FROM cultural_events WHERE id IN ({placeholders})",
            event_ids,
        )
        removed += cursor.rowcount
    conn.commit()
    return removed


def run_sources(conn):
    results = []
    scraper.ensure_schema(conn)
    for source_name in WEEKLY_SOURCES:
        try:
            events = scraper.SCRAPERS[source_name]()
            inserted, updated = scraper.upsert_events(conn, events)
            ended = reconcile_priority_events(conn, source_name, events)
            results.append(
                {
                    "source": source_name,
                    "fetched": len(events),
                    "inserted": inserted,
                    "updated": updated,
                    "ended": ended,
                    "error": None,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "source": source_name,
                    "fetched": 0,
                    "inserted": 0,
                    "updated": 0,
                    "ended": 0,
                    "error": str(exc),
                }
            )
    return results


def rebuild_recommendations_and_cards():
    with sqlite3.connect(DB_PATH) as conn:
        summary = culture_keyword_tagger.tag_events(conn)
        scored = culture_keyword_tagger.score_recommendations(
            conn, culture_keyword_tagger.DEFAULT_PERSON
        )
        monitor_count = conn.execute(
            "SELECT COUNT(*) FROM cultural_events WHERE title LIKE '%전시·교육 모니터%'"
        ).fetchone()[0]
        culture_keyword_tagger.write_report(
            summary, scored, culture_keyword_tagger.DEFAULT_PERSON
        )
    total_cards, counts = culture_card_gallery.render()
    shutil.copyfile(CARD_HTML, RECOMMENDATION_HTML)
    return {
        "tagged": len(summary),
        "recommended": len([item for item in scored if item[0] > 0]),
        "cards": total_cards,
        "counts": counts,
        "monitor_excluded": monitor_count,
    }


def write_report(cleaned, image_cleaned, source_results, status_updated, status_counts, render_result):
    lines = [
        "# 주간 문화 일정 업데이트 리포트",
        "",
        f"- 실행 수집기: {len(source_results)}개",
        f"- 승격 B등급 임시 데이터 정리: {cleaned}건",
        f"- 이상 이미지 정리: {image_cleaned}건",
        f"- 상태 갱신: {status_updated}건",
        f"- 카드 재생성: {render_result['cards']}건",
        f"- 추천 점수 반영: {render_result['recommended']}건",
        f"- 자동 모니터: {render_result['monitor_excluded']}건 (추천 카드 제외)",
        "",
        "## 수집기별 결과",
        "",
    ]
    for item in source_results:
        if item.get("error"):
            lines.append(f"- {item['source']}: 실패 - {item['error']}")
        else:
            lines.append(
                f"- {item['source']}: 발견 {item['fetched']}건, 신규 {item['inserted']}건, "
                f"갱신 {item['updated']}건, 종료 정리 {item['ended']}건"
            )
    lines.extend(["", "## 상태별 일정 수", ""])
    for status in ("진행중", "예정", "상설전시", "종료"):
        lines.append(f"- {status}: {status_counts.get(status, 0)}건")
    lines.extend(["", "## 카드 유형", ""])
    for content_type, count in render_result["counts"].items():
        lines.append(f"- {content_type}: {count}건")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cleaned = cleanup_promoted_backfill_rows(conn)
        source_results = run_sources(conn)
        image_cleaned, _image_size_skipped = cleanup_images(conn)
    status_updated, status_counts = refresh_statuses(DB_PATH)
    render_result = rebuild_recommendations_and_cards()
    write_report(cleaned, image_cleaned, source_results, status_updated, status_counts, render_result)

    print(f"sources={len(source_results)}")
    print(f"cleaned_backfill={cleaned}")
    for item in source_results:
        if item.get("error"):
            print(f"{item['source']}: error={item['error']}")
        else:
            print(
                f"{item['source']}: fetched={item['fetched']} inserted={item['inserted']} "
                f"updated={item['updated']} ended={item['ended']}"
            )
    print(f"cards={render_result['cards']}")
    print(f"recommended={render_result['recommended']}")
    print(f"report={REPORT_PATH}")
    print(f"html={RECOMMENDATION_HTML}")


if __name__ == "__main__":
    main()
