import argparse
import html
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "culture-alert.sqlite"
REPORT_PATH = BASE_DIR / "program-schedule-report.md"


WEEKDAY_LABELS = ["월", "화", "수", "목", "금", "토", "일"]
WEEKDAY_WORDS = {
    "월": 0,
    "월요일": 0,
    "화": 1,
    "화요일": 1,
    "수": 2,
    "수요일": 2,
    "목": 3,
    "목요일": 3,
    "금": 4,
    "금요일": 4,
    "토": 5,
    "토요일": 5,
    "일": 6,
    "일요일": 6,
}


def ensure_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS event_occurrences (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          event_id INTEGER NOT NULL,
          occurrence_date TEXT NOT NULL,
          start_time TEXT,
          end_time TEXT,
          label TEXT,
          note TEXT,
          source_url TEXT,
          confidence INTEGER NOT NULL DEFAULT 5,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (event_id) REFERENCES cultural_events(id),
          UNIQUE (event_id, occurrence_date, start_time, label)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_event_occurrences_event ON event_occurrences(event_id, occurrence_date)"
    )


def normalize_url(url):
    return (url or "").replace(chr(182), "&para")


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def to_iso_date(year, month, day):
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def extract_dates(text):
    dates = []
    for match in re.finditer(r"(20\d{2})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})", text):
        parsed = to_iso_date(match.group(1), match.group(2), match.group(3))
        if parsed:
            dates.append(parsed)
    return dates


def normalize_time(value):
    if not value:
        return None
    hour, minute = value.split(":")
    return f"{int(hour):02d}:{int(minute):02d}"


def extract_times(text):
    times = [normalize_time(item) for item in re.findall(r"\b\d{1,2}:\d{2}\b", text)]
    times = [item for item in times if item]
    if not times:
        return None, None

    # Prefer the first non-registration-looking range.
    for index in range(len(times) - 1):
        start_time = times[index]
        end_time = times[index + 1]
        if start_time == "09:00" and end_time in {"18:00", "23:55"}:
            continue
        if start_time == end_time:
            return start_time, None
        return start_time, end_time
    return times[0], None


def fetch_plain_text(url):
    request = Request(
        normalize_url(url),
        headers={"User-Agent": "Mozilla/5.0 culture-alert prototype; contact=personal-use"},
    )
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        page = response.read().decode(charset, "replace")
    page = re.sub(r"<script\b.*?</script>", " ", page, flags=re.S | re.I)
    page = re.sub(r"<style\b.*?</style>", " ", page, flags=re.S | re.I)
    plain = re.sub(r"<[^>]+>", " ", page)
    plain = html.unescape(plain)
    return re.sub(r"\s+", " ", plain).strip()


def extract_between(text, start_label, end_labels):
    start = text.find(start_label)
    if start == -1:
        return ""
    start += len(start_label)
    end_positions = [text.find(label, start) for label in end_labels]
    end_positions = [pos for pos in end_positions if pos != -1]
    end = min(end_positions) if end_positions else min(len(text), start + 500)
    return text[start:end].strip(" :.-")


def compact_field(value, limit=220):
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def extract_detail_fields(text):
    summary = extract_between(text, "요약", ["문의", "첨부파일", "파일선택"])
    location = extract_between(text, "장소", ["정원", "대상", "문의", "요약", "첨부파일", "파일선택"])
    target = extract_between(text, "대상", ["장소", "정원", "문의", "요약", "첨부파일", "파일선택"])
    apply_period = extract_between(text, "접수기간", ["교육기간", "대상", "장소", "정원", "문의"])
    location = location or extract_between(text, "교육장소", ["모집기간", "교육대상", "선발방법", "모집정원", "이용"])
    target = target or extract_between(text, "교육대상", ["선발방법", "모집정원", "이용", "신청제한"])
    apply_period = apply_period or extract_between(text, "모집기간", ["교육대상", "선발방법", "모집정원", "이용"])
    return {
        "summary": summary,
        "location": compact_field(location, 180),
        "target": compact_field(target, 180),
        "apply_period": compact_field(apply_period, 180),
    }


def weekdays_from_text(text):
    if "매주" not in text:
        return []
    found = []
    window_start = text.find("매주")
    window = text[window_start : window_start + 80]
    for word, index in WEEKDAY_WORDS.items():
        if word in window and index not in found:
            found.append(index)
    return sorted(found)


def dates_from_weekdays(start_date, end_date, weekdays):
    start = parse_date(start_date)
    end = parse_date(end_date)
    if not start or not end or not weekdays:
        return []
    dates = []
    current = start
    while current <= end:
        if current.weekday() in weekdays:
            dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def daily_dates_if_short(start_date, end_date):
    start = parse_date(start_date)
    end = parse_date(end_date)
    if not start or not end:
        return []
    if (end - start).days > 10:
        return []
    dates = []
    current = start
    while current <= end:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def is_sema_event(event):
    return "sema.seoul.go.kr" in normalize_url(event[7])


