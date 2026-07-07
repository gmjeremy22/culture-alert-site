import argparse
import re
import sqlite3
from collections import OrderedDict
from datetime import date, datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "culture-alert.sqlite"
REPORT_PATH = BASE_DIR / "keyword-tagging-report.md"
DEFAULT_PERSON = "가족"


TAG_RULES = OrderedDict(
    [
        ("근현대사", ("근현대사", "현대사", "일제", "독립", "광복", "3.1", "3·1", "6·10", "헌법", "DMZ", "휴전선", "권위주의", "민족운동", "대한민국역사박물관")),
        ("한국미술", ("한국미술", "한국근현대", "고미술", "김홍도", "단원", "유영국", "권진규", "조선", "서화", "회화", "분청사기", "백자", "도자")),
        ("고미술", ("고미술",)),
        ("현대미술", ("현대미술", "동시대", "개념미술", "설치", "퍼포먼스", "미디어", "뉴미디어", "다원예술", "MMCA", "서울시립미술관", "아트선재")),
        ("사진", ("사진", "포토", "카메라", "렌즈", "뮤지엄한미", "사진미술관")),
        ("공예", ("공예", "도자", "분청", "백자", "청자", "금속", "목공", "섬유", "장신구", "디자인", "서울공예박물관")),
        ("디자인", ("디자인", "타이포", "그래픽", "브랜드", "포스터", "한가람디자인")),
        ("건축", ("건축", "도시", "주거", "마을", "한양도성", "돈의문", "문화역서울284")),
        ("어린이", ("어린이", "초등", "가족", "아이", "청소년", "학교", "체험", "놀이")),
        ("가족", ("가족", "어린이", "초등", "체험", "놀이", "주말")),
        ("청소년", ("청소년", "중등", "고등", "학교")),
        ("교육", ("아카데미", "강좌", "수업", "워크숍")),
        ("강연", ("강연", "특강", "콜로키움", "학술", "세미나", "대담", "토크")),
        ("무료", ("무료", "관람료 무료", "참가비 무료", "무료관람")),
        ("주말", ("주말", "토요일", "일요일", "토요", "일요")),
        ("역사", ("역사", "박물관", "고궁", "궁중", "왕실", "민속", "생활사", "전쟁", "독립", "유물")),
        ("왕실", ("왕실", "궁중", "고궁", "창덕궁", "궁궐")),
        ("불교미술", ("불교", "불상", "사찰", "보살", "수월관음")),
        ("아시아", ("아시아", "태국", "일본", "중국", "한일", "동양")),
        ("해외문화", ("프랑스", "태국", "해외", "국제", "한불", "워싱턴", "투어링")),
        ("문학", ("문학", "소설", "시집", "한글")),
        ("음악", ("음악", "소리", "아리랑", "공연", "락", "노래")),
        ("미디어아트", ("미디어아트", "뉴미디어", "영상", "다원예술", "VR", "실감")),
        ("상설전시", ("상설", "상설전시", "소장품")),
        ("기획전시", ("기획전", "특별전", "기획전시", "특별전시")),
    ]
)

CONTENT_TYPE_TAGS = {
    "전시": ("전시",),
    "교육": ("교육",),
    "강연": ("강연",),
    "행사": ("행사",),
}

INSTITUTION_TAGS = (
    ("국립현대미술관", ("현대미술", "대형전시")),
    ("서울시립", ("현대미술",)),
    ("서울공예박물관", ("공예", "디자인")),
    ("국립중앙박물관", ("역사", "한국미술")),
    ("국립고궁박물관", ("역사", "왕실")),
    ("국립민속박물관", ("역사", "민속")),
    ("국립한글박물관", ("한글", "문학")),
    ("대한민국역사박물관", ("근현대사", "역사")),
    ("서울역사박물관", ("역사", "서울")),
    ("청계천박물관", ("역사", "서울")),
    ("서울생활사박물관", ("역사", "생활사")),
    ("호암미술관", ("한국미술",)),
    ("뮤지엄한미", ("사진",)),
)


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def days_until(value):
    parsed = parse_date(value)
    if not parsed:
        return None
    return (parsed - date.today()).days


