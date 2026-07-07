import html
import json
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

from culture_image_utils import display_image_url


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "culture-alert.sqlite"
OUTPUT_PATH = BASE_DIR / "culture-card-gallery.html"


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


def format_period(start_date, end_date, status=""):
    if status in {"상설전", "상설전시"}:
        return "상설전"
    if start_date and end_date:
        return f"{start_date} ~ {end_date}"
    if start_date:
        return f"{start_date} ~"
    if end_date:
        return f"~ {end_date}"
    return "기간 확인 필요"


NATURE_LABELS = {
    "limited": "기간한정",
    "long_term": "장기",
    "permanent": "상설",
    "program": "프로그램",
    "unknown": "기간확인",
}


def nature_label(event_nature, content_type):
    if event_nature == "program":
        return content_type
    return NATURE_LABELS.get(event_nature or "unknown", "기간확인")


def compact_text(value, limit=360):
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


NOISY_DESCRIPTION_MARKERS = (
    "$(function",
    "$.ajax",
    "ManpaJs",
    "alert(\"code:",
    "document).delegate",
    "개인정보처리방침",
    "담당자 정보",
    "소속박물관 바로가기",
    "© National Museum of Korea",
)


def looks_like_page_noise(value):
    text = str(value or "")
    if any(marker in text for marker in NOISY_DESCRIPTION_MARKERS):
        return True
    compacted = " ".join(text.split())
    if compacted.startswith("현재전시 ") and " 기간 " in compacted and " 장소 " in compacted:
        return True
    if "현재전시." in compacted and "제목:" in compacted and "장소:" in compacted:
        return True
    if compacted.startswith("공식 페이지 모니터 수집."):
        return True
    return len(compacted) > 1800 and ("function" in compacted or "$." in compacted)


def display_description(description, raw_text, limit=420):
    if description:
        return compact_text(description, limit)
    if not raw_text or looks_like_page_noise(raw_text):
        return ""
    return compact_text(raw_text, limit)


def display_title(title):
    if title == "한성부입니다":
        return "〈한성부입니다〉"
    return title


def split_keyword_list(value):
    keywords = []
    seen = set()
    for part in re.split(r"[;,/|·]+", value or ""):
        keyword = " ".join(part.split()).strip()
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        keywords.append(keyword)
    return keywords


TAG_LAYERS = {
    "nature": {"기간한정", "장기", "상설", "기간확인", "전시", "교육", "강연", "행사"},
    "time": {"곧 종료", "곧 시작"},
    "field": {
        "역사",
        "근현대사",
        "한국미술",
        "현대미술",
        "고미술",
        "공예",
        "디자인",
        "사진",
        "건축",
        "문학",
        "음악",
        "미디어아트",
        "불교미술",
        "왕실",
        "민속",
        "생활사",
        "한글",
        "아시아",
        "해외문화",
    },
    "audience": {"어린이", "가족", "청소년", "참여형"},
    "format": {"기획전시", "특별전시", "상설전시", "대형전시"},
    "access": {"무료"},
    "place": {"서울", "경기", "인천"},
}


def tag_layer(keyword):
    for layer, keywords in TAG_LAYERS.items():
        if keyword in keywords:
            return layer
    return "other"


def keywords_with_nature(keywords, event_nature, content_type):
    label = nature_label(event_nature, content_type)
    items = [label] if label else []
    for keyword in split_keyword_list(keywords):
        if keyword not in items and keyword != "전시":
            items.append(keyword)
    return items


def keyword_meta(keyword_list):
    return [{"label": keyword, "layer": tag_layer(keyword)} for keyword in keyword_list]


def keyword_chip_html(keyword):
    return (
        f'<span class="tag-layer-{html.escape(tag_layer(keyword))}">'
        f"{html.escape(keyword)}</span>"
    )


def usable_image_url(value):
    return display_image_url(value)


WEEKDAY_LABELS = ("월", "화", "수", "목", "금", "토", "일")


VENUE_ALIAS_GROUPS = (
    (
        "서울시립미술관 서소문본관",
        ("서울시립미술관 서소문본관", "서소문본관", "서소문 본관"),
    ),
    (
        "서울시립 북서울미술관",
        ("서울시립 북서울미술관", "북서울미술관", "북서울"),
    ),
    (
        "서울시립 남서울미술관",
        ("서울시립 남서울미술관", "남서울미술관", "남서울"),
    ),
    (
        "서울시립 미술아카이브",
        ("서울시립 미술아카이브", "미술아카이브"),
    ),
    (
        "서울시립 사진미술관",
        ("서울시립 사진미술관", "사진미술관"),
    ),
    (
        "SeMA 백남준기념관",
        ("SeMA 백남준기념관", "백남준기념관"),
    ),
    (
        "국립현대미술관 서울관",
        ("국립현대미술관 서울관", "MMCA 서울", "서울관"),
    ),
    (
        "국립현대미술관 과천관",
        ("국립현대미술관 과천관", "MMCA 과천", "과천관"),
    ),
    (
        "국립현대미술관 덕수궁관",
        ("국립현대미술관 덕수궁관", "MMCA 덕수궁", "덕수궁관"),
    ),
    (
        "국립민속박물관 파주",
        ("국립민속박물관 파주", "파주관"),
    ),
)

def compact_place_text(value):
    text = " ".join(str(value or "").split())
    text = re.sub(r"\s+", " ", text).strip(" ,")
    return text


def infer_venue_label(institution, location):
    institution_text = compact_place_text(institution)
    location_text = compact_place_text(location)
    combined = f"{institution_text} {location_text}"
    for venue, aliases in VENUE_ALIAS_GROUPS:
        if institution_text == venue:
            return venue
        if any(alias and alias in combined for alias in aliases):
            return venue
    if institution_text == "서울시립미술관" and not location_text:
        return "서울시립미술관 (장소 확인 필요)"
    if location_text in {"외부 별도 장소", "주워싱턴한국문화원"}:
        return location_text
    return institution_text


def format_detail_location(venue_label, location):
    location_text = compact_place_text(location)
    if not location_text or location_text == "확인 필요":
        return venue_label or "확인 필요"
    if venue_label and venue_label not in location_text:
        return f"{venue_label} · {location_text}"
    return location_text


def display_occurrence_date(value):
    parsed = parse_date(value)
    if not parsed:
        return value or "날짜 확인 필요"
    return f"{value} ({WEEKDAY_LABELS[parsed.weekday()]})"


def format_time_range(start_time, end_time):
    if start_time and end_time:
        return f"{start_time}~{end_time}"
    if start_time:
        return start_time
    return "시간 확인 필요"