def sema_focus_text(detail_text, title=""):
    start = 0
    if title:
        title_candidates = [title, title[:32], title[:20]]
        for candidate in title_candidates:
            if not candidate:
                continue
            index = detail_text.find(candidate)
            if index != -1:
                start = index
                break
    end_candidates = [
        detail_text.find("모든 전시와 프로그램 안내", start + 500),
        detail_text.find("미술관 소개", start + 500),
    ]
    end_candidates = [index for index in end_candidates if index != -1]
    end = min(end_candidates) if end_candidates else min(len(detail_text), start + 8000)
    return detail_text[start:end]


def dates_in_range(text, start_date, end_date):
    start = parse_date(start_date)
    end = parse_date(end_date)
    dates = []
    for item in extract_dates(text):
        parsed = parse_date(item)
        if parsed and start and end and start <= parsed <= end:
            dates.append(item)
    return sorted(dict.fromkeys(dates))


def sema_listing_dates(description, start_date, end_date):
    if "목록 일정:" not in (description or ""):
        return [], ""
    schedule_text = description.split("목록 일정:", 1)[1].split(" / ", 1)[0].strip()
    dates = sorted(dict.fromkeys(extract_dates(schedule_text)))
    if not dates:
        return [], ""
    if "~" in schedule_text:
        return [start_date] if start_date else dates[:1], "기간형 교육 시작일"
    if len(dates) > 1:
        return dates, "목록의 개별 회차"
    return dates, "목록의 단일 회차"


def sema_time_overrides(detail_text, title=""):
    focus = sema_focus_text(detail_text, title)
    overrides = {}
    pattern = re.compile(
        r"(20\d{2})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2}).{0,90}?"
        r"(\d{1,2}:\d{2})\s*(?:~|–|-)\s*(\d{1,2}:\d{2})",
        flags=re.S,
    )
    for match in pattern.finditer(focus):
        occurrence_date = to_iso_date(match.group(1), match.group(2), match.group(3))
        if not occurrence_date:
            continue
        overrides[occurrence_date] = (
            normalize_time(match.group(4)),
            normalize_time(match.group(5)),
        )
    return overrides


def sema_labeled_session_dates(detail_text, title=""):
    focus = sema_focus_text(detail_text, title)
    dates = []
    for match in re.finditer(
        r"(?:\[\s*\d+\s*회차\s*\]|\d+\s*회차)\s*(20\d{2})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})",
        focus,
    ):
        occurrence_date = to_iso_date(match.group(1), match.group(2), match.group(3))
        if occurrence_date:
            dates.append(occurrence_date)
    return sorted(dict.fromkeys(dates))


def sema_schedule_time_text(focus):
    for marker in ["일 시", "일시", "일 정", "일정", "매주"]:
        index = focus.find(marker)
        if index != -1:
            return focus[index : index + 700]
    return ""


def choose_occurrence_dates(event, detail_text):
    event_id, content_type, _institution, title, start_date, end_date = event[:6]
    start = parse_date(start_date)
    end = parse_date(end_date)

    if is_sema_event(event):
        focus = sema_focus_text(detail_text, title)
        labeled_dates = sema_labeled_session_dates(detail_text, title)
        if labeled_dates:
            return labeled_dates, "상세 페이지 회차 목록"
        time_dates = sorted(sema_time_overrides(detail_text, title))
        if len(time_dates) > 1:
            return time_dates, "상세 페이지 시간표"
        dates, basis = sema_listing_dates(event[8], start_date, end_date)
        if dates:
            return dates, basis
        if start_date:
            return [start_date], "기간형 교육 시작일"

    all_dates = dates_in_range(detail_text, start_date, end_date)

    if content_type == "교육":
        if len(all_dates) > 2:
            return all_dates, "상세 페이지 날짜 목록"
        weekdays = weekdays_from_text(detail_text)
        weekday_dates = dates_from_weekdays(start_date, end_date, weekdays)
        if weekday_dates:
            return weekday_dates, "반복 요일 추정"
        daily_dates = daily_dates_if_short(start_date, end_date)
        if daily_dates:
            return daily_dates, "짧은 기간 일별 회차"
        if start_date:
            return [start_date], "기간형 교육 시작일"

    if start_date:
        return [start_date], "단일 일정"
    return [], "날짜 확인 필요"


def build_occurrences(event, detail_text):
    (
        event_id,
        content_type,
        institution_name,
        title,
        start_date,
        end_date,
        location,
        source_url,
        description,
    ) = event
    dates, basis = choose_occurrence_dates(event, detail_text)
    if is_sema_event(event):
        focus_text = sema_focus_text(detail_text, title)
        start_time, end_time = extract_times(sema_schedule_time_text(focus_text))
        time_overrides = sema_time_overrides(detail_text, title)
    else:
        start_time, end_time = extract_times(detail_text)
        time_overrides = {}
    fields = extract_detail_fields(detail_text)
    note_parts = [basis]
    if fields["target"]:
        note_parts.append(f"대상: {fields['target']}")
    if fields["apply_period"]:
        note_parts.append(f"접수: {fields['apply_period']}")
    note = " / ".join(note_parts)
    occurrences = []
    for index, occurrence_date in enumerate(dates, start=1):
        label = "당일" if len(dates) == 1 else f"{index}회차"
        occurrence_start_time, occurrence_end_time = time_overrides.get(
            occurrence_date,
            (start_time, end_time),
        )
        occurrences.append(
            {
                "event_id": event_id,
                "occurrence_date": occurrence_date,
                "start_time": occurrence_start_time,
                "end_time": occurrence_end_time,
                "label": label,
                "note": note,
                "source_url": normalize_url(source_url),
                "confidence": 8
                if basis in {"상세 페이지 날짜 목록", "상세 페이지 회차 목록", "상세 페이지 시간표", "단일 일정", "목록의 개별 회차", "목록의 단일 회차"}
                else 6,
            }
        )
    return occurrences, fields


