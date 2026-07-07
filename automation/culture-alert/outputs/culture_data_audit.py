import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "culture-alert.sqlite"
CARD_HTML = BASE_DIR / "keyword-recommendation-report.html"
OFFICIAL_MONITOR_REPORT = BASE_DIR / "official-page-monitor-report.md"
REPORT_PATH = BASE_DIR / "data-quality-audit-report.md"
MONITOR_PATTERN = "%전시·교육 모니터%"
ENDED_STATUS = "종료"


def scalar(conn, query, params=()):
    return conn.execute(query, params).fetchone()[0]


def date_issues(conn):
    issues = []
    rows = conn.execute(
        "SELECT id, title, start_date, end_date FROM cultural_events"
    ).fetchall()
    for event_id, title, start_date, end_date in rows:
        parsed = {}
        for column, value in (("start_date", start_date), ("end_date", end_date)):
            if not value:
                continue
            try:
                parsed[column] = datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                issues.append(f"{event_id} | {title} | {column}={value}")
        if parsed.get("start_date") and parsed.get("end_date"):
            if parsed["start_date"] > parsed["end_date"]:
                issues.append(f"{event_id} | {title} | 시작일이 종료일보다 늦음")
    return issues


def url_issues(conn):
    issues = []
    rows = conn.execute(
        "SELECT id, title, source_url, image_url FROM cultural_events"
    ).fetchall()
    for event_id, title, source_url, image_url in rows:
        parsed_source = urlparse(source_url or "")
        if parsed_source.scheme not in {"http", "https"} or not parsed_source.netloc:
            issues.append(f"{event_id} | {title} | source_url={source_url}")
        if image_url:
            parsed_image = urlparse(image_url)
            if image_url.lower().startswith("data:"):
                issues.append(f"{event_id} | {title} | image_url=data URI")
            elif parsed_image.scheme not in {"http", "https"} or not parsed_image.netloc:
                issues.append(f"{event_id} | {title} | image_url={image_url}")
    return issues


def official_failures():
    if not OFFICIAL_MONITOR_REPORT.exists():
        return []
    lines = OFFICIAL_MONITOR_REPORT.read_text(encoding="utf-8").splitlines()
    failures = []
    in_failure_section = False
    for line in lines:
        if line.strip() == "## 실패/보류":
            in_failure_section = True
            continue
        if in_failure_section and line.startswith("## "):
            break
        if in_failure_section and line.startswith("- ") and "없음" not in line:
            failures.append(line)
    return failures