def load_occurrences(conn, event_id):
    table_exists = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'event_occurrences'
        """
    ).fetchone()
    if not table_exists:
        return []
    rows = conn.execute(
        """
        SELECT occurrence_date, start_time, end_time, label, note, confidence
        FROM event_occurrences
        WHERE event_id = ?
        ORDER BY occurrence_date, COALESCE(start_time, '99:99'), COALESCE(label, '')
        """,
        (event_id,),
    ).fetchall()
    occurrences = []
    today = date.today()
    for occurrence_date, start_time, end_time, label, note, confidence in rows:
        parsed = parse_date(occurrence_date)
        occurrences.append(
            {
                "date": occurrence_date,
                "dateText": display_occurrence_date(occurrence_date),
                "time": format_time_range(start_time, end_time),
                "startTime": start_time or "",
                "endTime": end_time or "",
                "label": label or "",
                "note": note or "",
                "confidence": int(confidence or 5),
                "isPast": bool(parsed and parsed < today),
            }
        )
    return occurrences


def normalize_companion_key(value):
    text = compact_place_text(value)
    if not text or text == "확인 필요":
        return ""
    return text


def compact_event_reference(item):
    next_occurrence = item.get("nextOccurrence")
    return {
        "index": item["index"],
        "id": item["id"],
        "type": item["type"],
        "title": item["title"],
        "displayTitle": item["displayTitle"],
        "institution": item["institution"],
        "venueLabel": item["venueLabel"],
        "displayVenue": item["displayVenue"],
        "period": item["period"],
        "startDate": item["startDate"],
        "endDate": item["endDate"],
        "location": item["location"],
        "status": item["status"],
        "nextOccurrence": next_occurrence,
    }


def attach_companion_events(items):
    for index, item in enumerate(items):
        item["index"] = index
    for item in items:
        venue_key = normalize_companion_key(item.get("venueLabel"))
        companions = []
        seen = set()
        for other in items:
            if other is item:
                continue
            same_venue = venue_key and normalize_companion_key(other.get("venueLabel")) == venue_key
            if not same_venue:
                continue
            if other["id"] in seen:
                continue
            seen.add(other["id"])
            companions.append(compact_event_reference(other))
        companions.sort(
            key=lambda value: (
                value.get("endDate") or "9999-12-31",
                value.get("startDate") or "9999-12-31",
                value.get("title") or "",
            )
        )
        item["companionEvents"] = companions


def load_events(conn, person_name):
    rows = conn.execute(
        """
        SELECT
          e.id,
          e.institution_id,
          e.content_type,
          i.name AS institution_name,
          e.title,
          e.start_date,
          e.end_date,
          e.location,
          e.region,
          e.price,
          e.description,
          e.keywords,
          e.event_nature,
          e.image_url,
          e.source_url,
          e.status,
          e.raw_text,
          COALESCE(r.score, 0) AS score
        FROM cultural_events e
        JOIN institutions i ON i.id = e.institution_id
        LEFT JOIN recommendations r
          ON r.event_id = e.id AND r.person_name = ?
        WHERE e.status != '종료'
          AND e.title NOT LIKE '%전시·교육 모니터%'
        ORDER BY
          COALESCE(r.score, 0) DESC,
          COALESCE(e.end_date, '9999-12-31'),
          e.start_date,
          e.title
        """,
        (person_name,),
    ).fetchall()
    related = load_related_links(conn, [row[0] for row in rows])
    items = []
    for row in rows:
        (
            event_id,
            institution_id,
            content_type,
            institution_name,
            title,
            start_date,
            end_date,
            location,
            region,
            price,
            description,
            keywords,
            event_nature,
            image_url,
            source_url,
            status,
            raw_text,
            score,
        ) = row
        remaining = days_until(end_date)
        starts_in = days_until(start_date)
        occurrences = load_occurrences(conn, event_id)
        next_occurrence = next(
            (
                occurrence
                for occurrence in occurrences
                if occurrence["date"] >= date.today().isoformat()
            ),
            occurrences[0] if occurrences else None,
        )
        urgency = ""
        if remaining is not None and 0 <= remaining <= 14:
            urgency = f"{remaining}일 남음"
        elif starts_in is not None and 0 <= starts_in <= 14:
            urgency = f"{starts_in}일 뒤 시작"
        venue_label = infer_venue_label(institution_name, location)
        display_venue = venue_label or institution_name
        detail_location = format_detail_location(venue_label, location or "확인 필요")
        keyword_list = keywords_with_nature(keywords, event_nature, content_type)
        item = {
            "id": event_id,
            "institutionId": institution_id,
            "type": content_type,
            "institution": institution_name,
            "venueLabel": venue_label,
            "displayVenue": display_venue,
            "eventNature": event_nature or "unknown",
            "natureLabel": nature_label(event_nature, content_type),
            "title": title,
            "displayTitle": display_title(title),
            "period": format_period(start_date, end_date, status),
            "startDate": start_date,
            "endDate": end_date,
            "location": location or "확인 필요",
            "detailLocation": detail_location,
            "region": region or "",
            "price": price or "",
            "status": status or "확인 필요",
            "keywords": keywords or "",
            "keywordList": keyword_list,
            "keywordMeta": keyword_meta(keyword_list),
            "imageUrl": usable_image_url(image_url),
            "sourceUrl": source_url,
            "score": float(score or 0),
            "urgency": urgency,
            "remainingDays": remaining,
            "startsInDays": starts_in,
            "isMajorInstitution": is_major_institution(institution_name),
            "description": display_description(description, raw_text),
            "occurrences": occurrences,
            "nextOccurrence": next_occurrence,
            "relatedLinks": related.get(event_id, []),
        }
        item["isPermanent"] = is_permanent_item(item)
        items.append(item)
    attach_companion_events(items)
    return items


def load_related_links(conn, event_ids):
    if not event_ids:
        return {}
    table_exists = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'related_links'
        """
    ).fetchone()
    if not table_exists:
        return {}
    placeholders = ",".join("?" for _ in event_ids)
    rows = conn.execute(
        f"""
        SELECT event_id, title, url, source, link_type
        FROM related_links
        WHERE event_id IN ({placeholders})
        ORDER BY event_id, rank, title
        """,
        event_ids,
    ).fetchall()
    links_by_event = {}
    for event_id, title, url, source, link_type in rows:
        links_by_event.setdefault(event_id, []).append(
            {
                "title": title,
                "url": url,
                "source": source,
                "type": link_type,
            }
        )
    return links_by_event


def type_counts(items):
    counts = {}
    for item in items:
        counts[item["type"]] = counts.get(item["type"], 0) + 1
    return counts


def is_permanent_item(item):
    if item.get("type") != "전시":
        return False
    if item.get("eventNature") == "permanent" or item.get("status") in {
        "상설전",
        "상설전시",
    }:
        return True
    title = f"{item.get('title') or ''} {item.get('displayTitle') or ''}"
    return "상설" in title


MAJOR_INSTITUTION_MARKERS = (
    "국립",
    "서울시립",
    "리움",
    "호암",
    "서울공예박물관",
    "경기도박물관",
    "경기도미술관",
)


def is_major_institution(name):
    text = str(name or "")
    return any(marker in text for marker in MAJOR_INSTITUTION_MARKERS)


