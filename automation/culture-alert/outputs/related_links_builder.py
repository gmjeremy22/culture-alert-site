import argparse
import sqlite3
from pathlib import Path
from urllib.parse import quote_plus


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "culture-alert.sqlite"
REPORT_PATH = BASE_DIR / "related-link-report.md"


def ensure_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS related_links (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          event_id INTEGER NOT NULL,
          link_type TEXT NOT NULL,
          title TEXT NOT NULL,
          url TEXT NOT NULL,
          source TEXT NOT NULL,
          rank INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (event_id) REFERENCES cultural_events(id),
          UNIQUE (event_id, link_type, url)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_related_links_event ON related_links(event_id, rank)"
    )


def event_query(title, institution):
    compact_title = " ".join(str(title or "").split())
    compact_institution = " ".join(str(institution or "").split())
    return f"{compact_title} {compact_institution} 후기"


def make_links(event_id, title, institution):
    query = event_query(title, institution)
    encoded = quote_plus(query)
    blog_encoded = quote_plus(query + " 블로그")
    return [
        {
            "event_id": event_id,
            "link_type": "blog_search",
            "title": "네이버 블로그 후기 검색",
            "url": f"https://search.naver.com/search.naver?where=blog&query={blog_encoded}",
            "source": "naver",
            "rank": 10,
        },
        {
            "event_id": event_id,
            "link_type": "web_search",
            "title": "네이버 통합 검색",
            "url": f"https://search.naver.com/search.naver?where=nexearch&query={encoded}",
            "source": "naver",
            "rank": 20,
        },
        {
            "event_id": event_id,
            "link_type": "web_search",
            "title": "Google 후기 검색",
            "url": f"https://www.google.com/search?q={encoded}",
            "source": "google",
            "rank": 30,
        },
    ]


def load_active_events(conn):
    return conn.execute(
        """
        SELECT e.id, e.title, i.name, e.start_date, e.end_date
        FROM cultural_events e
        JOIN institutions i ON i.id = e.institution_id
        WHERE e.status != '종료'
        ORDER BY COALESCE(e.end_date, '9999-12-31'), e.title
        """
    ).fetchall()


def upsert_links(conn, links):
    inserted = 0
    updated = 0
    for link in links:
        exists = conn.execute(
            """
            SELECT 1
            FROM related_links
            WHERE event_id = ? AND link_type = ? AND url = ?
            """,
            (link["event_id"], link["link_type"], link["url"]),
        ).fetchone()
        cursor = conn.execute(
            """
            INSERT INTO related_links (event_id, link_type, title, url, source, rank)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id, link_type, url) DO UPDATE SET
              title=excluded.title,
              source=excluded.source,
              rank=excluded.rank,
              updated_at=CURRENT_TIMESTAMP
            """,
            (
                link["event_id"],
                link["link_type"],
                link["title"],
                link["url"],
                link["source"],
                link["rank"],
            ),
        )
        if cursor.rowcount and exists:
            updated += 1
        elif cursor.rowcount:
            inserted += 1
    conn.commit()
    return inserted, updated


def build_report(events, inserted, updated):
    lines = [
        "# 후기/검색 링크 생성 결과",
        "",
        f"- 대상 전시: {len(events)}건",
        f"- 새로 추가한 링크: {inserted}개",
        f"- 갱신한 링크: {updated}개",
        "",
        "## 방식",
        "",
        "- 각 전시에 대해 네이버 블로그 검색, 네이버 통합 검색, Google 검색 링크를 생성했습니다.",
        "- 이 단계는 검색 결과 링크만 만드는 것이므로 OpenAI API 비용이 들지 않습니다.",
        "- 실제 후기 본문을 모아 요약하려면 별도의 검색 API나 크롤링, 그리고 요약용 OpenAI API를 선택적으로 붙이면 됩니다.",
        "",
        "## 대상 예시",
        "",
    ]
    for event_id, title, institution, start_date, end_date in events[:20]:
        period = f"{start_date or '?'} ~ {end_date or '?'}"
        lines.append(f"- {title} / {institution} / {period}")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="전시별 후기/검색 링크 생성기")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()

    with sqlite3.connect(args.db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        events = load_active_events(conn)
        links = []
        for event_id, title, institution, _start_date, _end_date in events:
            links.extend(make_links(event_id, title, institution))
        inserted, updated = upsert_links(conn, links)
        build_report(events, inserted, updated)

    print(f"events={len(events)} inserted={inserted} updated={updated}")
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
