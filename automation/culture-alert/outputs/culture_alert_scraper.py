import argparse
import csv
import html
import json
import re
import sqlite3
import ssl
from datetime import date
from pathlib import Path
from urllib.parse import quote, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from culture_image_utils import clean_image_url

try:
    from lxml import html as lxml_html
except ImportError:  # pragma: no cover - bundled runtime includes lxml.
    lxml_html = None


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "culture-alert.sqlite"
REPORT_PATH = BASE_DIR / "latest-collection-report.md"
OFFICIAL_PAGE_MONITOR_REPORT = BASE_DIR / "official-page-monitor-report.md"
INSTITUTION_CSV = BASE_DIR / "expanded-institution-candidates.csv"

OFFICIAL_PAGE_FETCH_OVERRIDES = {
    "https://www.bok.or.kr/museum/": "https://www.bok.or.kr/museum/main/main.do",
    "https://whankimuseum.org/now/": "http://whankimuseum.org/exhibition_category/exhibition_now/",
    "https://museum.seoul.go.kr/scwm/board/NR_boardView.do?bbsCd=1080&seq=20260623174312968": "https://museum.seoul.go.kr/www/board/NR_boardView.do?bbsCd=1002&seq=20260623174312968",
}


def clean_text(value):
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def clean_href(value):
    return (value or "").replace("&amp;", "&")


def first_match(pattern, value, flags=re.S):
    match = re.search(pattern, value, flags=flags)
    return match.group(1) if match else None


SEMA_BRANCH_ALIASES = (
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
)

BRANCH_INSTITUTION_DEFAULTS = {
    "서울시립 사진미술관": {
        "region": "서울",
        "city": "도봉구",
        "category": "미술관",
        "priority": 2,
        "collection_phase": "phase2",
        "exhibition_url": "https://sema.seoul.go.kr/",
        "program_url": "https://sema.seoul.go.kr/kr/whatson/landing",
        "notes": "서울시립미술관 분관. 서울시립미술관 통합 페이지에서 수집",
    },
    "전곡선사박물관": {
        "region": "경기",
        "city": "연천군",
        "category": "박물관",
        "priority": 2,
        "collection_phase": "phase2",
        "exhibition_url": "https://jgpm.ggcf.kr/exhibitions",
        "program_url": "https://jgpm.ggcf.kr/edus",
        "notes": "경기문화재단 계열. 전시/교육 목록을 분리 수집",
    },
    "경기도어린이박물관": {
        "region": "경기",
        "city": "용인시",
        "category": "박물관",
        "priority": 2,
        "collection_phase": "phase2",
        "exhibition_url": "https://gcm.ggcf.kr/exhibitions",
        "program_url": "https://gcm.ggcf.kr/edus",
        "notes": "경기문화재단 계열. 상설전시와 어린이 교육 프로그램을 분리 수집",
    },
    "서울생활사박물관": {
        "region": "서울",
        "city": "노원구",
        "category": "박물관",
        "priority": 2,
        "collection_phase": "phase2",
        "exhibition_url": "https://museum.seoul.go.kr/",
        "program_url": "https://museum.seoul.go.kr/",
        "notes": "서울역사박물관 통합 전시 목록에서 분관명으로 수집",
    },
    "청계천박물관": {
        "region": "서울",
        "city": "성동구",
        "category": "박물관",
        "priority": 2,
        "collection_phase": "phase2",
        "exhibition_url": "https://museum.seoul.go.kr/",
        "program_url": "https://museum.seoul.go.kr/",
        "notes": "서울역사박물관 통합 전시 목록에서 분관명으로 수집",
    },
    "한양도성박물관": {
        "region": "서울",
        "city": "종로구",
        "category": "박물관",
        "priority": 2,
        "collection_phase": "phase2",
        "exhibition_url": "https://museum.seoul.go.kr/",
        "program_url": "https://museum.seoul.go.kr/",
        "notes": "서울역사박물관 통합 전시 목록에서 분관명으로 수집",
    },
    "서울우리소리박물관": {
        "region": "서울",
        "city": "종로구",
        "category": "박물관",
        "priority": 2,
        "collection_phase": "phase2",
        "exhibition_url": "https://gomuseum.seoul.go.kr/",
        "program_url": "https://gomuseum.seoul.go.kr/",
        "notes": "서울역사박물관 통합 전시 목록과 서울우리소리박물관 사이트를 병행 확인",
    },
    "실학박물관": {
        "region": "경기",
        "city": "남양주시",
        "category": "박물관",
        "priority": 2,
        "collection_phase": "phase2",
        "exhibition_url": "https://silhak.ggcf.kr/exhibitions",
        "program_url": "https://silhak.ggcf.kr/edus",
        "notes": "경기문화재단 계열. 기존 전시 수집기 적용",
    },
}


def infer_sema_institution_name(location):
    text = clean_text(location or "")
    for branch_name, aliases in SEMA_BRANCH_ALIASES:
        if any(alias in text for alias in aliases):
            return branch_name
    if not text:
        return "서울시립미술관"
    return "서울시립미술관"


def fetch_html(url):
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 culture-alert prototype; contact=personal-use"
        },
    )
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, "replace")


def fetch_json(url, params, referer="https://www.leeumhoam.org/leeum/exhibition"):
    query = urlencode(params)
    headers = {
        "User-Agent": "Mozilla/5.0 culture-alert prototype; contact=personal-use",
        "X-Requested-With": "XMLHttpRequest",
    }
    if referer:
        headers["Referer"] = referer
    request = Request(
        f"{url}?{query}",
        headers=headers,
    )
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return json.loads(response.read().decode(charset, "replace"))