def render(person_name="가족"):
    with sqlite3.connect(DEFAULT_DB) as conn:
        items = load_events(conn, person_name)
    indexed_items = list(enumerate(items))
    timed_indexed_items = [
        (index, item) for index, item in indexed_items if not is_permanent_item(item)
    ]
    permanent_indexed_items = [
        (index, item) for index, item in indexed_items if is_permanent_item(item)
    ]
    timed_items = [item for _, item in timed_indexed_items]
    permanent_items = [item for _, item in permanent_indexed_items]
    counts = type_counts(items)
    timed_counts = type_counts(timed_items)
    details_json = json.dumps(items, ensure_ascii=False).replace("</", "<\\/")
    count_text = " · ".join(f"{key} {value}건" for key, value in counts.items())
    timed_count_text = " · ".join(
        f"{key} {value}건" for key, value in timed_counts.items()
    )
    permanent_count_text = f"상설전 {len(permanent_items)}건"
    keyword_groups = [
        (
            "주제",
            [
                "현대미술",
                "역사",
                "한국미술",
                "공예",
                "디자인",
                "미디어아트",
                "한글",
                "건축",
                "사진",
            ],
        ),
        ("대상/참여", ["가족", "어린이", "참여형"]),
        ("일정", ["강연", "교육"]),
        ("방문 조건", ["무료", "주말"]),
    ]
    available_keywords = {
        keyword for item in timed_items for keyword in item.get("keywordList", [])
    }
    keyword_group_blocks = []
    for group_label, group_keywords in keyword_groups:
        visible_keywords = [
            keyword for keyword in group_keywords if keyword in available_keywords
        ]
        if not visible_keywords:
            continue
        buttons = "".join(
            f'<button class="choice-button" type="button" data-keyword-choice="{html.escape(keyword)}" aria-pressed="false">{html.escape(keyword)}</button>'
            for keyword in visible_keywords
        )
        keyword_group_blocks.append(
            f"""
            <div class="keyword-choice-line">
              <span class="choice-line-label">{html.escape(group_label)}</span>
              <div class="choice-row">{buttons}</div>
            </div>
            """
        )
    keyword_buttons = "".join(keyword_group_blocks)
    region_buttons = "".join(
        f'<button class="choice-button" type="button" data-region-choice="{html.escape(region)}" aria-pressed="{str(region == "all").lower()}">{label}</button>'
        for region, label in [
            ("all", "전체"),
            ("서울", "서울"),
            ("경기", "경기"),
            ("인천", "인천"),
        ]
    )
    type_buttons = "".join(
        f'<button class="choice-button" type="button" data-type-choice="{html.escape(value)}" aria-pressed="{str(value == "all").lower()}">{label}</button>'
        for value, label in [
            ("all", "전체"),
            ("전시", "전시"),
            ("program", "강연/교육"),
        ]
    )
    priority_buttons = "".join(
        f'<button class="choice-button" type="button" data-priority-choice="{html.escape(value)}" aria-pressed="{str(value == "recommended").lower()}">{label}</button>'
        for value, label in [
            ("recommended", "추천순"),
            ("deadline", "마감 임박"),
            ("limited", "기간한정"),
            ("major", "주요 기관"),
        ]
    )
    filter_order = ["전시", "강연", "교육", "행사"]
    filter_buttons = [
        '<button class="filter-button" type="button" data-filter="all" aria-pressed="true">전체</button>'
    ]
    for item_type in filter_order:
        if item_type in timed_counts:
            filter_buttons.append(
                f'<button class="filter-button" type="button" data-filter="{html.escape(item_type)}" aria-pressed="false">{html.escape(item_type)}</button>'
            )
    def render_card(index, item, class_name):
        image = item["imageUrl"]
        image_html = (
            f'<img src="{html.escape(image)}" alt="{html.escape(item["displayTitle"])}" loading="lazy">'
            if image
            else '<div class="poster-empty" aria-label="이미지 없음"></div>'
        )
        keyword_chips = "".join(
            keyword_chip_html(keyword) for keyword in item["keywordList"][:4]
        )
        keyword_html = (
            f'<div class="keyword-row" aria-label="추천 태그">{keyword_chips}</div>'
            if keyword_chips
            else ""
        )
        return f"""
        <article class="{class_name}" data-type="{html.escape(item['type'])}" data-feature-index="{index}">
          <button class="card-button" type="button" data-index="{index}">
            <div class="poster">{image_html}</div>
            <div class="card-body">
              <p class="card-place">{html.escape(item['displayVenue'])}</p>
              <h2>{html.escape(item['displayTitle'])}</h2>
              <p class="card-period">{html.escape(item['period'])}</p>
              {keyword_html}
            </div>
          </button>
        </article>
        """

    featured_cards = "".join(
        render_card(index, item, "card feature-card")
        for index, item in timed_indexed_items
    )
    all_cards = "".join(
        render_card(index, item, "card list-card")
        for index, item in timed_indexed_items
    )
    permanent_cards = "".join(
        render_card(index, item, "card list-card")
        for index, item in permanent_indexed_items
    )

    html_text = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>수도권 문화 일정 카드</title>
  <style>
    @import url("https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css");
    :root {{
      color-scheme: dark;
      --ink: #f7f4ee;
      --muted: #9ea4ad;
      --line: rgba(247, 244, 238, 0.14);
      --paper: #050505;
      --panel: #101010;
      --panel-2: #171717;
      --accent: #f0dfc2;
      --accent-ink: #11100d;
      --shadow: 0 26px 70px rgba(0, 0, 0, 0.56);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font-family: "Pretendard Variable", Pretendard, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
      line-height: 1.5;
    }}
    main {{
      width: min(1180px, calc(100% - 44px));
      margin: 0 auto;
      padding: 42px 0 86px;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: end;
      margin-bottom: 52px;
      padding-bottom: 22px;
      border-bottom: 1px solid var(--line);
    }}
    .eyebrow {{
      margin: 0 0 8px;
      color: var(--accent);
      font-size: 12px;
      font-weight: 900;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 34px;
      line-height: 1.16;
      letter-spacing: 0;
    }}
    .summary {{
      margin: 0;
      color: var(--muted);
      font-size: 14px;
    }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-end;
    }}
    .view-button,
    .filter-button {{
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #0d0d0d;
      color: var(--ink);
      padding: 0 14px;
      font-size: 13px;
      font-weight: 760;
      cursor: pointer;
    }}
    .view-button[aria-pressed="true"],
    .filter-button[aria-pressed="true"] {{
      border-color: var(--accent);
      background: var(--accent);
      color: var(--accent-ink);
    }}
    .recommendation-panel {{
      display: grid;
      gap: 18px;
      margin: -28px 0 46px;
      padding-bottom: 28px;
      border-bottom: 1px solid rgba(247, 244, 238, 0.09);
    }}
    .choice-group {{
      display: grid;
      gap: 8px;
    }}
    .choice-title {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      font-weight: 850;
    }}
    .keyword-stack {{
      display: grid;
      gap: 10px;
    }}
    .keyword-choice-line {{
      display: grid;
      grid-template-columns: 74px minmax(0, 1fr);
      gap: 10px;
      align-items: start;
    }}
    .choice-line-label {{
      padding-top: 7px;
      color: #7f858d;
      font-size: 11px;
      font-weight: 860;
    }}
    .choice-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .choice-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }}
    .choice-button,
    .reset-button {{
      min-height: 34px;
      border: 1px solid rgba(247, 244, 238, 0.15);
      border-radius: 999px;
      background: #0c0c0c;
      color: #d8d0c2;
      padding: 0 12px;
      font-size: 12px;
      font-weight: 780;
      cursor: pointer;
    }}
    .choice-button[aria-pressed="true"] {{
      border-color: var(--accent);
      background: var(--accent);
      color: var(--accent-ink);
    }}
    .recommendation-status {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      color: var(--muted);
      font-size: 13px;
    }}
    .recommendation-status p {{
      margin: 0;
    }}
    .empty-state {{
      display: grid;
      min-height: 180px;
      place-items: center;
      border: 1px solid rgba(247, 244, 238, 0.12);
      border-radius: 8px;
      color: var(--muted);
      font-size: 14px;
    }}
    .empty-state[hidden] {{
      display: none;
    }}
    .featured-view,
    .all-view,
    .permanent-view {{
      width: 100%;
    }}
    .featured-view[hidden],
    .all-view[hidden],
    .permanent-view[hidden] {{
      display: none;
    }}
    .feature-feed {{
      display: grid;
      gap: 82px;
      align-items: start;
      width: 100%;
      margin: 0 auto;
    }}
    .feature-card {{
      width: min(820px, 100%);
      justify-self: start;
    }}
    .feature-card.rank-even {{
      justify-self: end;
      margin-top: -26px;
    }}
    .list-toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      justify-content: flex-start;
      margin-bottom: 18px;
    }}
    .view-heading {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: baseline;
      margin-bottom: 18px;
      padding-bottom: 13px;
      border-bottom: 1px solid rgba(247, 244, 238, 0.1);
    }}
    .view-heading p {{
      margin: 0;
      color: var(--ink);
      font-size: 17px;
      font-weight: 860;
    }}
    .view-heading span {{
      color: var(--muted);
      font-size: 13px;
      font-weight: 760;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(238px, 1fr));
      gap: 18px;
      align-items: stretch;
    }}
    .card {{
      min-width: 0;
    }}
    .card[hidden] {{
      display: none;
    }}
    .card-button {{
      display: grid;
      grid-template-rows: auto 1fr;
      width: 100%;
      height: 100%;
      min-height: 0;
      padding: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: var(--panel);
      color: inherit;
      text-align: left;
      cursor: pointer;
      box-shadow: 0 10px 28px rgba(0, 0, 0, 0.26);
      transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
    }}
    .feature-card .card-button {{
      grid-template-columns: minmax(230px, 300px) minmax(0, 1fr);
      grid-template-rows: none;
      align-items: end;
      gap: 26px;
      overflow: visible;
      border: 0;
      border-radius: 0;
      background: transparent;
      box-shadow: none;
    }}
    .feature-card:first-child {{
      width: min(900px, 100%);
    }}
    .feature-card:first-child .card-button {{
      grid-template-columns: minmax(260px, 350px) minmax(0, 1fr);
    }}
    .feature-card.rank-even .card-button {{
      grid-template-columns: minmax(0, 1fr) minmax(230px, 300px);
    }}
    .feature-card.rank-even .poster {{
      grid-column: 2;
      grid-row: 1;
    }}
    .feature-card.rank-even .card-body {{
      grid-column: 1;
      grid-row: 1;
      justify-items: end;
      text-align: right;
    }}
    .feature-card.rank-even .keyword-row {{
      justify-content: flex-end;
    }}
    .card-button:hover,
    .card-button:focus-visible {{
      transform: translateY(-3px);
      border-color: rgba(217, 236, 255, 0.62);
      box-shadow: var(--shadow);
      outline: none;
    }}
    .feature-card .card-button:hover,
    .feature-card .card-button:focus-visible {{
      box-shadow: none;
    }}
    .feature-card .card-button:hover .poster,
    .feature-card .card-button:focus-visible .poster {{
      box-shadow: none;
    }}
    .feature-card .card-button:hover .poster img,
    .feature-card .card-button:focus-visible .poster img {{
      transform: translateY(-2px);
      box-shadow: 0 34px 90px rgba(0, 0, 0, 0.72);
    }}
    .poster {{
      aspect-ratio: 4 / 5.35;
      width: 100%;
      background: #151515;
      overflow: hidden;
    }}
    .feature-card .poster {{
      display: flex;
      align-items: flex-start;
      justify-content: center;
      aspect-ratio: auto;
      background: transparent;
      overflow: visible;
      box-shadow: none;
    }}
    .poster img {{
      width: 100%;
      height: 100%;
      display: block;
      object-fit: contain;
      object-position: center top;
      background: #080808;
    }}
    .feature-card .poster img {{
      width: 100%;
      height: auto;
      max-height: 540px;
      object-fit: contain;
      background: transparent;
      border-radius: 3px;
      box-shadow: 0 22px 62px rgba(0, 0, 0, 0.52);
      transition: transform 160ms ease, box-shadow 160ms ease;
    }}
    .poster-empty {{
      display: grid;
      place-items: center;
      height: 100%;
      color: #7f8da3;
      font-size: 13px;
      font-weight: 800;
      background: #171717;
    }}
    .poster-empty::after {{
      content: "이미지 준비 중";
    }}
    .feature-card .poster-empty {{
      width: 100%;
      min-height: 360px;
      border: 1px solid rgba(247, 244, 238, 0.12);
      border-radius: 3px;
      background: #111111;
    }}
    .card-body {{
      display: grid;
      align-content: start;
      gap: 7px;
      padding: 15px 15px 16px;
    }}
    .feature-card .card-body {{
      align-items: start;
      gap: 10px;
      max-width: 430px;
      padding: 0 0 14px;
    }}
    h2 {{
      margin: 0;
      font-size: 16px;
      line-height: 1.34;
      letter-spacing: 0;
    }}
    .feature-card h2 {{
      font-size: 26px;
      line-height: 1.18;
      font-weight: 780;
    }}
    .feature-card:first-child h2 {{
      font-size: 31px;
    }}
    .card-place {{
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      font-weight: 850;
    }}
    .feature-card .card-place {{
      color: var(--accent);
      font-size: 12px;
    }}
    .card-period {{
      margin: 0;
      color: #c7c2b7;
      font-size: 13px;
      font-weight: 700;
    }}
    .feature-card .card-period {{
      font-size: 15px;
      font-weight: 640;
    }}
    .keyword-row,
    .tag-list {{
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
    }}
    .keyword-row span,
    .tag-chip {{
      display: inline-flex;
      align-items: center;
      min-height: 23px;
      border: 1px solid var(--tag-border, #dfe5ee);
      border-radius: 999px;
      background: var(--tag-bg, #f8fafc);
      color: var(--tag-fg, #526173);
      padding: 2px 8px;
      font-size: 12px;
      font-weight: 800;
    }}
    .keyword-row span::before,
    .tag-chip::before {{
      content: "";
      width: 6px;
      height: 6px;
      margin-right: 6px;
      border-radius: 999px;
      background: var(--tag-dot, #94a3b8);
    }}
    .tag-layer-nature {{
      --tag-border: rgba(128, 178, 255, 0.62);
      --tag-bg: rgba(128, 178, 255, 0.13);
      --tag-fg: #c5dcff;
      --tag-dot: #8ab8ff;
    }}
    .tag-layer-field {{
      --tag-border: rgba(107, 211, 157, 0.62);
      --tag-bg: rgba(107, 211, 157, 0.13);
      --tag-fg: #bdf3d2;
      --tag-dot: #6bd39d;
    }}
    .tag-layer-audience {{
      --tag-border: rgba(211, 160, 255, 0.62);
      --tag-bg: rgba(211, 160, 255, 0.13);
      --tag-fg: #e4ccff;
      --tag-dot: #c89aff;
    }}
    .tag-layer-time {{
      --tag-border: rgba(240, 184, 116, 0.68);
      --tag-bg: rgba(240, 184, 116, 0.13);
      --tag-fg: #f5d0a7;
      --tag-dot: #e6a767;
    }}
    .tag-layer-format {{
      --tag-border: rgba(158, 174, 255, 0.62);
      --tag-bg: rgba(158, 174, 255, 0.13);
      --tag-fg: #d0d7ff;
      --tag-dot: #9eaeff;
    }}
    .tag-layer-access {{
      --tag-border: rgba(205, 224, 129, 0.62);
      --tag-bg: rgba(205, 224, 129, 0.12);
      --tag-fg: #e2edaa;
      --tag-dot: #c5d870;
    }}
    .tag-layer-place {{
      --tag-border: rgba(112, 216, 224, 0.62);
      --tag-bg: rgba(112, 216, 224, 0.12);
      --tag-fg: #bdeef2;
      --tag-dot: #70d8e0;
    }}
    .next-line {{
      display: grid;
      grid-template-columns: 36px 1fr;
      gap: 8px;
      align-items: baseline;
      padding: 8px 10px;
      border-radius: 6px;
      background: #111c23;
      color: var(--accent);
      font-size: 13px;
      font-weight: 800;
    }}
    .next-line span {{
      color: var(--muted);
      font-size: 12px;
    }}
    dl {{
      display: grid;
      gap: 6px;
      margin: 2px 0 0;
      font-size: 13px;
    }}
    dl div {{
      display: grid;
      grid-template-columns: 36px 1fr;
      gap: 8px;
    }}
    dt {{
      color: var(--muted);
    }}
    dd {{
      margin: 0;
    }}
    .overlay {{
      position: fixed;
      inset: 0;
      z-index: 20;
      display: grid;
      place-items: center;
      padding: 22px;
      background: rgba(0, 0, 0, 0.72);
    }}
    .overlay[hidden] {{
      display: none;
    }}
    .detail-panel {{
      width: min(980px, 100%);
      max-height: min(820px, calc(100vh - 44px));
      overflow: auto;
      border-radius: 8px;
      border: 1px solid var(--line);
      background: #101620;
      box-shadow: 0 30px 90px rgba(0, 0, 0, 0.62);
    }}
    .detail-layout {{
      display: grid;
      grid-template-columns: minmax(250px, 390px) 1fr;
    }}
    .detail-image {{
      display: flex;
      align-items: flex-start;
      justify-content: center;
      background: #0c1119;
      min-height: 100%;
      overflow: hidden;
    }}
    .detail-image img {{
      width: 100%;
      height: auto;
      max-height: min(760px, calc(100vh - 44px));
      display: block;
      object-fit: contain;
      object-position: top center;
      background: #0c1119;
    }}
    .detail-image .poster-empty {{
      width: 100%;
      min-height: 520px;
    }}
    .detail-body {{
      padding: 24px;
    }}
    .detail-top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      margin-bottom: 14px;
    }}
    .detail-kicker {{
      margin: 0 0 6px;
      color: var(--muted);
      font-size: 14px;
      font-weight: 700;
    }}
    .detail-title {{
      margin: 0;
      font-size: 28px;
      line-height: 1.25;
      letter-spacing: 0;
    }}
    .close-button {{
      flex: 0 0 auto;
      width: 38px;
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #141c28;
      color: var(--ink);
      font-size: 18px;
      cursor: pointer;
    }}
    .detail-description {{
      margin: 18px 0;
      color: #cbd5e3;
      font-size: 15px;
    }}
    .detail-actions,
    .related-list,
    .companion-list {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .source-link,
    .related-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 38px;
      border-radius: 6px;
      padding: 0 12px;
      font-size: 13px;
      font-weight: 800;
      text-decoration: none;
    }}
    .source-link {{
      background: var(--accent);
      color: var(--accent-ink);
    }}
    .schedule-section,
    .tag-section,
    .companion-section,
    .related-links {{
      margin-top: 18px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
    }}
    .section-title,
    .related-title {{
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 800;
    }}
    .related-link {{
      border: 1px solid var(--line);
      background: #121722;
      color: var(--ink);
    }}
    .occurrence-list {{
      display: grid;
      gap: 8px;
    }}
    .occurrence-item {{
      display: grid;
      grid-template-columns: minmax(110px, 0.42fr) 1fr;
      gap: 10px;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #121722;
    }}
    .occurrence-item.is-past {{
      opacity: 0.58;
    }}
    .occurrence-date {{
      color: var(--ink);
      font-size: 13px;
      font-weight: 900;
    }}
    .occurrence-main {{
      display: grid;
      gap: 3px;
      color: #cbd5e3;
      font-size: 13px;
    }}
    .occurrence-time {{
      font-weight: 800;
    }}
    .occurrence-note {{
      color: var(--muted);
      font-size: 12px;
    }}
    .companion-button {{
      flex: 1 1 210px;
      min-height: 74px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #121722;
      color: var(--ink);
      padding: 10px;
      text-align: left;
      cursor: pointer;
    }}
    .companion-button:hover,
    .companion-button:focus-visible {{
      border-color: var(--accent);
      outline: none;
    }}
    .companion-type {{
      display: block;
      margin-bottom: 4px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 900;
    }}
    .companion-title {{
      display: block;
      font-size: 13px;
      font-weight: 850;
      line-height: 1.35;
    }}
    .companion-period {{
      display: block;
      margin-top: 5px;
      color: var(--muted);
      font-size: 12px;
    }}
    .modal-open {{
      overflow: hidden;
    }}
    @media (max-width: 760px) {{
      main {{
        width: min(100% - 24px, 1160px);
        padding-top: 20px;
      }}
      header {{
        display: block;
      }}
      h1 {{
        font-size: 26px;
      }}
      .toolbar {{
        justify-content: flex-start;
        margin-top: 14px;
      }}
      .recommendation-panel {{
        margin: -24px 0 34px;
        gap: 16px;
        padding-bottom: 24px;
      }}
      .choice-grid {{
        grid-template-columns: 1fr;
        gap: 12px;
      }}
      .keyword-stack {{
        gap: 12px;
      }}
      .keyword-choice-line {{
        grid-template-columns: 1fr;
        gap: 6px;
      }}
      .choice-line-label {{
        padding-top: 0;
      }}
      .choice-button,
      .reset-button {{
        min-height: 36px;
      }}
      .recommendation-status {{
        display: grid;
        justify-content: stretch;
      }}
      .feature-feed {{
        grid-template-columns: 1fr;
        gap: 34px;
      }}
      .feature-card,
      .feature-card.rank-even,
      .feature-card:nth-child(4n+3) {{
        width: 100%;
        justify-self: stretch;
        margin-top: 0;
      }}
      .feature-card .card-button,
      .feature-card:first-child .card-button,
      .feature-card.rank-even .card-button {{
        grid-template-columns: 1fr;
        gap: 14px;
      }}
      .feature-card.rank-even .poster,
      .feature-card.rank-even .card-body {{
        grid-column: auto;
        grid-row: auto;
      }}
      .feature-card.rank-even .card-body {{
        justify-items: start;
        text-align: left;
      }}
      .feature-card.rank-even .keyword-row {{
        justify-content: flex-start;
      }}
      .feature-card h2,
      .feature-card:first-child h2 {{
        font-size: 22px;
      }}
      .feature-card .card-body {{
        width: 100%;
        max-width: none;
        padding-bottom: 0;
      }}
      .grid {{
        grid-template-columns: repeat(auto-fill, minmax(172px, 1fr));
        gap: 10px;
      }}
      .list-card .card-button {{
        min-height: 370px;
      }}
      .card-body {{
        padding: 12px;
      }}
      h2 {{
        font-size: 15px;
      }}
      .overlay {{
        padding: 10px;
      }}
      .detail-layout {{
        grid-template-columns: 1fr;
      }}
      .detail-image img {{
        min-height: 0;
        max-height: 420px;
        object-fit: contain;
      }}
      .detail-image .poster-empty {{
        min-height: 260px;
      }}
      .detail-title {{
        font-size: 22px;
      }}
      .occurrence-item {{
        grid-template-columns: 1fr;
        gap: 4px;
      }}
      .companion-button {{
        flex-basis: 100%;
      }}
    }}
  </style>
</head>
<body class="view-featured">
  <main>
    <header>
      <div>
        <p class="eyebrow">관심 기반 추천</p>
        <h1>{html.escape(person_name)} 관심 문화 일정</h1>
        <p class="summary">진행/예정 {len(items)}건 · {html.escape(count_text)}</p>
      </div>
      <div class="toolbar" aria-label="보기 전환">
        <button class="view-button" type="button" data-view="featured" aria-pressed="true">추천 보기</button>
        <button class="view-button" type="button" data-view="all" aria-pressed="false">기간 일정</button>
        <button class="view-button" type="button" data-view="permanent" aria-pressed="false">상설전</button>
      </div>
    </header>
    <section class="recommendation-panel" aria-label="관심 기반 추천 설정">
      <div class="choice-group">
        <p class="choice-title">관심 키워드</p>
        <div class="keyword-stack" id="keywordChoices">
          {keyword_buttons}
        </div>
      </div>
      <div class="choice-grid">
        <div class="choice-group">
          <p class="choice-title">지역</p>
          <div class="choice-row">
            {region_buttons}
          </div>
        </div>
        <div class="choice-group">
          <p class="choice-title">일정</p>
          <div class="choice-row">
            {type_buttons}
          </div>
        </div>
        <div class="choice-group">
          <p class="choice-title">우선</p>
          <div class="choice-row">
            {priority_buttons}
          </div>
        </div>
      </div>
      <div class="recommendation-status">
        <p id="recommendationSummary"></p>
        <button class="reset-button" type="button" id="resetRecommendation">초기화</button>
      </div>
    </section>
    <section class="featured-view" id="featuredView" aria-label="추천 일정">
      <div class="feature-feed" id="featureFeed">
        {featured_cards}
      </div>
      <div class="empty-state" id="emptyRecommendations" hidden>조건에 맞는 일정이 없어요.</div>
    </section>
    <section class="all-view" id="allView" aria-label="기간 일정" hidden>
      <div class="view-heading">
        <p>기간 일정</p>
        <span>{html.escape(timed_count_text or "0건")}</span>
      </div>
      <div class="list-toolbar" aria-label="일정 필터">
        {"".join(filter_buttons)}
      </div>
      <div class="grid" id="cardGrid">
        {all_cards}
      </div>
    </section>
    <section class="permanent-view" id="permanentView" aria-label="상설전" hidden>
      <div class="view-heading">
        <p>상설전</p>
        <span>{html.escape(permanent_count_text)}</span>
      </div>
      <div class="grid" id="permanentGrid">
        {permanent_cards}
      </div>
    </section>
  </main>

  <div class="overlay" id="detailOverlay" hidden>
    <section class="detail-panel" role="dialog" aria-modal="true" aria-labelledby="detailTitle">
      <div class="detail-layout">
        <div class="detail-image" id="detailImage"></div>
        <div class="detail-body">
          <div class="detail-top">
            <div>
              <p class="detail-kicker" id="detailKicker"></p>
              <h2 class="detail-title" id="detailTitle"></h2>
            </div>
            <button class="close-button" type="button" id="detailClose" aria-label="닫기">×</button>
          </div>
          <dl>
            <div><dt>기간</dt><dd id="detailPeriod"></dd></div>
            <div><dt>장소</dt><dd id="detailLocation"></dd></div>
            <div><dt>상태</dt><dd id="detailStatus"></dd></div>
            <div><dt>가격</dt><dd id="detailPrice"></dd></div>
          </dl>
          <p class="detail-description" id="detailDescription"></p>
          <div class="tag-section" id="detailTags"></div>
          <div class="schedule-section" id="detailSchedule"></div>
          <div class="companion-section" id="detailCompanions"></div>
          <div class="detail-actions">
            <a class="source-link" id="detailSource" href="#" target="_blank" rel="noopener">원문 보기</a>
          </div>
          <div class="related-links" id="detailRelated"></div>
        </div>
      </div>
    </section>
  </div>

  <script>
    const items = {details_json};
    const overlay = document.getElementById("detailOverlay");
    const imageBox = document.getElementById("detailImage");
    const closeButton = document.getElementById("detailClose");
    const featuredView = document.getElementById("featuredView");
    const allView = document.getElementById("allView");
    const permanentView = document.getElementById("permanentView");
    const featureFeed = document.getElementById("featureFeed");
    const emptyRecommendations = document.getElementById("emptyRecommendations");
    const recommendationSummary = document.getElementById("recommendationSummary");
    const resetRecommendation = document.getElementById("resetRecommendation");
    const featureCards = Array.from(document.querySelectorAll("#featuredView .feature-card"));
    const featureCardByIndex = new Map(
      featureCards.map((card) => [Number(card.dataset.featureIndex), card])
    );
    const selectedKeywords = new Set();
    const recommendationState = {{
      region: "all",
      type: "all",
      priority: "recommended"
    }};
    const fields = {{
      kicker: document.getElementById("detailKicker"),
      title: document.getElementById("detailTitle"),
      period: document.getElementById("detailPeriod"),
      location: document.getElementById("detailLocation"),
      status: document.getElementById("detailStatus"),
      price: document.getElementById("detailPrice"),
      description: document.getElementById("detailDescription"),
      source: document.getElementById("detailSource"),
      tags: document.getElementById("detailTags"),
      schedule: document.getElementById("detailSchedule"),
      companions: document.getElementById("detailCompanions"),
      related: document.getElementById("detailRelated")
    }};

    function numeric(value) {{
      return typeof value === "number" && Number.isFinite(value) ? value : null;
    }}

    function keywordMatches(item, keyword) {{
      const keywords = item.keywordList || [];
      if (keywords.includes(keyword)) return true;
      const text = [
        item.displayTitle,
        item.title,
        item.description,
        item.displayVenue,
        item.institution
      ].filter(Boolean).join(" ");
      return text.includes(keyword);
    }}

    function selectedKeywordCount(item) {{
      let count = 0;
      selectedKeywords.forEach((keyword) => {{
        if (keywordMatches(item, keyword)) count += 1;
      }});
      return count;
    }}

    function passesRecommendationFilters(item) {{
      if (item.isPermanent) {{
        return false;
      }}
      if (recommendationState.region !== "all" && item.region !== recommendationState.region) {{
        return false;
      }}
      if (recommendationState.type === "program") {{
        if (!["강연", "교육", "행사"].includes(item.type)) return false;
      }} else if (recommendationState.type !== "all" && item.type !== recommendationState.type) {{
        return false;
      }}
      return selectedKeywords.size === 0 || selectedKeywordCount(item) > 0;
    }}

    function urgencyScore(item) {{
      const remaining = numeric(item.remainingDays);
      const startsIn = numeric(item.startsInDays);
      let score = 0;
      if (remaining !== null) {{
        if (remaining < 0) score -= 30;
        else if (remaining <= 7) score += 18;
        else if (remaining <= 14) score += 12;
        else if (remaining <= 30) score += 7;
        else if (remaining <= 60) score += 3;
      }}
      if (startsIn !== null) {{
        if (startsIn >= 0 && startsIn <= 14) score += 5;
        else if (startsIn > 14 && startsIn <= 30) score += 2;
      }}
      return score;
    }}

    function natureScore(item) {{
      if (item.eventNature === "limited") return 8;
      if (item.eventNature === "long_term") return 2;
      if (item.eventNature === "permanent") return -4;
      return 0;
    }}

    function scoreRecommendation(item, index) {{
      const matchedKeywords = selectedKeywordCount(item);
      let score = Number(item.score || 0) * 2;

      if (selectedKeywords.size > 0) {{
        score += matchedKeywords * 24;
      }} else {{
        score += urgencyScore(item) * 0.7;
      }}

      score += urgencyScore(item);
      score += natureScore(item);
      if (item.imageUrl) score += 1.5;
      if ((item.occurrences || []).length) score += 1;

      if (recommendationState.priority === "deadline") {{
        score += urgencyScore(item) * 1.8;
      }} else if (recommendationState.priority === "limited") {{
        score += item.eventNature === "limited" ? 18 : -2;
      }} else if (recommendationState.priority === "major") {{
        score += item.isMajorInstitution ? 16 : -2;
      }}

      return score - index * 0.01;
    }}

    function priorityLabel() {{
      if (recommendationState.priority === "deadline") return "마감 임박";
      if (recommendationState.priority === "limited") return "기간한정";
      if (recommendationState.priority === "major") return "주요 기관";
      return "추천순";
    }}

    function applyRecommendations() {{
      const ranked = items
        .map((item, index) => ({{ item, index, score: scoreRecommendation(item, index) }}))
        .filter((entry) => passesRecommendationFilters(entry.item))
        .sort((a, b) => b.score - a.score);
      const visible = ranked.slice(0, 12);

      featureCards.forEach((card) => {{
        card.hidden = true;
        card.classList.remove("rank-even");
      }});

      visible.forEach((entry, order) => {{
        const card = featureCardByIndex.get(entry.index);
        if (!card) return;
        card.classList.toggle("rank-even", order % 2 === 1);
        card.hidden = false;
        featureFeed.appendChild(card);
      }});

      const basis = [];
      basis.push(selectedKeywords.size ? Array.from(selectedKeywords).join(", ") : "기본 추천");
      basis.push(recommendationState.region === "all" ? "전체 지역" : recommendationState.region);
      basis.push(priorityLabel());
      recommendationSummary.textContent =
        ranked.length + "건 중 " + visible.length + "건 표시 · " + basis.join(" · ");
      emptyRecommendations.hidden = visible.length > 0;
    }}

    function setSingleChoice(selector, value) {{
      document.querySelectorAll(selector).forEach((button) => {{
        const pressed =
          button.dataset.regionChoice === value ||
          button.dataset.typeChoice === value ||
          button.dataset.priorityChoice === value;
        button.setAttribute("aria-pressed", String(pressed));
      }});
    }}

    function resetRecommendationState() {{
      selectedKeywords.clear();
      recommendationState.region = "all";
      recommendationState.type = "all";
      recommendationState.priority = "recommended";
      document.querySelectorAll("[data-keyword-choice]").forEach((button) => {{
        button.setAttribute("aria-pressed", "false");
      }});
      setSingleChoice("[data-region-choice]", "all");
      setSingleChoice("[data-type-choice]", "all");
      setSingleChoice("[data-priority-choice]", "recommended");
      applyRecommendations();
    }}

    function fillImage(item) {{
      imageBox.textContent = "";
      if (item.imageUrl) {{
        const img = document.createElement("img");
        img.src = item.imageUrl;
        img.alt = item.displayTitle || item.title;
        imageBox.appendChild(img);
      }} else {{
        const empty = document.createElement("div");
        empty.className = "poster-empty";
        imageBox.appendChild(empty);
      }}
    }}

    function fillRelated(item) {{
      fields.related.textContent = "";
      if (!item.relatedLinks || !item.relatedLinks.length) {{
        fields.related.hidden = true;
        return;
      }}
      const title = document.createElement("p");
      title.className = "related-title";
      title.textContent = "후기/검색";
      const list = document.createElement("div");
      list.className = "related-list";
      item.relatedLinks.forEach((link) => {{
        const anchor = document.createElement("a");
        anchor.className = "related-link";
        anchor.href = link.url;
        anchor.target = "_blank";
        anchor.rel = "noopener";
        anchor.textContent = link.title;
        list.appendChild(anchor);
      }});
      fields.related.appendChild(title);
      fields.related.appendChild(list);
      fields.related.hidden = false;
    }}

    function makeSectionTitle(text) {{
      const title = document.createElement("p");
      title.className = "section-title";
      title.textContent = text;
      return title;
    }}

    function fillTags(item) {{
      fields.tags.textContent = "";
      const keywords = item.keywordMeta || (item.keywordList || []).map((label) => ({{ label, layer: "other" }}));
      if (!keywords.length) {{
        fields.tags.hidden = true;
        return;
      }}
      fields.tags.appendChild(makeSectionTitle("추천 태그"));
      const list = document.createElement("div");
      list.className = "tag-list";
      keywords.slice(0, 14).forEach((keyword) => {{
        const chip = document.createElement("span");
        chip.className = "tag-chip tag-layer-" + (keyword.layer || "other");
        chip.textContent = keyword.label || keyword;
        list.appendChild(chip);
      }});
      fields.tags.appendChild(list);
      fields.tags.hidden = false;
    }}

    function fillSchedule(item) {{
      fields.schedule.textContent = "";
      const occurrences = item.occurrences || [];
      if (!occurrences.length) {{
        fields.schedule.hidden = true;
        return;
      }}
      fields.schedule.appendChild(makeSectionTitle("세부 회차 " + occurrences.length + "개"));
      const list = document.createElement("div");
      list.className = "occurrence-list";
      occurrences.forEach((occurrence) => {{
        const row = document.createElement("div");
        row.className = "occurrence-item" + (occurrence.isPast ? " is-past" : "");

        const dateBox = document.createElement("div");
        dateBox.className = "occurrence-date";
        dateBox.textContent = occurrence.dateText || occurrence.date || "날짜 확인 필요";

        const main = document.createElement("div");
        main.className = "occurrence-main";

        const time = document.createElement("span");
        time.className = "occurrence-time";
        time.textContent = occurrence.time || "시간 확인 필요";
        main.appendChild(time);

        const detailParts = [occurrence.label, occurrence.note].filter(Boolean);
        if (detailParts.length) {{
          const note = document.createElement("span");
          note.className = "occurrence-note";
          note.textContent = detailParts.join(" · ");
          main.appendChild(note);
        }}

        row.appendChild(dateBox);
        row.appendChild(main);
        list.appendChild(row);
      }});
      fields.schedule.appendChild(list);
      fields.schedule.hidden = false;
    }}

    function fillCompanions(item) {{
      fields.companions.textContent = "";
      const companions = item.companionEvents || [];
      if (!companions.length) {{
        fields.companions.hidden = true;
        return;
      }}
      fields.companions.appendChild(makeSectionTitle("같은 실제 장소의 다른 일정 " + companions.length + "개"));
      const list = document.createElement("div");
      list.className = "companion-list";
      companions.forEach((event) => {{
        const button = document.createElement("button");
        button.type = "button";
        button.className = "companion-button";
        button.addEventListener("click", () => openDetail(event.index));

        const type = document.createElement("span");
        type.className = "companion-type";
        type.textContent = event.type + " · " + event.displayVenue;

        const title = document.createElement("span");
        title.className = "companion-title";
        title.textContent = event.title;

        const period = document.createElement("span");
        period.className = "companion-period";
        period.textContent = event.nextOccurrence
          ? "다음 " + event.nextOccurrence.dateText + " " + event.nextOccurrence.time
          : event.period;

        button.appendChild(type);
        button.appendChild(title);
        button.appendChild(period);
        list.appendChild(button);
      }});
      fields.companions.appendChild(list);
      fields.companions.hidden = false;
    }}

    function openDetail(index) {{
      const item = items[index];
      if (!item) return;
      fillImage(item);
      fields.kicker.textContent = `${{item.type}} · ${{item.displayVenue}}`;
      fields.title.textContent = item.displayTitle || item.title;
      fields.period.textContent = item.period;
      fields.location.textContent = item.detailLocation || item.location;
      fields.status.textContent = item.status;
      fields.price.textContent = item.price || "확인 필요";
      fields.description.textContent = item.description || "추가 설명은 원문에서 확인할 수 있습니다.";
      fields.source.href = item.sourceUrl;
      fillTags(item);
      fillSchedule(item);
      fillCompanions(item);
      fillRelated(item);
      overlay.hidden = false;
      document.body.classList.add("modal-open");
      closeButton.focus();
    }}

    function closeDetail() {{
      overlay.hidden = true;
      document.body.classList.remove("modal-open");
    }}

    document.querySelectorAll("[data-index]").forEach((button) => {{
      button.addEventListener("click", () => openDetail(Number(button.dataset.index)));
    }});
    document.querySelectorAll("[data-view]").forEach((button) => {{
      button.addEventListener("click", () => {{
        const view = button.dataset.view;
        document.querySelectorAll("[data-view]").forEach((other) => {{
          other.setAttribute("aria-pressed", String(other === button));
        }});
        featuredView.hidden = view !== "featured";
        allView.hidden = view !== "all";
        permanentView.hidden = view !== "permanent";
        document.body.classList.toggle("view-featured", view === "featured");
        document.body.classList.toggle("view-all", view === "all");
        document.body.classList.toggle("view-permanent", view === "permanent");
      }});
    }});
    document.querySelectorAll("[data-keyword-choice]").forEach((button) => {{
      button.addEventListener("click", () => {{
        const keyword = button.dataset.keywordChoice;
        if (selectedKeywords.has(keyword)) {{
          selectedKeywords.delete(keyword);
          button.setAttribute("aria-pressed", "false");
        }} else {{
          selectedKeywords.add(keyword);
          button.setAttribute("aria-pressed", "true");
        }}
        applyRecommendations();
      }});
    }});
    document.querySelectorAll("[data-region-choice]").forEach((button) => {{
      button.addEventListener("click", () => {{
        recommendationState.region = button.dataset.regionChoice;
        setSingleChoice("[data-region-choice]", recommendationState.region);
        applyRecommendations();
      }});
    }});
    document.querySelectorAll("[data-type-choice]").forEach((button) => {{
      button.addEventListener("click", () => {{
        recommendationState.type = button.dataset.typeChoice;
        setSingleChoice("[data-type-choice]", recommendationState.type);
        applyRecommendations();
      }});
    }});
    document.querySelectorAll("[data-priority-choice]").forEach((button) => {{
      button.addEventListener("click", () => {{
        recommendationState.priority = button.dataset.priorityChoice;
        setSingleChoice("[data-priority-choice]", recommendationState.priority);
        applyRecommendations();
      }});
    }});
    resetRecommendation.addEventListener("click", resetRecommendationState);
    closeButton.addEventListener("click", closeDetail);
    overlay.addEventListener("click", (event) => {{
      if (event.target === overlay) closeDetail();
    }});
    document.addEventListener("keydown", (event) => {{
      if (event.key === "Escape" && !overlay.hidden) closeDetail();
    }});

    document.querySelectorAll("[data-filter]").forEach((button) => {{
      button.addEventListener("click", () => {{
        const filter = button.dataset.filter;
        document.querySelectorAll("[data-filter]").forEach((other) => {{
          other.setAttribute("aria-pressed", String(other === button));
        }});
        document.querySelectorAll("#allView .card").forEach((card) => {{
          card.hidden = filter !== "all" && card.dataset.type !== filter;
        }});
      }});
    }});
    applyRecommendations();
  </script>
</body>
</html>
"""
    OUTPUT_PATH.write_text(html_text, encoding="utf-8")
    return len(items), counts


def main():
    total, counts = render()
    print(f"cards={total}")
    for key, value in counts.items():
        print(f"{key}={value}")
    print(f"html={OUTPUT_PATH}")


if __name__ == "__main__":
    main()