def day_span(start_date, end_date):
    start = parse_date(start_date)
    end = parse_date(end_date)
    if not start or not end:
        return None
    return (end - start).days


def normalize_text(*values):
    text = " ".join(str(value or "") for value in values)
    return re.sub(r"\s+", " ", text).strip()


def split_keywords(value):
    parts = re.split(r"[;,/|·]+", value or "")
    return [part.strip() for part in parts if part.strip()]


def add_tag(tags, tag, source, evidence="", weight=1):
    if not tag:
        return
    current = tags.get(tag)
    if current:
        current["weight"] = max(current["weight"], weight)
        if evidence and evidence not in current["evidence"]:
            current["evidence"].append(evidence)
        if source not in current["sources"]:
            current["sources"].append(source)
        return
    tags[tag] = {"weight": weight, "sources": [source], "evidence": [evidence] if evidence else []}


EVENT_NATURE_LABELS = {
    "limited": "기간한정",
    "long_term": "장기",
    "permanent": "상설",
    "program": "프로그램",
    "unknown": "기간확인",
}


def classify_event_nature(content_type, title, start_date, end_date, status, description):
    if content_type != "전시":
        return "program"
    searchable = normalize_text(title, status, description)
    has_permanent_marker = any(
        marker in searchable for marker in ("상설", "소장품", "상설전시")
    )
    if status in {"상설전", "상설전시"} or (not end_date and has_permanent_marker):
        return "permanent"
    span = day_span(start_date, end_date)
    if span is not None:
        if span >= 180:
            return "long_term"
        return "limited"
    if end_date:
        return "limited"
    starts_in = days_until(start_date)
    if starts_in is not None and starts_in <= -365:
        return "permanent"
    return "unknown"


def event_nature_label(event_nature, content_type):
    if event_nature == "program":
        return content_type
    return EVENT_NATURE_LABELS.get(event_nature, "기간확인")


def occurrence_tags(conn, event_id):
    rows = conn.execute(
        """
        SELECT occurrence_date, start_time, end_time, label, note
        FROM event_occurrences
        WHERE event_id = ?
        """,
        (event_id,),
    ).fetchall()
    tags = []
    for occurrence_date, _start_time, _end_time, label, note in rows:
        parsed = parse_date(occurrence_date)
        if parsed and parsed.weekday() >= 5:
            tags.append(("주말", "회차 일정", occurrence_date, 2))
        text = normalize_text(label, note)
        if "토요일" in text or "일요일" in text or "주말" in text:
            tags.append(("주말", "회차 설명", text, 2))
    return tags


def infer_tags_for_event(conn, row):
    (
        event_id,
        institution_name,
        content_type,
        title,
        start_date,
        end_date,
        location,
        price,
        description,
        raw_keywords,
        raw_text,
        status,
    ) = row
    searchable = normalize_text(
        institution_name,
        content_type,
        title,
        location,
        price,
        description,
    )
    lower_searchable = searchable.lower()
    tags = OrderedDict()

    for tag in CONTENT_TYPE_TAGS.get(content_type, ()):
        add_tag(tags, tag, "유형", content_type, 3)

    for institution_piece, mapped_tags in INSTITUTION_TAGS:
        if institution_piece in institution_name:
            for tag in mapped_tags:
                add_tag(tags, tag, "기관", institution_name, 2)

    for tag, aliases in TAG_RULES.items():
        for alias in aliases:
            if tag == "무료" and "멤버 무료" in searchable:
                continue
            if alias.lower() in lower_searchable:
                add_tag(tags, tag, "내용", alias, 2)
                break

    if price and "무료" in price and "멤버" not in price:
        add_tag(tags, "무료", "가격", price, 3)

    if content_type in {"교육", "강연", "행사"}:
        add_tag(tags, "참여형", "유형", content_type, 2)

    for tag, source, evidence, weight in occurrence_tags(conn, event_id):
        add_tag(tags, tag, source, evidence, weight)

    if days_until(end_date) is not None and 0 <= days_until(end_date) <= 14:
        add_tag(tags, "곧 종료", "일정", end_date, 2)
    if days_until(start_date) is not None and 0 <= days_until(start_date) <= 14:
        add_tag(tags, "곧 시작", "일정", start_date, 1)

    return tags