def load_program_events(conn):
    rows = conn.execute(
        """
        SELECT e.id, e.content_type, i.name, e.title, e.start_date, e.end_date,
               e.location, e.source_url, COALESCE(e.description, '')
        FROM cultural_events e
        JOIN institutions i ON i.id = e.institution_id
        WHERE e.content_type != '전시'
        ORDER BY e.start_date, e.title
        """
    ).fetchall()
    return rows


def upsert_occurrences(conn, event_ids, occurrences):
    if event_ids:
        placeholders = ",".join("?" for _ in event_ids)
        conn.execute(f"DELETE FROM event_occurrences WHERE event_id IN ({placeholders})", event_ids)
    for occurrence in occurrences:
        conn.execute(
            """
            INSERT INTO event_occurrences (
              event_id, occurrence_date, start_time, end_time, label, note, source_url, confidence
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id, occurrence_date, start_time, label) DO UPDATE SET
              end_time=excluded.end_time,
              note=excluded.note,
              source_url=excluded.source_url,
              confidence=excluded.confidence,
              updated_at=CURRENT_TIMESTAMP
            """,
            (
                occurrence["event_id"],
                occurrence["occurrence_date"],
                occurrence["start_time"],
                occurrence["end_time"],
                occurrence["label"],
                occurrence["note"],
                occurrence["source_url"],
                occurrence["confidence"],
            ),
        )


def update_event_detail(conn, event, fields, detail_text):
    event_id = event[0]
    location = fields["location"] or event[6]
    summary = fields["summary"]
    if not summary:
        summary = event[8] or detail_text[:520]
    conn.execute(
        """
        UPDATE cultural_events
        SET location = COALESCE(NULLIF(?, ''), location),
            description = COALESCE(NULLIF(?, ''), description),
            source_url = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (location, summary[:900], normalize_url(event[7]), event_id),
    )


def build_report(rows, occurrences, failures):
    rows_by_id = {row[0]: row for row in rows}
    occurrences_by_event = {}
    for occurrence in occurrences:
        occurrences_by_event.setdefault(occurrence["event_id"], []).append(occurrence)

    lines = [
        "# 강연/교육 세부 회차 정리",
        "",
        f"- 검토한 강연/교육/행사: {len(rows)}건",
        f"- 생성한 회차: {len(occurrences)}건",
        f"- 상세 페이지 확인 실패: {len(failures)}건",
        "",
        "## 회차 목록",
        "",
    ]
    for event_id, event_occurrences in occurrences_by_event.items():
        row = rows_by_id[event_id]
        lines.append(f"### {row[3]}")
        lines.append(f"- 기관: {row[2]}")
        lines.append(f"- 유형: {row[1]}")
        lines.append(f"- 큰 기간: {row[4] or '?'} ~ {row[5] or '?'}")
        for item in event_occurrences:
            time_text = item["start_time"] or "시간 확인 필요"
            if item["end_time"]:
                time_text = f"{time_text}~{item['end_time']}"
            lines.append(f"  - {item['label']}: {item['occurrence_date']} {time_text}")
        lines.append("")

    if failures:
        lines.extend(["## 확인 실패", ""])
        for event_id, title, reason in failures:
            lines.append(f"- {title}: {reason}")

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="강연/교육/행사 세부 회차 추출기")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()

    with sqlite3.connect(args.db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        conn.execute(
            "UPDATE cultural_events SET source_url = REPLACE(source_url, ?, ?)",
            (chr(182), "&para"),
        )
        rows = load_program_events(conn)
        all_occurrences = []
        failures = []
        for row in rows:
            try:
                detail_text = fetch_plain_text(row[7])
                occurrences, fields = build_occurrences(row, detail_text)
                update_event_detail(conn, row, fields, detail_text)
                all_occurrences.extend(occurrences)
            except Exception as exc:
                fallback_text = " ".join(str(value or "") for value in row)
                occurrences, _fields = build_occurrences(row, fallback_text)
                all_occurrences.extend(occurrences)
                failures.append((row[0], row[3], str(exc)))
        upsert_occurrences(conn, [row[0] for row in rows], all_occurrences)
        conn.commit()
        build_report(rows, all_occurrences, failures)

    print(f"programs={len(rows)} occurrences={len(all_occurrences)} failures={len(failures)}")
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