def ensure_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS event_occurrences (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          event_id INTEGER NOT NULL REFERENCES cultural_events(id) ON DELETE CASCADE,
          occurrence_date TEXT NOT NULL,
          start_time TEXT,
          end_time TEXT,
          label TEXT,
          note TEXT,
          source_url TEXT,
          confidence INTEGER NOT NULL DEFAULT 5,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(event_id, occurrence_date, COALESCE(start_time, ''), COALESCE(label, ''))
        )
        """
    )
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(cultural_events)").fetchall()
    }
    if "image_url" not in columns:
        conn.execute("ALTER TABLE cultural_events ADD COLUMN image_url TEXT")
    if "event_nature" not in columns:
        conn.execute("ALTER TABLE cultural_events ADD COLUMN event_nature TEXT NOT NULL DEFAULT 'unknown'")


def parse_date_range(value):
    value = html.unescape(value or "")
    value = re.sub(r"\([^)]{1,10}\)", "", value)
    value = (
        value.replace("\xa0", " ")
        .replace("–", "~")
        .replace("—", "~")
        .replace("－", "~")
    )
    match = re.search(r"(\d{4}-\d{2}-\d{2})\s*(?:~|-)\s*(\d{4}-\d{2}-\d{2})", value)
    if match:
        return match.group(1), match.group(2)
    match = re.search(
        r"(\d{4})[./년-]\s*(\d{1,2})[./월-]\s*(\d{1,2})[.일]?\s*~\s*(?:(\d{4})[./년-]\s*)?(\d{1,2})[./월-]\s*(\d{1,2})",
        value,
    )
    if match:
        end_year = match.group(4) or match.group(1)
        start_date = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        end_date = f"{end_year}-{int(match.group(5)):02d}-{int(match.group(6)):02d}"
        return start_date, end_date
    match = re.search(r"(\d{4})[./](\d{1,2})[./](\d{1,2})\s*~\s*(?:(\d{4})[./](\d{1,2})[./](\d{1,2}))?", value)
    if match:
        start_date = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        end_date = None
        if match.group(4):
            end_date = f"{match.group(4)}-{int(match.group(5)):02d}-{int(match.group(6)):02d}"
        return start_date, end_date
    dates = []
    for match in re.finditer(r"(\d{4})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})", value):
        dates.append(f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}")
    if not dates:
        return None, None
    if len(dates) == 1:
        return dates[0], None
    return dates[0], dates[1]


def image_from_block(base_url, block):
    src = first_match(r'<img[^>]+src="([^"]+)"', block)
    if not src:
        src = first_match(r"background(?:-image)?:\s*url\(['\"]?([^'\")]+)", block)
    if not src:
        return None
    src = html.unescape(src).strip()
    image = urljoin(base_url, src)
    return clean_image_url(image)


def table_value(block, *labels):
    for label in labels:
        match = re.search(
            rf"<th>\s*{re.escape(label)}\s*</th>\s*<td[^>]*>(.*?)</td>",
            block,
            flags=re.S,
        )
        if match:
            return clean_text(match.group(1))
    return ""


def extract_ggcf_card_entries(institution_name, base_url, path, content_type):
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    page = fetch_html(url)
    starts = list(re.finditer(r'<li>\s*<div class="exhibition-img-area"', page))
    events = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else page.find("</ul>", match.start())
        if end == -1:
            end = page.find("</main>", match.start())
        if end == -1:
            end = match.start() + 5000
        block = page[match.start():end]
        title = clean_text(first_match(r"<h4>(.*?)</h4>", block) or "")
        if not title:
            continue
        href = (
            first_match(r'<a class="link-plus" href="([^"]+)"', block)
            or first_match(r'<div class="detail-page-url-box">\s*<a href="([^"]+)"', block)
        )
        source_url = urljoin(url, clean_href(href)) if href else url
        if content_type == "전시":
            date_text = table_value(block, "기간")
        else:
            date_text = table_value(block, "교육기간", "행사기간", "접수기간")
        start_date, end_date = parse_date_range(date_text)
        location = table_value(block, "장소")
        price = table_value(block, "참가비", "관람료")
        description = clean_text(first_match(r'<p class="list-pointer">(.*?)</p>', block) or "")
        tags = [
            clean_text(item).lstrip("#")
            for item in re.findall(r'<ul class="sns-mark[^"]*">(.*?)</ul>', block, flags=re.S)
            for item in re.findall(r"<a[^>]*>(.*?)</a>", item, flags=re.S)
        ]
        keywords = ";".join(tag for tag in tags if tag)
        if any(existing["source_url"] == source_url for existing in events):
            continue
        events.append(
            {
                "institution_name": institution_name,
                "content_type": content_type,
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": location,
                "region": "경기",
                "price": price or None,
                "description": description or None,
                "keywords": keywords or None,
                "image_url": image_from_block(url, block),
                "source_url": source_url,
                "status": infer_status(start_date, end_date),
                "raw_text": clean_text(block),
            }
        )
    if not events:
        raise RuntimeError(f"{institution_name} {content_type} 정보 블록을 찾지 못했습니다.")
    return events


def infer_status(start_date, end_date):
    today = date.today().isoformat()
    if start_date and today < start_date:
        return "예정"
    if end_date and today > end_date:
        return "종료"
    return "진행중"


def require_lxml():
    if lxml_html is None:
        raise RuntimeError("상세 HTML 파싱을 위해 lxml이 필요합니다.")


def doc_from_html(page):
    require_lxml()
    return lxml_html.fromstring(page)


def node_text(node):
    return clean_text(node.text_content())


def first_node_text(doc, xpath):
    nodes = doc.xpath(xpath)
    if not nodes:
        return ""
    value = nodes[0]
    if isinstance(value, str):
        return clean_text(value)
    return node_text(value)


def parse_single_date(value):
    match = re.search(r"(20\d{2})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})", value or "")
    if not match:
        return None
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def normalize_time(value):
    value = clean_text(value).replace("시", "")
    match = re.search(r"(\d{1,2})(?::(\d{1,2}))?", value)
    if not match:
        return None
    return f"{int(match.group(1)):02d}:{int(match.group(2) or 0):02d}"


def parse_time_range(value):
    match = re.search(
        r"(\d{1,2}(?::\d{1,2})?)\s*(?:~|-|–)\s*(\d{1,2}(?::\d{1,2})?)\s*시?",
        value or "",
    )
    if not match:
        return None, None
    return normalize_time(match.group(1)), normalize_time(match.group(2))


def parse_program_occurrence_text(value):
    value = clean_text(value)
    date_match = re.search(r"(20\d{2})[.\-/]\s*(\d{1,2})[.\-/]\s*(\d{1,2})", value)
    if not date_match:
        return None
    occurrence_date = (
        f"{date_match.group(1)}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
    )
    start_time, end_time = parse_time_range(value[date_match.end():])
    label = clean_text(value[: date_match.start()])
    return {
        "date": occurrence_date,
        "start_time": start_time,
        "end_time": end_time,
        "label": label or None,
        "confidence": 5,
    }


def best_content_image(base_url, page):
    images = re.findall(r'<img[^>]+src="([^"]+)"[^>]*>', page or "", flags=re.I)
    preferred = []
    fallback = []
    ignored = (
        "common/",
        "logo",
        "util",
        "sns",
        "nav-",
        "renewal-pup",
        "sub-visual",
        "m_close",
    )
    for src in images:
        src = html.unescape(src)
        lowered = src.lower()
        if any(token in lowered for token in ignored):
            continue
        if "editorimage.do" in lowered or "files" in lowered or "file" in lowered:
            preferred.append(src)
        else:
            fallback.append(src)
    src = (preferred or fallback or [None])[0]
    return urljoin(base_url, src) if src else None


def content_type_from_program(title, category=""):
    text = f"{title or ''} {category or ''}"
    if any(token in text for token in ("강연", "특강", "강좌", "포럼", "학술대회", "세미나")):
        return "강연"
    if any(token in text for token in ("행사", "음악회", "공연")):
        return "행사"
    return "교육"


def join_keywords(*values):
    keywords = []
    seen = set()
    for value in values:
        if not value:
            continue
        for item in re.split(r"[;,/|]", str(value)):
            item = clean_text(item).strip("#")
            if item and item not in seen:
                seen.add(item)
                keywords.append(item)
    return ";".join(keywords) or None


def extract_gangseo_detail(source_url):
    page = fetch_html(source_url)
    doc = doc_from_html(page)
    labels = [
        "종 류",
        "대 상",
        "장 소",
        "강 사",
        "접 수 기 간",
        "교 육 기 간",
        "문 의",
        "준 비 물",
    ]
    fields = {}
    for node in doc.xpath("//li"):
        text = node_text(node)
        for label in labels:
            if text.startswith(label):
                fields[label] = clean_text(text[len(label):])
                break
    title = first_node_text(doc, '//p[contains(@class, "subj")]')
    body_notes = []
    for node in doc.xpath("//p"):
        text = node_text(node)
        if not text or text in {title, "교육소개"}:
            continue
        if "만족도" in text or text.startswith("COPYRIGHT"):
            continue
        if len(text) > 15:
            body_notes.append(text)
    occurrences = []
    for row in doc.xpath("//table//tr[.//td]"):
        cells = [node_text(cell) for cell in row.xpath("./td")]
        if not cells or "프로그램명/프로그램일시" not in cells[0]:
            continue
        occurrence = parse_program_occurrence_text(
            cells[0].replace("프로그램명/프로그램일시", "")
        )
        if not occurrence:
            continue
        note_parts = []
        for cell in cells[1:]:
            text = clean_text(cell)
            if text:
                note_parts.append(text)
        occurrence["note"] = "; ".join(note_parts) or None
        occurrence["source_url"] = source_url
        occurrences.append(occurrence)
    description_parts = []
    for label in ("대 상", "접 수 기 간", "교 육 기 간", "문 의", "강 사", "준 비 물"):
        if fields.get(label):
            description_parts.append(f"{label}: {fields[label]}")
    description_parts.extend(body_notes[:2])
    return {
        "title": title,
        "fields": fields,
        "description": clean_text(" / ".join(description_parts))[:700] or None,
        "occurrences": occurrences,
        "image_url": best_content_image(source_url, page),
        "raw_text": clean_text(page),
    }


def extract_gangseo_education_list(institution_name, list_url, base_keywords):
    page = fetch_html(list_url)
    doc = doc_from_html(page)
    events = []
    seen = set()
    for row in doc.xpath('//table//tr[.//a[contains(@href, "/gsfc/education/view.do")]]'):
        title = first_node_text(row, './/p[contains(@class, "subj")]')
        hrefs = row.xpath('.//a[contains(@href, "/gsfc/education/view.do")]/@href')
        if not title or not hrefs:
            continue
        source_url = urljoin(list_url, clean_href(hrefs[0]))
        if source_url in seen:
            continue
        seen.add(source_url)
        cells = [node_text(cell) for cell in row.xpath("./td")]
        if len(cells) < 5:
            continue
        apply_period = cells[1]
        education_period = cells[2]
        category = cells[3]
        target = cells[4]
        start_date, end_date = parse_date_range(education_period)
        detail = extract_gangseo_detail(source_url)
        fields = detail["fields"]
        if fields.get("교 육 기 간"):
            start_date, end_date = parse_date_range(fields["교 육 기 간"])
        status = infer_status(start_date, end_date)
        if status == "종료":
            continue
        image_url = (
            best_content_image(list_url, lxml_html.tostring(row, encoding="unicode"))
            or detail["image_url"]
        )
        keyword_hints = []
        if any(token in f"{title} {target}" for token in ("어린이", "초등", "청소년", "가족")):
            keyword_hints.append("가족")
        if any(token in f"{title} {category}" for token in ("체험", "만들기", "참여")):
            keyword_hints.append("참여형")
        if any(token in title for token in ("정선", "민화", "한국화", "사군자", "탁본")):
            keyword_hints.extend(["한국미술", "전통"])
        if any(token in title for token in ("허준", "약초", "동의보감", "의학", "건강")):
            keyword_hints.extend(["역사", "의학"])
        events.append(
            {
                "institution_name": institution_name,
                "content_type": content_type_from_program(title, category),
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": fields.get("장 소") or institution_name,
                "region": "서울",
                "price": None,
                "description": detail["description"]
                or f"접수기간: {apply_period}. 대상: {target}",
                "keywords": join_keywords(base_keywords, category, target, *keyword_hints),
                "image_url": image_url,
                "source_url": source_url,
                "status": status,
                "raw_text": detail["raw_text"][:1200],
                "occurrences": detail["occurrences"],
            }
        )
    if not events:
        raise RuntimeError(f"{institution_name} 교육 상세 일정 중 현재/예정 항목을 찾지 못했습니다.")
    return events


def extract_small_local_gangseo_deep():
    events = []
    events.extend(
        extract_gangseo_education_list(
            "겸재정선미술관",
            "https://culture.gangseo.seoul.kr/gsfc/education/kgallery/list.do?menuNo=800075",
            "한국미술;전통;교육",
        )
    )
    events.extend(
        extract_gangseo_education_list(
            "허준박물관",
            "https://culture.gangseo.seoul.kr/gsfc/education/hmuseum/list.do?menuNo=800077",
            "역사;의학;교육",
        )
    )
    return events


def seongbuk_field_map(doc):
    fields = {}
    for node in doc.xpath("//li"):
        text = node_text(node)
        for label in ("전시기간", "전시구분", "출품작가", "장소"):
            if text.startswith(label):
                fields[label] = clean_text(text[len(label):])
                break
    return fields


def extract_description_after_marker(doc, *markers):
    text = clean_text(doc.xpath("string(//body)"))
    for marker in markers:
        start = text.find(marker)
        if start != -1:
            text = text[start + len(marker):]
            break
    for end_marker in ("목록", "관련사이트", "Previous"):
        end = text.find(end_marker)
        if end != -1:
            text = text[:end]
    return clean_text(text)[:900] or None


def extract_seongbuk_exhibition(source):
    page = fetch_html(source["url"])
    doc = doc_from_html(page)
    fields = seongbuk_field_map(doc)
    title = source.get("title")
    if not title:
        page_title = first_node_text(doc, "//title")
        match = re.search(r"게시판읽기\((.*?)\)", page_title)
        title = clean_text(match.group(1) if match else page_title)
    start_date, end_date = parse_date_range(fields.get("전시기간", ""))
    description = extract_description_after_marker(doc, "■ 전시 소개", "전시 소개")
    artist = fields.get("출품작가")
    category = fields.get("전시구분")
    if artist:
        description = clean_text(f"작가: {artist}. {description or ''}")
    return {
        "institution_name": source["institution_name"],
        "content_type": "전시",
        "title": title,
        "start_date": start_date,
        "end_date": end_date,
        "location": fields.get("장소") or source["institution_name"],
        "region": "서울",
        "price": "무료" if "무료" in clean_text(doc.xpath("string(//body)")) else None,
        "description": description,
        "keywords": join_keywords(source.get("keywords"), category, artist, "무료"),
        "image_url": best_content_image(source["url"], page),
        "source_url": source["url"],
        "status": infer_status(start_date, end_date),
        "raw_text": clean_text(page)[:1200],
    }


def extract_small_local_seongbuk_deep():
    sources = [
        {
            "institution_name": "성북구립 최만린미술관",
            "title": "집: 두 조각가를 잇다",
            "url": "https://sma.sbculture.or.kr/cml/exhibition/current.do?mode=view&articleNo=53327&article.offset=0&articleLimit=10",
            "keywords": "한국미술;현대조각;작가미술관",
        },
        {
            "institution_name": "성북구립미술관",
            "url": "https://sma.sbculture.or.kr/sma/exhibition/current.do?mode=view&articleNo=43458&article.offset=0&articleLimit=10",
            "keywords": "한국미술;공공미술;조각",
        },
    ]
    events = [extract_seongbuk_exhibition(source) for source in sources]
    return [event for event in events if event["status"] != "종료"]


def seodaemun_fields(doc):
    fields = {}
    for node in doc.xpath("//li"):
        text = node_text(node)
        for label in (
            "전시명",
            "전시장소",
            "전시구분",
            "전시기간",
            "강좌명",
            "장소",
            "날짜",
            "시간",
            "대상",
            "수강료",
        ):
            if text.startswith(label):
                fields[label] = clean_text(text[len(label):])
                break
    return fields


def extract_seodaemun_exhibition(url, keywords):
    page = fetch_html(url)
    doc = doc_from_html(page)
    fields = seodaemun_fields(doc)
    start_date, end_date = parse_date_range(fields.get("전시기간", ""))
    paragraphs = [
        node_text(node)
        for node in doc.xpath("//p")
        if len(node_text(node)) > 20 and not node_text(node).startswith("COPYRIGHT")
    ]
    return {
        "institution_name": "서대문자연사박물관",
        "content_type": "전시",
        "title": fields.get("전시명") or first_node_text(doc, "//h4"),
        "start_date": start_date,
        "end_date": end_date,
        "location": fields.get("전시장소"),
        "region": "서울",
        "price": None,
        "description": clean_text(" ".join(paragraphs))[:900] or None,
        "keywords": keywords,
        "image_url": best_content_image(url, page),
        "source_url": url,
        "status": infer_status(start_date, end_date),
        "raw_text": clean_text(page)[:1200],
    }


SEODAEMUN_EDU_CATEGORIES = {
    "class": "박물관 교실",
    "tour": "박물관 투어",
    "science": "과학강연",
    "meta": "메타 교실",
    "moon": "가족과 함께하는 달보기",
    "camp": "성인대상 교육",
    "school": "학급투어",
    "curator": "나도 큐레이터",
    "experience": "과학도구 체험",
}


def extract_seodaemun_calendar_month(url):
    page = fetch_html(url)
    doc = doc_from_html(page)
    title = first_node_text(doc, '//h5[contains(@class, "title")]')
    month_match = re.search(r"(20\d{2})년\s*(\d{1,2})월", title)
    if not month_match:
        raise RuntimeError("서대문자연사박물관 교육 달력 월 정보를 찾지 못했습니다.")
    year = int(month_match.group(1))
    month = int(month_match.group(2))
    hidden = {
        node.get("name"): node.get("value")
        for node in doc.xpath('//input[@type="hidden"][@name]')
    }
    events = []
    for name, title_value in hidden.items():
        match = re.match(r"(\d{1,2})_([a-z]+)_title(\d+)$", name)
        if not match:
            continue
        day = int(match.group(1))
        category = match.group(2)
        index = match.group(3)
        link_id = hidden.get(f"{day}_{category}_link{index}")
        time_text = hidden.get(f"{day}_{category}_time{index}") or ""
        if not title_value or not link_id:
            continue
        date_text = f"{year}-{month:02d}-{day:02d}"
        source_url = (
            f"https://namu.sdm.go.kr/web/main/education/{category}/view?epIdx={link_id}"
        )
        fields = {}
        description = None
        price = None
        location = "서대문자연사박물관"
        try:
            detail_page = fetch_html(source_url)
            detail_doc = doc_from_html(detail_page)
            fields = seodaemun_fields(detail_doc)
            description_parts = [
                node_text(node)
                for node in detail_doc.xpath("//p")
                if len(node_text(node)) > 20
            ]
            description = clean_text(" ".join(description_parts))[:700] or None
            location = fields.get("장소") or location
            price = fields.get("수강료")
            date_text = parse_single_date(fields.get("날짜")) or date_text
            time_text = fields.get("시간") or time_text
        except Exception:
            pass
        start_time, end_time = parse_time_range(time_text)
        label = SEODAEMUN_EDU_CATEGORIES.get(category, category)
        content_type = "강연" if category == "science" else "교육"
        target = fields.get("대상")
        status = infer_status(date_text, date_text)
        field_title = fields.get("강좌명")
        hidden_title = clean_text(title_value)
        display_title = hidden_title if len(hidden_title) > len(field_title or "") else (field_title or hidden_title)
        if re.fullmatch(r"\(?\d{1,2}월\)?", display_title or ""):
            display_title = f"{label} {display_title}"
        if display_title.startswith(label) and time_text:
            display_title = f"{display_title} {time_text}"
        events.append(
            {
                "institution_name": "서대문자연사박물관",
                "content_type": content_type,
                "title": display_title,
                "start_date": date_text,
                "end_date": date_text,
                "location": location,
                "region": "서울",
                "price": price,
                "description": description,
                "keywords": join_keywords("자연사;과학;교육", label, target),
                "image_url": None,
                "source_url": source_url,
                "status": status,
                "raw_text": f"서대문자연사박물관 교육 달력 수집. 월={title}; 분류={label}; 시간={time_text}",
                "occurrences": [
                    {
                        "date": date_text,
                        "start_time": start_time,
                        "end_time": end_time,
                        "label": label,
                        "note": target,
                        "source_url": source_url,
                        "confidence": 5,
                    }
                ],
            }
        )
    next_href = first_node_text(doc, '//a[contains(@class, "next-style")]/@href')
    next_url = urljoin(url, html.unescape(next_href)) if next_href else None
    return events, next_url


def extract_small_local_seodaemun_deep():
    events = [
        extract_seodaemun_exhibition(
            "https://namu.sdm.go.kr/web/main/exhibition/event/current/view",
            "자연사;기후;생태;환경",
        ),
        extract_seodaemun_exhibition(
            "https://namu.sdm.go.kr/web/main/exhibition/special/current/view",
            "자연사;식물;생태;과학",
        ),
    ]
    month_url = "https://namu.sdm.go.kr/web/main/education/all/list"
    seen_urls = set()
    for _ in range(2):
        if not month_url or month_url in seen_urls:
            break
        seen_urls.add(month_url)
        month_events, month_url = extract_seodaemun_calendar_month(month_url)
        events.extend(month_events)
    return events


def extract_national_museum_current_exhibitions():
    url = "https://www.museum.go.kr/MUSEUM/contents/M0202010000.do?menuId=current"
    page = fetch_html(url)
    doc = doc_from_html(page)
    info_nodes = doc.xpath(
        '//div[contains(concat(" ", normalize-space(@class), " "), " info ")][.//strong]'
    )
    if not info_nodes:
        raise RuntimeError("국립중앙박물관 현재 전시 정보 블록을 찾지 못했습니다.")

    events = []
    for info in info_nodes:
        title = first_node_text(info, ".//strong")
        period_text = first_node_text(
            info, './/li[strong[contains(normalize-space(.), "기간")]]/p'
        )
        location = first_node_text(
            info, './/li[strong[contains(normalize-space(.), "장소")]]/p'
        )
        if not title or not period_text or not location:
            continue
        start_date, end_date = parse_date_range(period_text)
        hrefs = info.xpath('.//a[contains(@href, "exhiSpThemId")]/@href')
        source_url = urljoin(url, clean_href(hrefs[-1])) if hrefs else url
        image_url = None
        ancestors = info.xpath("./ancestor::li[1]")
        if ancestors:
            image_candidates = ancestors[0].xpath(
                './/img[@src and not(contains(@src, "btn_more")) and not(contains(@src, "onerror"))]/@src'
            )
            if image_candidates:
                image_url = urljoin(url, clean_href(image_candidates[0]))
        raw_text = f"국립중앙박물관 현재전시. 제목: {title}; 기간: {period_text}; 장소: {location}"
        events.append(
            {
                "institution_name": "국립중앙박물관",
                "content_type": "전시",
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": location,
                "region": "서울",
                "price": None,
                "description": None,
                "keywords": None,
                "image_url": image_url,
                "source_url": source_url,
                "status": infer_status(start_date, end_date),
                "raw_text": raw_text,
            }
        )
    return events


def extract_seoul_craft_museum_exhibitions():
    url = "https://craftmuseum.seoul.go.kr/main"
    page = fetch_html(url)
    item_blocks = re.findall(
        r'<div class="item">\s*<a href="(/exhibit/plan/view/[^"]+)">(.*?)</a>\s*</div>',
        page,
        flags=re.S,
    )
    if not item_blocks:
        raise RuntimeError("서울공예박물관 전시 정보 블록을 찾지 못했습니다.")

    events = []
    for href, block in item_blocks:
        title_match = re.search(r'<div class="subject[^"]*">(.*?)</div>', block, flags=re.S)
        info_match = re.search(r'<span class="info font16 ellipse color-494A4B">(.*?)</span>', block, flags=re.S)
        if not title_match or not info_match:
            continue

        title = clean_text(title_match.group(1))
        info_text = clean_text(info_match.group(1))
        start_date, end_date = parse_date_range(info_text)
        location = re.sub(
            r"\d{4}[./]\d{1,2}[./]\d{1,2}\s*~\s*(?:\d{4}[./]\d{1,2}[./]\d{1,2})?,?",
            "",
            info_text,
        )
        location = clean_text(location)
        source_url = urljoin(url, href)
        image_match = re.search(r'<img[^>]+src="([^"]+)"', block)
        image_url = urljoin(url, html.unescape(image_match.group(1))) if image_match else None
        events.append(
            {
                "institution_name": "서울공예박물관",
                "content_type": "전시",
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": location,
                "region": "서울",
                "price": None,
                "description": None,
                "keywords": "공예",
                "image_url": image_url,
                "source_url": source_url,
                "status": infer_status(start_date, end_date),
                "raw_text": clean_text(block),
            }
        )
    return events


def extract_seoul_museum_of_art_exhibitions():
    url = "https://sema.seoul.go.kr/kr/whatson/landing"
    page = fetch_html(url)
    starts = [match.start() for match in re.finditer(r'<div id="dv_[^"]+"[^>]*data-whatson-menu-div="EX"', page)]
    if not starts:
        raise RuntimeError("서울시립미술관 전시 정보 블록을 찾지 못했습니다.")

    events = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else page.find('<div class="c-pagination', start)
        if end == -1:
            end = page.find("</main>", start)
        block = page[start:end]
        title_match = re.search(r'<strong class="o_h1">(.*?)</strong>', block, flags=re.S)
        date_match = re.search(r"(\d{4}/\d{2}/\d{2}\s*~\s*\d{4}/\d{2}/\d{2})", block)
        link_match = re.search(r'data-idx="([^"]+)"', block)
        if not title_match or not date_match:
            continue

        title = clean_text(title_match.group(1))
        start_date, end_date = parse_date_range(date_match.group(1))
        location_match = re.search(r'<span class="o_h2 epEcPlaceNm app-none">(.*?)</span>', block, flags=re.S)
        location = clean_text(location_match.group(1)).strip(",") if location_match else None
        source_url = url
        if link_match:
            source_url = f"{url}#dv_{link_match.group(1)}"
        image_match = re.search(r'<img[^>]+src="([^"]+)"', block)
        image_url = urljoin(url, html.unescape(image_match.group(1))) if image_match else None
        events.append(
            {
                "institution_name": infer_sema_institution_name(location),
                "content_type": "전시",
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": location,
                "region": "서울",
                "price": None,
                "description": None,
                "keywords": "현대미술",
                "image_url": image_url,
                "source_url": source_url,
                "status": infer_status(start_date, end_date),
                "raw_text": clean_text(block),
            }
        )
    return events


def parse_sema_date_text(value):
    dates = []
    for year, month, day in re.findall(r"(20\d{2})/(\d{1,2})/(\d{1,2})", value or ""):
        dates.append(f"{year}-{int(month):02d}-{int(day):02d}")
    if not dates:
        return None, None
    return dates[0], dates[-1]


def extract_seoul_museum_of_art_programs():
    url = "https://sema.seoul.go.kr/kr/whatson/landing"
    page = fetch_html(url)
    starts = list(
        re.finditer(
            r'<div id="dv_([^"]+)"[^>]*data-idx="([^"]+)"[^>]*data-whatson-menu-div="([^"]+)"',
            page,
        )
    )
    if not starts:
        raise RuntimeError("서울시립미술관 교육프로그램 정보 블록을 찾지 못했습니다.")

    events = []
    for index, match in enumerate(starts):
        if match.group(3) != "EP":
            continue
        end = starts[index + 1].start() if index + 1 < len(starts) else page.find('<div class="c-pagination', match.start())
        if end == -1:
            end = page.find("</main>", match.start())
        block = page[match.start():end]
        title_match = re.search(r'<strong class="o_h1">(.*?)</strong>', block, flags=re.S)
        date_text = clean_text(first_match(r'<span class="o_h3">\s*(.*?)</span>', block) or "")
        if not title_match or not date_text:
            continue

        program_id = match.group(2)
        title = clean_text(title_match.group(1))
        start_date, end_date = parse_sema_date_text(date_text)
        location_match = re.search(r'<span class="o_h2 epEcPlaceNm(?: app-none)?">(.*?)</span>', block, flags=re.S)
        location = clean_text(location_match.group(1)).strip(",") if location_match else None
        image_match = re.search(r'<img[^>]+src="([^"]+)"', block)
        image_url = urljoin(url, html.unescape(image_match.group(1))) if image_match else None
        source_url = f"https://sema.seoul.go.kr/kr/whatson/education/detail?acadmyEeNo={program_id}"
        events.append(
            {
                "institution_name": infer_sema_institution_name(location),
                "content_type": "교육",
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": location,
                "region": "서울",
                "price": None,
                "description": f"목록 일정: {date_text}",
                "keywords": "교육;미술;현대미술",
                "image_url": image_url,
                "source_url": source_url,
                "status": infer_status(start_date, end_date),
                "raw_text": clean_text(block),
            }
        )
    if not events:
        raise RuntimeError("서울시립미술관 교육프로그램을 찾지 못했습니다.")
    return events


def extract_leeum_exhibitions():
    url = "https://www.leeumhoam.org/leeum/exhibition/list"
    data = fetch_json(
        url,
        {
            "view": "grid",
            "state": "1",
            "keyword": "",
            "startDate": "",
            "endDate": "",
            "limit": "16",
            "mainFlag": "false",
            "found": "LM",
            "page": "1",
            "tab": "present",
        },
    )
    events = []
    for row in data.get("list", []):
        title = clean_text(row.get("title") or "")
        if not title:
            continue
        start_date = row.get("startDate")
        end_date = row.get("endDate")
        is_permanent = (
            end_date in {"1900-01-01", "9999-12-31"}
            or (start_date and start_date < "1900-01-01")
        )
        if is_permanent:
            start_date = None
            end_date = None
        elif end_date in {"1900-01-01", "9999-12-31"}:
            end_date = None
        source_url = f"https://www.leeumhoam.org/leeum/exhibition/{row.get('exhibitionSeq')}?params=Y"
        image_url = None
        if row.get("image"):
            image_url = "https://www.leeumhoam.org/upload/exhibition/" + quote(row["image"])
        events.append(
            {
                "institution_name": "리움미술관",
                "content_type": "전시",
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": clean_text(row.get("location") or ""),
                "region": "서울",
                "price": None,
                "description": row.get("imageAlt"),
                "keywords": "상설전시;한국미술;고미술" if is_permanent else "현대미술",
                "image_url": image_url,
                "source_url": source_url,
                "status": "상설전" if is_permanent else infer_status(start_date, end_date),
                "raw_text": json.dumps(row, ensure_ascii=False),
            }
        )
    return events


def extract_hangeul_museum_exhibitions():
    url = "https://www.hangeul.go.kr/exhibition?curr_menu_cd=0102020000"
    page = fetch_html(url)
    blocks = re.findall(r"<li>\s*(<a[^>]+class=\"go-view\".*?</a>)\s*</li>", page, flags=re.S)
    if not blocks:
        raise RuntimeError("국립한글박물관 전시 정보 블록을 찾지 못했습니다.")

    events = []
    for block in blocks:
        title = clean_text(first_match(r'<h3 class="tit-mid">(.*?)</h3>', block) or "")
        if not title:
            continue
        exhibition_no = first_match(r'data-exhibition-no="([^"]+)"', block)
        info_values = re.findall(r"<dd>(.*?)</dd>", block, flags=re.S)
        start_date, end_date = parse_date_range(clean_text(info_values[0]) if info_values else "")
        location = clean_text(info_values[1]) if len(info_values) > 1 else None
        image_url = image_from_block(url, block)
        source_url = (
            f"https://www.hangeul.go.kr/exhibition/{exhibition_no}?page=1&curr_menu_cd=0102020000"
            if exhibition_no
            else url
        )
        events.append(
            {
                "institution_name": "국립한글박물관",
                "content_type": "전시",
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": location,
                "region": "서울",
                "price": None,
                "description": None,
                "keywords": "한글;언어;디자인",
                "image_url": image_url,
                "source_url": source_url,
                "status": infer_status(start_date, end_date),
                "raw_text": clean_text(block),
            }
        )
    return events


def extract_ggcf_exhibitions(institution_name, base_url):
    url = f"{base_url.rstrip('/')}/exhibitions"
    page = fetch_html(url)
    events = []

    # Card style used by several Gyeonggi Cultural Foundation museum sites.
    for block in re.findall(r'<a href="([^"]*/exhibitions/\d+)" class="sld_box03">(.*?)</a>', page, flags=re.S):
        href, body = block
        title = clean_text(first_match(r'<p class="sld_title">(.*?)</p>', body) or "")
        if not title:
            continue
        period_text = clean_text(first_match(r"<dt>\s*기간\s*</dt>\s*<dd>(.*?)</dd>", body) or "")
        location = clean_text(first_match(r"<dt>\s*장소\s*</dt>\s*<dd>(.*?)</dd>", body) or "")
        start_date, end_date = parse_date_range(period_text)
        source_url = urljoin(url, href)
        events.append(
            {
                "institution_name": institution_name,
                "content_type": "전시",
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": location,
                "region": "경기",
                "price": None,
                "description": None,
                "keywords": None,
                "image_url": image_from_block(url, body),
                "source_url": source_url,
                "status": infer_status(start_date, end_date),
                "raw_text": clean_text(body),
            }
        )

    # Simple list style used by GMoMA.
    for href, body in re.findall(r'<a href="([^"]*/?exhibitions/\d+)">(.*?)</a>', page, flags=re.S):
        if "sld_box03" in body:
            continue
        title_candidates = re.findall(r"<p(?: [^>]*)?>(.*?)</p>", body, flags=re.S)
        title_candidates = [
            clean_text(item)
            for item in title_candidates
            if "date" not in item and clean_text(item)
        ]
        date_text = clean_text(first_match(r'<p class="date">(.*?)</p>', body) or "")
        if not title_candidates or not date_text:
            continue
        title = title_candidates[0]
        if title in {"현재 / 예정", "과거"}:
            continue
        start_date, end_date = parse_date_range(date_text)
        source_url = urljoin(url, href)
        event = {
            "institution_name": institution_name,
            "content_type": "전시",
            "title": title,
            "start_date": start_date,
            "end_date": end_date,
            "location": None,
            "region": "경기",
            "price": None,
            "description": None,
            "keywords": None,
            "image_url": image_from_block(url, body),
            "source_url": source_url,
            "status": infer_status(start_date, end_date),
            "raw_text": clean_text(body),
        }
        if not any(existing["source_url"] == source_url for existing in events):
            events.append(event)

    # NJP/similar list style.
    for body in re.findall(r"<li>\s*(.*?)</li>", page, flags=re.S):
        href = (
            first_match(r"window\.location\.href='([^']*/exhibitions/\d+)'", body)
            or first_match(r'href=["\']?([^"\'> ]*/?exhibitions/\d+)', body)
        )
        title = clean_text(first_match(r'class="title">(.*?)</a>', body) or first_match(r"<h4>(.*?)</h4>", body) or "")
        date_text = clean_text(first_match(r'class="date">(.*?)</div>', body) or first_match(r"<th>\s*기간\s*</th>\s*<td[^>]*>(.*?)</td>", body) or "")
        if not href or not title or not date_text:
            continue
        location = clean_text(first_match(r"<th>\s*장소\s*</th>\s*<td[^>]*>(.*?)</td>", body) or "")
        start_date, end_date = parse_date_range(date_text)
        source_url = urljoin(url, href)
        if any(existing["source_url"] == source_url for existing in events):
            continue
        events.append(
            {
                "institution_name": institution_name,
                "content_type": "전시",
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": location,
                "region": "경기",
                "price": None,
                "description": None,
                "keywords": None,
                "image_url": image_from_block(url, body),
                "source_url": source_url,
                "status": infer_status(start_date, end_date),
                "raw_text": clean_text(body),
            }
        )

    # List items whose detail URL is stored on the opening li tag.
    onclick_matches = list(
        re.finditer(r"<li[^>]+onclick=\"window\.location\.href='([^']*/exhibitions/\d+)'\"", page)
    )
    for index, match in enumerate(onclick_matches):
        source_url = match.group(1)
        end = onclick_matches[index + 1].start() if index + 1 < len(onclick_matches) else page.find("</ul>", match.start())
        if end == -1:
            end = page.find("</main>", match.start())
        body = page[match.start():end]
        title = clean_text(first_match(r"<h4>(.*?)</h4>", body) or "")
        date_text = clean_text(first_match(r"<th>\s*기간\s*</th>\s*<td[^>]*>(.*?)</td>", body) or "")
        if not title or not date_text:
            continue
        location = clean_text(first_match(r"<th>\s*장소\s*</th>\s*<td[^>]*>(.*?)</td>", body) or "")
        start_date, end_date = parse_date_range(date_text)
        if any(existing["source_url"] == source_url for existing in events):
            continue
        events.append(
            {
                "institution_name": institution_name,
                "content_type": "전시",
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": location,
                "region": "경기",
                "price": None,
                "description": None,
                "keywords": None,
                "image_url": image_from_block(url, body),
                "source_url": source_url,
                "status": infer_status(start_date, end_date),
                "raw_text": clean_text(body),
            }
        )

    if not events:
        raise RuntimeError(f"{institution_name} 전시 정보 블록을 찾지 못했습니다.")
    return events


def extract_gmoma_exhibitions():
    return extract_ggcf_exhibitions("경기도미술관", "https://gmoma.ggcf.kr")


def extract_gyeonggi_museum_exhibitions():
    return extract_ggcf_exhibitions("경기도박물관", "https://musenet.ggcf.kr")


def extract_njp_exhibitions():
    return extract_ggcf_exhibitions("백남준아트센터", "https://njp.ggcf.kr")


def extract_silhak_exhibitions():
    return extract_ggcf_exhibitions("실학박물관", "https://silhak.ggcf.kr")


def extract_jgpm_exhibitions():
    return extract_ggcf_card_entries("전곡선사박물관", "https://jgpm.ggcf.kr", "exhibitions", "전시")


def extract_jgpm_programs():
    return extract_ggcf_card_entries("전곡선사박물관", "https://jgpm.ggcf.kr", "edus", "교육")


def extract_gcm_exhibitions():
    return extract_ggcf_card_entries("경기도어린이박물관", "https://gcm.ggcf.kr", "exhibitions", "전시")


def extract_gcm_programs():
    return extract_ggcf_card_entries("경기도어린이박물관", "https://gcm.ggcf.kr", "edus", "교육")


def extract_mmca_exhibitions():
    url = "https://www.mmca.go.kr/exhibitions/AjaxExhibitionList.do"
    referer = "https://www.mmca.go.kr/exhibitions/progressList.do"
    params = {
        "exhFlag": "1",
        "searchExhPlaCd": "",
        "searchExhCd": "",
        "sort": "exhStDt",
        "pageIndex": "1",
    }
    first_page = fetch_json(url, params, referer=referer)
    total_pages = int(first_page.get("paginationInfo", {}).get("totalPageCount") or 1)
    pages = [first_page]
    for page_index in range(2, min(total_pages, 5) + 1):
        page_params = dict(params)
        page_params["pageIndex"] = str(page_index)
        pages.append(fetch_json(url, page_params, referer=referer))

    institution_by_place = {
        "서울": "국립현대미술관 서울관",
        "과천": "국립현대미술관 과천관",
        "덕수궁": "국립현대미술관 덕수궁관",
    }
    events = []
    for page in pages:
        for row in page.get("exhibitionsList", []):
            place_name = clean_text(row.get("exhPlaNm") or "")
            institution_name = institution_by_place.get(place_name)
            if not institution_name:
                continue
            title = clean_text(row.get("exhTitle") or "")
            if not title:
                continue
            start_date = row.get("exhStDt")
            end_date = row.get("exhEdDt")
            image_path = row.get("exhThumbImg") or row.get("exhDidImg")
            image_url = urljoin("https://www.mmca.go.kr", image_path) if image_path else None
            source_url = f"https://www.mmca.go.kr/exhibitions/progressList.do#exhId={row.get('exhId')}"
            description = clean_text(row.get("exhContentsSumm") or row.get("exhContents") or "")
            events.append(
                {
                    "institution_name": institution_name,
                    "content_type": "전시",
                    "title": title,
                    "start_date": start_date,
                    "end_date": end_date,
                    "location": clean_text(row.get("exhPlaDtl") or place_name),
                    "region": "경기" if place_name == "과천" else "서울",
                    "price": clean_text(row.get("exhAdm") or "") or None,
                    "description": description,
                    "keywords": clean_text(row.get("exhThemewd") or row.get("exhTpCd") or ""),
                    "image_url": image_url,
                    "source_url": source_url,
                    "status": infer_status(start_date, end_date),
                    "raw_text": json.dumps(row, ensure_ascii=False),
                }
            )
    if not events:
        raise RuntimeError("국립현대미술관 수도권 전시 정보를 찾지 못했습니다.")
    return events


def extract_seoul284_exhibitions():
    url = "https://www.seoul284.org/program/list/category/319/state/5/menu/328"
    page = fetch_html(url)
    blocks = re.findall(
        r'<a class="exh_listBox" href="javascript:goView\((.*?)\);">(.*?)</a>',
        page,
        flags=re.S,
    )
    if not blocks:
        raise RuntimeError("문화역서울284 전시 정보 블록을 찾지 못했습니다.")

    events = []
    for args, block in blocks:
        title = clean_text(first_match(r'<strong class="exh_tit">(.*?)</strong>', block) or "")
        if not title:
            continue
        date_text = clean_text(first_match(r'<p class="exh_date">(.*?)</p>', block) or "")
        start_date, end_date = parse_date_range(date_text)
        arg_values = re.findall(r"'([^']+)'", args)
        source_url = url
        if len(arg_values) >= 2:
            source_url = urljoin(url, f"{arg_values[0]}?idx={arg_values[1]}")
        category = clean_text(first_match(r'<span class="exh_cate">(.*?)</span>', block) or "")
        events.append(
            {
                "institution_name": "문화역서울284",
                "content_type": "전시",
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": "문화역서울284",
                "region": "서울",
                "price": None,
                "description": clean_text(first_match(r'<p class="exh_cont">(.*?)</p>', block) or ""),
                "keywords": category,
                "image_url": image_from_block(url, block),
                "source_url": source_url,
                "status": infer_status(start_date, end_date),
                "raw_text": clean_text(block),
            }
        )
    return events


def extract_soma_exhibitions():
    url = "https://soma.kspo.or.kr/dspy/display/curr/list"
    page = fetch_html(url)
    starts = [match.start() for match in re.finditer(r'<div class="exh_list_current_wrap">', page)]
    if not starts:
        raise RuntimeError("소마미술관 현재 전시 정보 블록을 찾지 못했습니다.")

    events = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else page.find("</ul>", start)
        if end == -1:
            end = page.find("</main>", start)
        block = page[start:end]
        title = clean_text(first_match(r"<h3[^>]*>(.*?)</h3>", block) or "")
        if not title:
            continue
        date_text = clean_text(first_match(r"<strong>\s*기간\s*</strong>(.*?)</li>", block) or "")
        start_date, end_date = parse_date_range(date_text)
        location = clean_text(first_match(r"<strong>\s*장소\s*</strong>(.*?)</li>", block) or "")
        href = first_match(r'<a href="([^"]+)">바로가기</a>', block)
        events.append(
            {
                "institution_name": "소마미술관",
                "content_type": "전시",
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": location or "소마미술관",
                "region": "서울",
                "price": None,
                "description": None,
                "keywords": "조각;현대미술",
                "image_url": image_from_block(url, block),
                "source_url": urljoin(url, href) if href else url,
                "status": infer_status(start_date, end_date),
                "raw_text": clean_text(block),
            }
        )
    return events


def extract_inartplatform_exhibitions():
    url = "https://inartplatform.kr/program/list?category=B&time=now"
    page = fetch_html(url)
    blocks = re.findall(r'<li>\s*<a href="(/program/view\?no=\d+)">(.*?)</a>\s*</li>', page, flags=re.S)
    if not blocks:
        raise RuntimeError("인천아트플랫폼 전시 정보 블록을 찾지 못했습니다.")

    events = []
    for href, block in blocks:
        title_parts = [clean_text(part) for part in re.findall(r"<strong>(.*?)</strong>", block, flags=re.S)]
        title = " ".join(part for part in title_parts if part)
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue
        date_text = clean_text(first_match(r'<span class="date">(.*?)</span>', block) or "")
        start_date, end_date = parse_date_range(date_text)
        events.append(
            {
                "institution_name": "인천아트플랫폼",
                "content_type": "전시",
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": "인천아트플랫폼",
                "region": "인천",
                "price": None,
                "description": None,
                "keywords": "현대미술;인천",
                "image_url": image_from_block(url, block),
                "source_url": urljoin(url, href),
                "status": infer_status(start_date, end_date),
                "raw_text": clean_text(block),
            }
        )
    return events


def extract_artsonje_exhibitions():
    url = "https://artsonje.org/exhibition-program/exhibition/"
    page = fetch_html(url)
    link_blocks = re.findall(
        r'<a href="(https://artsonje\.org/exhibition/[^"]+)"><img[^>]+src="([^"]+)".*?</a>.*?<div class="fwpl-item el-ue1s1t"><a href="[^"]+">(.*?)</a>',
        page,
        flags=re.S,
    )
    if not link_blocks:
        raise RuntimeError("아트선재센터 전시 정보 블록을 찾지 못했습니다.")

    events = []
    seen = set()
    for source_url, list_image_url, title_html in link_blocks[:20]:
        if source_url in seen:
            continue
        seen.add(source_url)
        detail_page = fetch_html(source_url)
        body_start = detail_page.find("<body")
        body_text = clean_text(detail_page[body_start:] if body_start != -1 else detail_page)
        date_match = re.search(
            r"20\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.?\s*[~\-]\s*(?:20\d{2}\.\s*)?\d{1,2}\.\s*\d{1,2}\.?",
            body_text,
        )
        if not date_match:
            continue
        start_date, end_date = parse_date_range(date_match.group(0))
        title = clean_text(title_html)
        image_url = (
            first_match(r'<meta property="og:image" content="([^"]+)"', detail_page)
            or html.unescape(list_image_url)
        )
        description = first_match(r'<meta property="og:description" content="([^"]+)"', detail_page)
        events.append(
            {
                "institution_name": "아트선재센터",
                "content_type": "전시",
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": "아트선재센터",
                "region": "서울",
                "price": None,
                "description": clean_text(description or ""),
                "keywords": "현대미술",
                "image_url": image_url,
                "source_url": source_url,
                "status": infer_status(start_date, end_date),
                "raw_text": body_text[:3000],
            }
        )
    if not events:
        raise RuntimeError("아트선재센터 전시 기간을 찾지 못했습니다.")
    return events


def extract_nfm_exhibitions():
    urls = [
        ("https://www.nfm.go.kr/user/planexhibition/home/20/selectPlanExhibitionNList.do", "서울"),
        ("https://www.nfm.go.kr/user/planexhibition/home/62/selectPlanExhibitionNList.do?planExhibitionGbn=PAJU", "경기"),
    ]
    events = []
    for url, region in urls:
        page = fetch_html(url)
        blocks = re.findall(r'<li class="thumb_item">(.*?)</li>', page, flags=re.S)
        for block in blocks:
            title = clean_text(first_match(r'<div class="item_title wrap">(.*?)</div>', block) or "")
            if not title:
                continue
            date_text = clean_text(first_match(r'<div class="item_date wrap">(.*?)</div>', block) or "")
            start_date, end_date = parse_date_range(date_text)
            location = clean_text(first_match(r'<div class="item_loca wrap">(.*?)</div>', block) or "")
            href = first_match(r'<a href="([^"]+)" class="d-exhibition__link"', block)
            categories = ";".join(clean_text(item) for item in re.findall(r'<span class="item_info[^"]*">(.*?)</span>', block, flags=re.S))
            events.append(
                {
                    "institution_name": "국립민속박물관",
                    "content_type": "전시",
                    "title": title,
                    "start_date": start_date,
                    "end_date": end_date,
                    "location": location,
                    "region": region,
                    "price": None,
                    "description": None,
                    "keywords": categories,
                    "image_url": image_from_block(url, block),
                    "source_url": urljoin(url, html.unescape(href)) if href else url,
                    "status": infer_status(start_date, end_date),
                    "raw_text": clean_text(block),
                }
            )

    child_url = "https://www.nfm.go.kr/home/subIndex/1196.do"
    child_page = fetch_html(child_url)
    child_blocks = re.findall(r'<li class="exhibition_item item">(.*?)</li>', child_page, flags=re.S)
    for block in child_blocks:
        title = clean_text(first_match(r'<div class="tit">(.*?)</div>', block) or "")
        if not title:
            continue
        date_text = clean_text(first_match(r'<div class="txt">\s*기간[:：]?(.*?)</div>', block) or "")
        start_date, end_date = parse_date_range(date_text)
        location = clean_text(first_match(r'<div class="txt">\s*장소[:：]?(.*?)</div>', block) or "")
        href = first_match(r'<a href="([^"]+)"[^>]*class="wrap btn"', block)
        events.append(
            {
                "institution_name": "국립민속박물관",
                "content_type": "전시",
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": location,
                "region": "서울",
                "price": None,
                "description": None,
                "keywords": "어린이박물관;상설전시",
                "image_url": image_from_block(child_url, block),
                "source_url": urljoin(child_url, html.unescape(href)) if href else child_url,
                "status": infer_status(start_date, end_date),
                "raw_text": clean_text(block),
            }
        )

    if not events:
        raise RuntimeError("국립민속박물관 전시 정보 블록을 찾지 못했습니다.")
    return events


def extract_gogung_exhibitions():
    url = "https://www.gogung.go.kr/gogung/bbs/BMSR00002/list.do?menuNo=800040"
    page = fetch_html(url)
    blocks = re.findall(
        r'<li>\s*<a href="([^"]+)" title="페이지 이동">(.*?)</a>\s*</li>',
        page,
        flags=re.S,
    )
    if not blocks:
        raise RuntimeError("국립고궁박물관 특별전시 정보 블록을 찾지 못했습니다.")

    events = []
    for href, block in blocks:
        title = clean_text(first_match(r'<p class="subject[^"]*">(.*?)</p>', block) or "")
        if not title:
            continue
        date_text = clean_text(first_match(r'<span class="title">\s*기간\s*</span>\s*<span class="text">(.*?)</span>', block) or "")
        start_date, end_date = parse_date_range(date_text)
        location = clean_text(first_match(r'<span class="title">\s*장소\s*</span>\s*<span class="text[^"]*">(.*?)</span>', block) or "")
        category = clean_text(first_match(r'<span class="category[^"]*">(.*?)</span>', block) or "")
        events.append(
            {
                "institution_name": "국립고궁박물관",
                "content_type": "전시",
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": location,
                "region": "서울",
                "price": None,
                "description": None,
                "keywords": category,
                "image_url": image_from_block(url, block),
                "source_url": urljoin(url, html.unescape(href)),
                "status": infer_status(start_date, end_date),
                "raw_text": clean_text(block),
            }
        )
    return events


def extract_much_programs():
    institution_name = "대한민국역사박물관"
    events = []

    edu_url = "https://www.much.go.kr/MUCH/contents/M03010200000.do"
    edu_page = fetch_html(edu_url)
    edu_section = first_match(r'<div class="ls-edu-img">(.*?)<!-- 페이징 -->', edu_page) or ""
    for href, block in re.findall(r'<li>\s*<a href="([^"]+)">(.*?)</a>\s*</li>', edu_section, flags=re.S):
        title = clean_text(first_match(r'<p class="sb">(.*?)</p>', block) or "")
        if not title:
            continue
        date_text = clean_text(
            first_match(r'<span class="lb">\s*교육기간\s*</span>\s*<span class="tx">(.*?)</span>', block)
            or ""
        )
        start_date, end_date = parse_date_range(date_text)
        target = clean_text(
            first_match(r'<span class="lb">\s*대상\s*</span>\s*<span class="tx">(.*?)</span>', block)
            or ""
        )
        apply_period = clean_text(
            first_match(r'<span class="lb">\s*접수기간\s*</span>\s*<span class="tx">(.*?)</span>', block)
            or ""
        )
        tags = ";".join(clean_text(item) for item in re.findall(r'<div class="bat">(.*?)</div>', block, flags=re.S))
        tags = clean_text(tags)
        events.append(
            {
                "institution_name": institution_name,
                "content_type": "교육",
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": "대한민국역사박물관",
                "region": "서울",
                "price": None,
                "description": f"대상: {target}. 접수기간: {apply_period}".strip(),
                "keywords": tags,
                "image_url": image_from_block(edu_url, block),
                "source_url": urljoin(edu_url, clean_href(href)),
                "status": infer_status(start_date, end_date),
                "raw_text": clean_text(block),
            }
        )

    event_url = "https://www.much.go.kr/MUCH/contents/M03020100000.do"
    event_page = fetch_html(event_url)
    event_section = first_match(r'<div class="ls-culture-img">(.*?)<!-- 페이징 -->', event_page) or ""
    for href, block in re.findall(r'<li>\s*<a href="([^"]+)">(.*?)</a>\s*</li>', event_section, flags=re.S):
        title = clean_text(first_match(r'<p class="sb">(.*?)</p>', block) or "")
        if not title:
            continue
        tx_values = [clean_text(item) for item in re.findall(r'<span class="tx">\s*(.*?)\s*</span>', block, flags=re.S)]
        date_text = tx_values[0] if tx_values else ""
        location = tx_values[1] if len(tx_values) > 1 else "대한민국역사박물관"
        start_date, end_date = parse_date_range(date_text)
        category = clean_text(first_match(r'<div class="bat">(.*?)</div>', block) or "")
        content_type = "강연" if ("콜로키움" in title or "학술행사" in category) else "행사"
        events.append(
            {
                "institution_name": institution_name,
                "content_type": content_type,
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": location,
                "region": "서울",
                "price": None,
                "description": None,
                "keywords": category,
                "image_url": image_from_block(event_url, block),
                "source_url": urljoin(event_url, clean_href(href)),
                "status": infer_status(start_date, end_date),
                "raw_text": clean_text(block),
            }
        )

    if not events:
        raise RuntimeError("대한민국역사박물관 교육/행사 정보 블록을 찾지 못했습니다.")
    return events


def extract_seoul_history_exhibitions():
    url = "https://museum.seoul.go.kr/www/board/NR_boardList.do?bbsCd=1002&q_exhSttus=next&q_listType=LIST&sso=ok"
    try:
        page = fetch_html(url)
    except Exception:
        page, _final_url = fetch_html_relaxed(url)
    rows = re.findall(r"<tr>\s*(.*?)</tr>", page, flags=re.S)
    institution_by_branch = {
        "서울역사박물관": "서울역사박물관",
        "서울생활사박물관": "서울생활사박물관",
        "청계천박물관": "청계천박물관",
        "우리소리박물관": "서울우리소리박물관",
        "한양도성박물관": "한양도성박물관",
        "공평도시유적전시관": "서울역사박물관",
    }
    events = []
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)
        if len(cells) < 4:
            continue
        branch_name = clean_text(cells[0])
        institution_name = institution_by_branch.get(branch_name, "서울역사박물관")
        title = clean_text(first_match(r"<a[^>]*>(.*?)</a>", cells[1]) or cells[1])
        title = re.sub(r"\s*첨부파일\s*\d+개 있음\s*", "", title).strip()
        date_text = clean_text(cells[2])
        start_date, end_date = parse_date_range(date_text)
        location = clean_text(cells[3]).replace("\xa0", " ")
        seq = first_match(r"jsViewAction\('1002',\s*'([^']+)'", cells[1])
        source_url = (
            f"https://museum.seoul.go.kr/www/board/NR_boardView.do?bbsCd=1002&q_exhSttus=next&seq={seq}"
            if seq
            else url
        )
        image_url = None
        description = None
        if seq:
            try:
                try:
                    detail_page = fetch_html(source_url)
                except Exception:
                    detail_page, _final_url = fetch_html_relaxed(source_url)
                image_url = image_from_block(source_url, detail_page)
                description = clean_text(detail_page)[:320]
            except Exception:
                image_url = None
                description = None
        events.append(
            {
                "institution_name": institution_name,
                "content_type": "전시",
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": location,
                "region": "서울",
                "price": None,
                "description": description,
                "keywords": branch_name,
                "image_url": image_url,
                "source_url": source_url,
                "status": infer_status(start_date, end_date),
                "raw_text": clean_text(row),
            }
        )
    if not events:
        raise RuntimeError("서울역사박물관 계열 현재/예정 전시 정보를 찾지 못했습니다.")
    return events


def relaxed_ssl_context(low_security=False):
    context = ssl._create_unverified_context()
    if low_security:
        try:
            context.set_ciphers("DEFAULT:@SECLEVEL=1")
        except ssl.SSLError:
            pass
    return context


def official_page_url_variants(url):
    primary = OFFICIAL_PAGE_FETCH_OVERRIDES.get(url, url)
    parsed = urlparse(primary)
    variants = [primary]
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        hosts = [parsed.netloc]
        if parsed.netloc.startswith("www."):
            hosts.append(parsed.netloc[4:])
        else:
            hosts.append("www." + parsed.netloc)
        for scheme in ("https", "http"):
            for host in hosts:
                variants.append(
                    urlunparse(
                        (scheme, host, parsed.path, parsed.params, parsed.query, parsed.fragment)
                    )
                )
    seen = set()
    ordered = []
    for item in variants:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def fetch_html_relaxed(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    errors = []
    for candidate_url in official_page_url_variants(url):
        for low_security in (False, True):
            request = Request(candidate_url, headers=headers)
            try:
                context = relaxed_ssl_context(low_security)
                with urlopen(request, timeout=24, context=context) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    final_url = response.geturl()
                    return response.read().decode(charset, "replace"), final_url
            except Exception as exc:
                errors.append(f"{candidate_url}: {exc}")
    raise RuntimeError(" / ".join(errors[-4:]))


def load_candidate_metadata():
    if not INSTITUTION_CSV.exists():
        return {}
    with INSTITUTION_CSV.open(encoding="utf-8-sig", newline="") as file:
        return {
            row["institution_name"]: row
            for row in csv.DictReader(file)
            if row.get("institution_name")
        }


def monitor_skip_institutions():
    if not DEFAULT_DB.exists():
        return set()
    manual_marker = "%등급 보강 수집%"
    monitor_marker = "공식 페이지 모니터 수집.%"
    with sqlite3.connect(DEFAULT_DB) as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT i.name
            FROM institutions i
            JOIN cultural_events e ON e.institution_id = i.id
            WHERE e.raw_text NOT LIKE ?
              AND e.raw_text NOT LIKE ?
            """,
            (manual_marker, monitor_marker),
        ).fetchall()
    return {row[0] for row in rows}


