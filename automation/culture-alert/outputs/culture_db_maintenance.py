import shutil
import sqlite3
from pathlib import Path
from urllib.error import URLError

from culture_image_utils import MIN_IMAGE_SIDE, clean_image_url, is_small_remote_image


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "culture-alert.sqlite"
REPORT_PATH = BASE_DIR / "db-maintenance-report.md"
BACKUP_PATH = BASE_DIR / "culture-alert.before-maintenance.sqlite"


DEPENDENT_EVENT_TABLES = (
    "event_occurrences",
    "event_keywords",
    "recommendations",
    "related_links",
)


def table_exists(conn, table_name):
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
    )


def create_indexes(conn):
    statements = [
        "CREATE INDEX IF NOT EXISTS idx_recommendations_event_person ON recommendations(event_id, person_name)",
        "CREATE INDEX IF NOT EXISTS idx_recommendations_person_score ON recommendations(person_name, score DESC)",
        "CREATE INDEX IF NOT EXISTS idx_events_source_url ON cultural_events(source_url)",
        "CREATE INDEX IF NOT EXISTS idx_events_title ON cultural_events(title)",
        "CREATE INDEX IF NOT EXISTS idx_event_candidates_institution ON event_candidates(institution_name)",
        "CREATE INDEX IF NOT EXISTS idx_event_candidates_dates ON event_candidates(start_date, end_date)",
    ]
    created_or_confirmed = 0
    for statement in statements:
        conn.execute(statement)
        created_or_confirmed += 1
    return created_or_confirmed


def cleanup_orphans(conn):
    removed = {}
    for table in DEPENDENT_EVENT_TABLES:
        if not table_exists(conn, table):
            continue
        cursor = conn.execute(
            f"""
            DELETE FROM {table}
            WHERE event_id NOT IN (SELECT id FROM cultural_events)
            """
        )
        removed[table] = cursor.rowcount
    return removed


def cleanup_images(conn):
    removed = 0
    skipped_size_checks = 0
    rows = conn.execute(
        """
        SELECT id, image_url
        FROM cultural_events
        WHERE image_url IS NOT NULL
          AND TRIM(image_url) != ''
        """
    ).fetchall()
    for event_id, image_url in rows:
        cleaned = clean_image_url(image_url)
        should_clear = cleaned is None
        if cleaned and not should_clear:
            try:
                should_clear = is_small_remote_image(cleaned, min_side=MIN_IMAGE_SIDE)
            except (OSError, UnicodeError, URLError, TimeoutError):
                skipped_size_checks += 1
                should_clear = False
        if should_clear:
            conn.execute(
                """
                UPDATE cultural_events
                SET image_url = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (event_id,),
            )
            removed += 1
    return removed, skipped_size_checks


def integrity_check(conn):
    return [row[0] for row in conn.execute("PRAGMA integrity_check").fetchall()]


def counts(conn):
    table_names = (
        "institutions",
        "cultural_events",
        "event_keywords",
        "recommendations",
        "event_occurrences",
        "related_links",
    )
    return {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in table_names
        if table_exists(conn, table)
    }


def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(DB_PATH)
    shutil.copyfile(DB_PATH, BACKUP_PATH)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        before = counts(conn)
        index_count = create_indexes(conn)
        orphan_removed = cleanup_orphans(conn)
        images_removed, image_size_skipped = cleanup_images(conn)
        conn.execute("PRAGMA optimize")
        conn.commit()
        integrity = integrity_check(conn)
        after = counts(conn)

    lines = [
        "# DB 유지보수 리포트",
        "",
        f"- 백업: {BACKUP_PATH}",
        f"- 인덱스 확인/추가: {index_count}개",
        f"- 이상 이미지 정리: {images_removed}건",
        f"- 이미지 크기 확인 보류: {image_size_skipped}건",
        f"- 무결성 검사: {', '.join(integrity)}",
        "",
        "## 고아 데이터 정리",
        "",
    ]
    for table, removed in orphan_removed.items():
        lines.append(f"- {table}: {removed}건")
    lines.extend(["", "## 테이블 건수", ""])
    for table in sorted(after):
        lines.append(f"- {table}: {before.get(table, 0)} -> {after[table]}")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"indexes={index_count}")
    print(f"images_removed={images_removed}")
    print(f"integrity={','.join(integrity)}")
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
