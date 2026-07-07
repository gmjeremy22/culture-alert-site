import sqlite3
from datetime import date, datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "culture-alert.sqlite"

ENDED = "종료"
ONGOING = "진행중"
UPCOMING = "예정"
PERMANENT = "상설전시"


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def infer_status(start_date, end_date, current_status, today):
    if current_status == PERMANENT:
        return PERMANENT
    if not start_date and not end_date:
        return PERMANENT
    start = parse_date(start_date)
    end = parse_date(end_date)
    if end and end < today:
        return ENDED
    if start and start > today:
        return UPCOMING
    return ONGOING


def refresh_statuses(db_path=DEFAULT_DB, today=None):
    today = today or date.today()
    updated = 0
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, start_date, end_date, status FROM cultural_events"
        ).fetchall()
        for event_id, start_date, end_date, status in rows:
            new_status = infer_status(start_date, end_date, status, today)
            if new_status == status:
                continue
            conn.execute(
                """
                UPDATE cultural_events
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (new_status, event_id),
            )
            updated += 1
        conn.commit()
        counts = dict(
            conn.execute(
                "SELECT status, COUNT(*) FROM cultural_events GROUP BY status"
            ).fetchall()
        )
    return updated, counts


def main():
    updated, counts = refresh_statuses()
    print(f"status_updated={updated}")
    for status in (ONGOING, UPCOMING, PERMANENT, ENDED):
        print(f"{status}={counts.get(status, 0)}")


if __name__ == "__main__":
    main()