def backfill_source_groups():
    from a_grade_backfill_collector import A_GRADE_SOURCES
    from b_grade_backfill_collector import B_GRADE_SOURCES
    from c_grade_backfill_collector import C_GRADE_SOURCES
    from seoul_expansion_backfill_collector import SEOUL_EXPANSION_SOURCES
    from small_local_backfill_collector import SMALL_LOCAL_SOURCES

    groups = []
    for tier, sources in (
        ("A", A_GRADE_SOURCES),
        ("B", B_GRADE_SOURCES),
        ("C", C_GRADE_SOURCES),
        ("C", SMALL_LOCAL_SOURCES),
        ("C", SEOUL_EXPANSION_SOURCES),
    ):
        for source in sources:
            item = dict(source)
            item.setdefault("tier", tier)
            groups.append(item)
    return groups


def source_page_confidence(source_name, event_title, page_text):
    text = clean_text(page_text)
    checks = []
    if event_title:
        checks.append(event_title in text)
        title_tokens = [token for token in re.split(r"[\s:：,·ㆍ<>\[\](){}]+", event_title) if len(token) >= 3]
        if title_tokens:
            checks.append(sum(1 for token in title_tokens[:5] if token in text) >= max(1, min(2, len(title_tokens))))
    if source_name:
        checks.append(source_name in text)
        compact_name = source_name.replace(" ", "")
        checks.append(compact_name and compact_name in text.replace(" ", ""))
    return "높음" if any(checks) else "낮음"