def main():
    html = CARD_HTML.read_text(encoding="utf-8") if CARD_HTML.exists() else ""
    with sqlite3.connect(DB_PATH) as conn:
        totals = {
            "institutions": scalar(conn, "SELECT COUNT(*) FROM institutions"),
            "events": scalar(conn, "SELECT COUNT(*) FROM cultural_events"),
            "recommendations": scalar(conn, "SELECT COUNT(*) FROM recommendations"),
            "event_keywords": scalar(conn, "SELECT COUNT(*) FROM event_keywords"),
            "occurrences": scalar(conn, "SELECT COUNT(*) FROM event_occurrences"),
            "auto_monitors": scalar(
                conn,
                "SELECT COUNT(*) FROM institutions WHERE collection_phase='phase2-auto-monitor'",
            ),
            "monitor_events": scalar(
                conn,
                "SELECT COUNT(*) FROM cultural_events WHERE title LIKE ?",
                (MONITOR_PATTERN,),
            ),
            "monitor_in_recommendations": scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM recommendations r
                JOIN cultural_events e ON e.id = r.event_id
                WHERE e.title LIKE ?
                """,
                (MONITOR_PATTERN,),
            ),
            "monitor_in_keywords": scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM event_keywords k
                JOIN cultural_events e ON e.id = k.event_id
                WHERE e.title LIKE ?
                """,
                (MONITOR_PATTERN,),
            ),
            "blank_institutions": scalar(
                conn,
                "SELECT COUNT(*) FROM institutions WHERE TRIM(COALESCE(name, '')) = ''",
            ),
            "blank_titles": scalar(
                conn,
                "SELECT COUNT(*) FROM cultural_events WHERE TRIM(COALESCE(title, '')) = ''",
            ),
            "blank_sources": scalar(
                conn,
                "SELECT COUNT(*) FROM cultural_events WHERE TRIM(COALESCE(source_url, '')) = ''",
            ),
            "missing_institution_links": scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM cultural_events e
                LEFT JOIN institutions i ON i.id = e.institution_id
                WHERE i.id IS NULL
                """,
            ),
            "duplicate_groups": scalar(
                conn,
                """
                SELECT COUNT(*)
                FROM (
                  SELECT institution_id, title, COALESCE(start_date, ''), source_url, COUNT(*) AS c
                  FROM cultural_events
                  GROUP BY institution_id, title, COALESCE(start_date, ''), source_url
                  HAVING c > 1
                )
                """,
            ),
        }
        statuses = conn.execute(
            "SELECT status, COUNT(*) FROM cultural_events GROUP BY status ORDER BY COUNT(*) DESC"
        ).fetchall()
        content_types = conn.execute(
            """
            SELECT content_type, COUNT(*)
            FROM cultural_events
            WHERE status != ?
              AND title NOT LIKE ?
            GROUP BY content_type
            ORDER BY COUNT(*) DESC
            """,
            (ENDED_STATUS, MONITOR_PATTERN),
        ).fetchall()
        date_bad = date_issues(conn)
        url_bad = url_issues(conn)

    html_monitor_count = html.count("전시·교육 모니터")
    failures = official_failures()
    hard_errors = [
        totals["blank_institutions"],
        totals["blank_titles"],
        totals["blank_sources"],
        totals["missing_institution_links"],
        totals["duplicate_groups"],
        totals["monitor_in_recommendations"],
        totals["monitor_in_keywords"],
        html_monitor_count,
        len(date_bad),
        len(url_bad),
    ]
    verdict = "통과" if sum(hard_errors) == 0 else "확인 필요"

    lines = [
        "# 데이터 품질 점검 리포트",
        "",
        f"- 판정: {verdict}",
        f"- 기관: {totals['institutions']}개",
        f"- 전체 일정/모니터 원천: {totals['events']}건",
        f"- 추천 카드: {totals['recommendations']}건",
        f"- 키워드 태그: {totals['event_keywords']}건",
        f"- 세부 회차 일정: {totals['occurrences']}건",
        f"- 자동 모니터 승격 기관: {totals['auto_monitors']}개",
        f"- 자동 모니터 이벤트: {totals['monitor_events']}건",
        "",
        "## 통과 기준",
        "",
        f"- 기관명 누락: {totals['blank_institutions']}건",
        f"- 일정 제목 누락: {totals['blank_titles']}건",
        f"- 출처 URL 누락: {totals['blank_sources']}건",
        f"- 기관 연결 끊김: {totals['missing_institution_links']}건",
        f"- 중복 일정 그룹: {totals['duplicate_groups']}건",
        f"- 날짜 오류: {len(date_bad)}건",
        f"- URL/이미지 형식 오류: {len(url_bad)}건",
        f"- 추천 점수에 섞인 자동 모니터: {totals['monitor_in_recommendations']}건",
        f"- 키워드 태그에 섞인 자동 모니터: {totals['monitor_in_keywords']}건",
        f"- 카드 HTML에 노출된 자동 모니터 문구: {html_monitor_count}건",
        "",
        "## 상태별 전체 원천",
        "",
    ]
    for status, count in statuses:
        lines.append(f"- {status}: {count}건")
    lines.extend(["", "## 카드 기준 유형", ""])
    for content_type, count in content_types:
        lines.append(f"- {content_type}: {count}건")
    lines.extend(["", "## 공식 페이지 점검 보류", ""])
    if failures:
        lines.extend(failures)
    else:
        lines.append("- 없음")
    if date_bad:
        lines.extend(["", "## 날짜 오류 상세", *[f"- {item}" for item in date_bad]])
    if url_bad:
        lines.extend(["", "## URL 오류 상세", *[f"- {item}" for item in url_bad]])
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"verdict={verdict}")
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