def ensure_schema(conn):
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(cultural_events)").fetchall()
    }
    if "event_nature" not in columns:
        conn.execute(
            "ALTER TABLE cultural_events ADD COLUMN event_nature TEXT NOT NULL DEFAULT 'unknown'"
        )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS event_keywords (
          event_id INTEGER NOT NULL,
          keyword TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT 'rule',
          weight INTEGER NOT NULL DEFAULT 1,
          evidence TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (event_id) REFERENCES cultural_events(id),
          UNIQUE (event_id, keyword)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_event_keywords_keyword ON event_keywords(keyword, weight)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_event_keywords_event ON event_keywords(event_id)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_nature ON cultural_events(event_nature)")
    conn.commit()


def load_events(conn):
    return conn.execute(
        """
        SELECT
          e.id,
          i.name,
          e.content_type,
          e.title,
          e.start_date,
          e.end_date,
          e.location,
          e.price,
          e.description,
          e.keywords,
          e.raw_text,
          e.status
        FROM cultural_events e
        JOIN institutions i ON i.id = e.institution_id
        WHERE e.status != '종료'
          AND e.title NOT LIKE '%전시·교육 모니터%'
        ORDER BY e.id
        """
    ).fetchall()


def tag_events(conn):
    ensure_schema(conn)
    rows = load_events(conn)
    summary = []
    conn.execute("DELETE FROM event_keywords")
    for row in rows:
        event_id = row[0]
        tags = infer_tags_for_event(conn, row)
        (
            _event_id,
            _institution_name,
            content_type,
            title,
            start_date,
            end_date,
            _location,
            _price,
            description,
            raw_keywords,
            _raw_text,
            status,
        ) = row
        event_nature = classify_event_nature(
            content_type, title, start_date, end_date, status, description
        )
        nature_label = event_nature_label(event_nature, content_type)
        add_tag(tags, nature_label, "일정 성격", event_nature, 4)
        ordered_tags = sorted(tags.items(), key=lambda item: (-item[1]["weight"], item[0]))
        for tag, meta in ordered_tags:
            evidence = "; ".join(meta["evidence"][:3])
            source = ",".join(meta["sources"][:3])
            conn.execute(
                """
                INSERT INTO event_keywords (event_id, keyword, source, weight, evidence)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(event_id, keyword) DO UPDATE SET
                  source=excluded.source,
                  weight=excluded.weight,
                  evidence=excluded.evidence,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (event_id, tag, source, meta["weight"], evidence),
            )
        visible_keywords = ";".join(tag for tag, _meta in ordered_tags)
        conn.execute(
            """
            UPDATE cultural_events
            SET keywords = ?, event_nature = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (visible_keywords, event_nature, event_id),
        )
        summary.append((event_id, row[3], [tag for tag, _meta in ordered_tags]))
    conn.commit()
    return summary


def load_interests(conn, person_name):
    return conn.execute(
        """
        SELECT keyword, weight
        FROM interests
        WHERE person_name = ? AND active = 1
        ORDER BY weight DESC, keyword
        """,
        (person_name,),
    ).fetchall()


def score_recommendations(conn, person_name):
    interests = load_interests(conn, person_name)
    event_rows = conn.execute(
        """
        SELECT
          e.id,
          i.name,
          e.content_type,
          e.title,
          e.start_date,
          e.end_date,
          e.location,
          e.description,
          e.raw_text
        FROM cultural_events e
        JOIN institutions i ON i.id = e.institution_id
        WHERE e.status != '종료'
          AND e.title NOT LIKE '%전시·교육 모니터%'
        """
    ).fetchall()
    tag_rows = conn.execute(
        "SELECT event_id, keyword, weight FROM event_keywords"
    ).fetchall()
    tags_by_event = {}
    for event_id, keyword, weight in tag_rows:
        tags_by_event.setdefault(event_id, {})[keyword] = weight

    conn.execute("DELETE FROM recommendations WHERE person_name = ?", (person_name,))
    scored = []
    for row in event_rows:
        event_id, institution, content_type, title, start_date, end_date, location, description, _raw_text = row
        text = normalize_text(institution, content_type, title, location, description).lower()
        event_tags = tags_by_event.get(event_id, {})
        matched = []
        score = 0.0
        for keyword, interest_weight in interests:
            keyword_lower = keyword.lower()
            if keyword in event_tags:
                tag_weight = event_tags[keyword]
                score += interest_weight * (2 + min(tag_weight, 3) * 0.5)
                matched.append(keyword)
            elif keyword_lower in text:
                score += interest_weight
                matched.append(keyword)

        remaining = days_until(end_date)
        starts_in = days_until(start_date)
        timing_reasons = []
        if remaining is not None and 0 <= remaining <= 14:
            score += 3
            timing_reasons.append(f"{remaining}일 남음")
        elif remaining is not None and 0 <= remaining <= 30:
            score += 1
            timing_reasons.append(f"{remaining}일 남음")
        if starts_in is not None and 0 <= starts_in <= 14:
            score += 1
            timing_reasons.append(f"{starts_in}일 뒤 시작")

        top_tags = sorted(event_tags.items(), key=lambda item: (-item[1], item[0]))[:5]
        tag_text = ", ".join(tag for tag, _weight in top_tags)
        matched_text = ", ".join(dict.fromkeys(matched))
        reason_parts = []
        if matched_text:
            reason_parts.append(f"관심 키워드: {matched_text}")
        if tag_text:
            reason_parts.append(f"일정 태그: {tag_text}")
        if timing_reasons:
            reason_parts.append("일정: " + ", ".join(timing_reasons))
        reason = " · ".join(reason_parts) or "일정/장소 기준"
        conn.execute(
            """
            INSERT INTO recommendations (event_id, person_name, score, matched_keywords, reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_id, person_name, round(score, 2), matched_text, reason),
        )
        scored.append((score, event_id, title, matched_text, tag_text))
    conn.commit()
    return sorted(scored, reverse=True)


def write_report(summary, scored, person_name):
    tagged_count = sum(1 for _event_id, _title, tags in summary if tags)
    all_tags = {}
    for _event_id, _title, tags in summary:
        for tag in tags:
            all_tags[tag] = all_tags.get(tag, 0) + 1
    lines = [
        "# 키워드 태깅 리포트",
        "",
        f"- 태깅 대상: {len(summary)}건",
        f"- 태그가 붙은 일정: {tagged_count}건",
        f"- 추천 대상: {person_name}",
        "",
        "## 많이 붙은 태그",
        "",
    ]
    for tag, count in sorted(all_tags.items(), key=lambda item: (-item[1], item[0]))[:30]:
        lines.append(f"- {tag}: {count}건")
    lines.extend(["", "## 추천 점수 상위", ""])
    for score, _event_id, title, matched, tag_text in scored[:20]:
        lines.append(f"- {title}")
        lines.append(f"  - 점수: {score:.1f}")
        lines.append(f"  - 관심 키워드: {matched or '없음'}")
        lines.append(f"  - 태그: {tag_text or '없음'}")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="문화 일정 키워드 태깅 및 추천 점수 갱신")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--person", default=DEFAULT_PERSON)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    summary = tag_events(conn)
    scored = score_recommendations(conn, args.person)
    write_report(summary, scored, args.person)
    print(f"tagged_events={len(summary)}")
    print(f"recommended_events={len([item for item in scored if item[0] > 0])}")
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