def extract_official_page_monitor_events():
    metadata = load_candidate_metadata()
    skip_names = monitor_skip_institutions()
    page_cache = {}
    events = []
    failures = []
    monitored_sources = 0

    for source in backfill_source_groups():
        name = source["name"]
        if name in skip_names:
            continue
        monitored_sources += 1
        meta = metadata.get(name, {})
        for event in source.get("events", []):
            source_url = clean_href(event.get("source_url") or source.get("official_url") or meta.get("official_url") or "")
            if not source_url:
                failures.append((name, event.get("title", ""), "출처 URL 없음"))
                continue
            display_source_url = OFFICIAL_PAGE_FETCH_OVERRIDES.get(source_url, source_url)
            if source_url not in page_cache:
                try:
                    page_cache[source_url] = (*fetch_html_relaxed(source_url), None)
                except Exception as exc:
                    page_cache[source_url] = (None, source_url, str(exc))
            page, final_url, error = page_cache[source_url]
            if error:
                failures.append((name, event.get("title", ""), error))
                continue
            if not page or len(clean_text(page)) < 20:
                failures.append((name, event.get("title", ""), "공식 페이지 본문이 너무 짧음"))
                continue

            start_date = event.get("start_date")
            end_date = event.get("end_date")
            explicit_status = event.get("status")
            status = explicit_status or infer_status(start_date, end_date)
            confidence = source_page_confidence(name, event.get("title", ""), page)
            image_url = event.get("image_url") or image_from_block(final_url, page)
            description = clean_text(event.get("description") or "")
            if not description:
                description = clean_text(page)[:360]
            region = source.get("region") or meta.get("region")
            raw_text = (
                f"공식 페이지 모니터 수집. 기관={name}; "
                f"확인수준={confidence}; 전략={source.get('collection_strategy', '')}; "
                f"원천={final_url}; 설명={description}"
            )
            events.append(
                {
                    "institution_name": name,
                    "content_type": event.get("content_type") or "전시",
                    "title": clean_text(event.get("title") or ""),
                    "start_date": start_date,
                    "end_date": end_date,
                    "location": event.get("location"),
                    "region": region,
                    "price": event.get("price"),
                    "description": description or None,
                    "keywords": event.get("keywords"),
                    "image_url": image_url,
                    "source_url": display_source_url,
                    "status": status,
                    "raw_text": raw_text,
                }
            )

    lines = [
        "# 공식 페이지 모니터 수집 리포트",
        "",
        f"- 모니터 대상 기관: {monitored_sources}개",
        f"- 확인 URL: {len(page_cache)}개",
        f"- 수집 성공 일정: {len(events)}건",
        f"- 수집 실패 일정: {len(failures)}건",
        "",
        "## 실패/보류",
        "",
    ]
    if failures:
        for name, title, error in failures[:80]:
            lines.append(f"- {name} - {title}: {error}")
    else:
        lines.append("- 없음")
    OFFICIAL_PAGE_MONITOR_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if not events:
        raise RuntimeError("공식 페이지 모니터 수집에서 성공한 일정이 없습니다.")
    return events


SCRAPERS = {
    "artsonje": extract_artsonje_exhibitions,
    "ggcf-gcm": extract_gcm_exhibitions,
    "ggcf-gcm-programs": extract_gcm_programs,
    "ggcf-gmoma": extract_gmoma_exhibitions,
    "ggcf-jgpm": extract_jgpm_exhibitions,
    "ggcf-jgpm-programs": extract_jgpm_programs,
    "ggcf-musenet": extract_gyeonggi_museum_exhibitions,
    "ggcf-njp": extract_njp_exhibitions,
    "ggcf-silhak": extract_silhak_exhibitions,
    "gogung": extract_gogung_exhibitions,
    "hangeul": extract_hangeul_museum_exhibitions,
    "inartplatform": extract_inartplatform_exhibitions,
    "leeum": extract_leeum_exhibitions,
    "mmca": extract_mmca_exhibitions,
    "much-programs": extract_much_programs,
    "national-museum": extract_national_museum_current_exhibitions,
    "nfm": extract_nfm_exhibitions,
    "official-page-monitor": extract_official_page_monitor_events,
    "seoul-craft": extract_seoul_craft_museum_exhibitions,
    "seoul-history": extract_seoul_history_exhibitions,
    "seoul284": extract_seoul284_exhibitions,
    "sema": extract_seoul_museum_of_art_exhibitions,
    "sema-programs": extract_seoul_museum_of_art_programs,
    "small-local-deep-gangseo": extract_small_local_gangseo_deep,
    "small-local-deep-seodaemun": extract_small_local_seodaemun_deep,
    "small-local-deep-seongbuk": extract_small_local_seongbuk_deep,
    "soma": extract_soma_exhibitions,
}


def get_institution_id(conn, name):
    row = conn.execute("SELECT id FROM institutions WHERE name = ?", (name,)).fetchone()
    if not row:
        defaults = BRANCH_INSTITUTION_DEFAULTS.get(name)
        if defaults:
            cursor = conn.execute(
                """
                INSERT INTO institutions (
                  name, region, city, category, priority, collection_phase,
                  exhibition_url, program_url, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                  region=excluded.region,
                  city=excluded.city,
                  category=excluded.category,
                  priority=excluded.priority,
                  collection_phase=excluded.collection_phase,
                  exhibition_url=excluded.exhibition_url,
                  program_url=excluded.program_url,
                  notes=excluded.notes,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (
                    name,
                    defaults["region"],
                    defaults["city"],
                    defaults["category"],
                    defaults["priority"],
                    defaults["collection_phase"],
                    defaults["exhibition_url"],
                    defaults["program_url"],
                    defaults["notes"],
                ),
            )
            return cursor.lastrowid or conn.execute(
                "SELECT id FROM institutions WHERE name = ?", (name,)
            ).fetchone()[0]
        raise RuntimeError(f"기관이 DB에 없습니다: {name}")
    return row[0]


def upsert_events(conn, events):
    inserted = 0
    updated = 0
    for event in events:
        institution_id = get_institution_id(conn, event["institution_name"])
        exists = conn.execute(
            """
            SELECT id
            FROM cultural_events
            WHERE institution_id = ? AND title = ? AND start_date IS ? AND source_url = ?
            """,
            (institution_id, event["title"], event["start_date"], event["source_url"]),
        ).fetchone()
        if not exists:
            exists = conn.execute(
                """
                SELECT id
                FROM cultural_events
                WHERE institution_id = ? AND start_date IS ? AND source_url = ?
                """,
                (institution_id, event["start_date"], event["source_url"]),
            ).fetchone()
        if not exists:
            exists = conn.execute(
                """
                SELECT id
                FROM cultural_events
                WHERE institution_id = ? AND title = ? AND start_date IS ?
                """,
                (institution_id, event["title"], event["start_date"]),
            ).fetchone()
        if not exists:
            exists = conn.execute(
                """
                SELECT id
                FROM cultural_events
                WHERE institution_id = ?
                  AND title = ?
                  AND start_date IS ?
                  AND (
                    raw_text LIKE '%등급 보강 수집%'
                    OR raw_text LIKE '공식 페이지 모니터 수집.%'
                  )
                """,
                (institution_id, event["title"], event["start_date"]),
            ).fetchone()
        values = (
            event["content_type"],
            event["title"],
            event["start_date"],
            event["end_date"],
            event["location"],
            event["region"],
            event["price"],
            event["description"],
            event["keywords"],
            clean_image_url(event.get("image_url")),
            event["source_url"],
            event["status"],
            event["raw_text"],
        )
        if exists:
            event_id = exists[0]
            conn.execute(
                """
                UPDATE cultural_events
                SET content_type = ?,
                    title = ?,
                    start_date = ?,
                    end_date = ?,
                    location = ?,
                    region = ?,
                    price = ?,
                    description = ?,
                    keywords = ?,
                    image_url = ?,
                    source_url = ?,
                    status = ?,
                    raw_text = ?,
                    last_checked_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                values + (event_id,),
            )
            updated += 1
        else:
            cursor = conn.execute(
                """
                INSERT INTO cultural_events (
                  institution_id, content_type, title, start_date, end_date, location, region,
                  price, description, keywords, image_url, source_url, status, raw_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (institution_id,) + values,
            )
            event_id = cursor.lastrowid
            inserted += 1
        if event.get("occurrences"):
            conn.execute("DELETE FROM event_occurrences WHERE event_id = ?", (event_id,))
            for occurrence in event["occurrences"]:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO event_occurrences (
                      event_id, occurrence_date, start_time, end_time, label, note, source_url, confidence
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        occurrence["date"],
                        occurrence.get("start_time"),
                        occurrence.get("end_time"),
                        occurrence.get("label"),
                        occurrence.get("note"),
                        occurrence.get("source_url") or event["source_url"],
                        occurrence.get("confidence", 5),
                    ),
                )
    conn.commit()
    return inserted, updated


def build_report(conn, results):
    rows = conn.execute(
        """
        SELECT i.name, e.title, e.start_date, e.end_date, e.location, e.status, e.source_url
        FROM cultural_events e
        JOIN institutions i ON i.id = e.institution_id
        ORDER BY i.priority, i.name, COALESCE(e.end_date, '9999-12-31'), e.title
        """
    ).fetchall()
    lines = [
        "# 최신 수집 결과",
        "",
        f"- 수집기 실행: {len(results)}개",
        f"- 원문에서 발견한 전시: {sum(item['fetched'] for item in results)}건",
        f"- 새로 추가: {sum(item['inserted'] for item in results)}건",
        f"- 갱신: {sum(item['updated'] for item in results)}건",
        f"- DB 내 전체 전시: {len(rows)}건",
        "",
        "## 수집기별 결과",
        "",
    ]
    for item in results:
        lines.append(
            f"- {item['name']}: 발견 {item['fetched']}건, 추가 {item['inserted']}건, 갱신 {item['updated']}건"
        )
    lines.extend([
        "",
        "## 전시 목록",
        "",
    ])
    current_institution = None
    for institution, title, start_date, end_date, location, status, source_url in rows:
        if institution != current_institution:
            current_institution = institution
            lines.append(f"### {institution}")
            lines.append("")
        period = f"{start_date or '?'} ~ {end_date or '?'}"
        lines.append(f"- {title} ({period}, {status})")
        lines.append(f"  - 장소: {location or '확인 필요'}")
        lines.append(f"  - 링크: {source_url}")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="수도권 문화 일정 수집기")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--source",
        action="append",
        choices=sorted(SCRAPERS),
        help="실행할 수집기 이름. 생략하면 모든 수집기를 실행합니다.",
    )
    args = parser.parse_args()

    selected = args.source or sorted(SCRAPERS)
    results = []
    with sqlite3.connect(args.db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_schema(conn)
        for name in selected:
            events = SCRAPERS[name]()
            inserted, updated = upsert_events(conn, events)
            results.append(
                {
                    "name": name,
                    "fetched": len(events),
                    "inserted": inserted,
                    "updated": updated,
                }
            )
        build_report(conn, results)

    for item in results:
        print(
            f"{item['name']}: fetched={item['fetched']} inserted={item['inserted']} updated={item['updated']}"
        )
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
