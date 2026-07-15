"""Conservative official-site collector for institutions without dedicated scrapers.

It intentionally promotes an event only when an official page contains a usable
title and an explicit date range. Sites that render their listings entirely in
JavaScript are recorded for follow-up instead of producing guesswork cards.
"""

from __future__ import annotations

import html
import re
import sqlite3
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "culture-alert.sqlite"
TODAY = date.today()
MAX_DETAIL_PAGES = 3

# These institutions were originally backfilled from official references but
# did not yet have a durable, dedicated source parser.
ADAPTIVE_INSTITUTION_NAMES = (
    "돈의문박물관마을",
    "서울대학교미술관",
    "성곡미술관",
    "코리아나미술관 스페이스씨",
    "한양도성박물관",
    "환기미술관",
    "인천상륙작전기념관",
    "CICA 미술관",
    "김중업건축박물관",
    "김포아트빌리지 아트센터",
    "아트센터 화이트블럭",
    "안양박물관",
    "안양파빌리온",
    "용인시박물관",
    "경희궁",
    "고려대학교박물관",
    "김달진미술자료박물관",
    "김세중미술관",
    "농업박물관",
    "목인박물관 목석원",
    "서대문형무소역사관",
    "서울교육박물관",
    "성북구립미술관",
    "성북선잠박물관",
    "아라리오뮤지엄 인 스페이스",
    "이화여자대학교 자연사박물관",
    "한국은행 화폐박물관",
    "혜곡최순우기념관",
)

# A few official portals host several facilities. Their event cards are only
# usable when the surrounding text identifies the intended venue.
VENUE_HINTS = {
    "김포아트빌리지 아트센터": ("아트빌리지", "아트센터"),
    "안양박물관": ("안양박물관",),
    "안양파빌리온": ("안양파빌리온", "APAP"),
    "김중업건축박물관": ("김중업", "건축박물관"),
    "한양도성박물관": ("한양도성",),
    "경희궁": ("경희궁",),
}

DATE_RE = re.compile(r"(20\d{2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{1,2})")
DATE_RANGE_RE = re.compile(
    r"(20\d{2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,2})\s*(?:~|\-|to|until)\s*"
    r"(20\d{2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,2})",
    re.I,
)
LINK_HINT_RE = re.compile(
    r"(전시|교육|강연|행사|프로그램|일정|기획|exhibit|exhibition|program|education|event|schedule|whatson)",
    re.I,
)
DETAIL_URL_HINT_RE = re.compile(r"(display|exhibition|exhibit|board|view|article|show|program|calendar|event)", re.I)
EMPTY_MARKER_RE = re.compile(
    r"(등록된 게시물이 없습니다|진행 중인 전시.*없|현재 전시.*없|no current exhibition|no exhibition)",
    re.I,
)
BAD_TITLE_RE = re.compile(
    r"(로그인|회원|개인정보|이용약관|공지사항|당첨자발표|더보기|자세히|전체보기|전시 안내|전시 일정|"
    r"교육 안내|program schedule|copyright)",
    re.I,
)


@dataclass
class AdaptiveCollectionResult:
    events: list[dict]
    checks: dict[str, tuple[str, str]]


def clean_text(value: str) -> str:
    value = re.sub(r"<script.*?</script>", " ", value or "", flags=re.S | re.I)
    value = re.sub(r"<style.*?</style>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def normalize_date(value: str) -> str | None:
    match = DATE_RE.search(value or "")
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return None


def fetch_html(url: str) -> tuple[str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; culture-alert/1.0; personal-use)",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
        },
    )
    parsed = urlparse(url)
    alternate_scheme = "http" if parsed.scheme == "https" else "https"
    alternate_host = (
        parsed.netloc.removeprefix("www.")
        if parsed.netloc.startswith("www.")
        else f"www.{parsed.netloc}"
    )
    variants = [
        url,
        urlunparse((alternate_scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)),
        urlunparse((parsed.scheme, alternate_host, parsed.path, parsed.params, parsed.query, parsed.fragment)),
    ]
    errors = []
    for candidate in dict.fromkeys(variants):
        request = Request(candidate, headers=request.headers)
        for low_security in (False, True):
            try:
                context = ssl.create_default_context()
                if low_security:
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                    try:
                        context.set_ciphers("DEFAULT:@SECLEVEL=0")
                    except ssl.SSLError:
                        pass
                with urlopen(request, timeout=6, context=context) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    return response.geturl(), response.read().decode(charset, "replace")
            except Exception as exc:
                errors.append(str(exc))
    raise RuntimeError(" / ".join(errors[-3:]))


def same_site(first_url: str, second_url: str) -> bool:
    first = urlparse(first_url).netloc.removeprefix("www.")
    second = urlparse(second_url).netloc.removeprefix("www.")
    return bool(first and second and first == second)


def candidate_links(base_url: str, page: str) -> list[str]:
    found = []
    seen = set()
    for href, label in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', page, re.S | re.I):
        href = html.unescape(href).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(base_url, href)
        if not same_site(base_url, absolute):
            continue
        text = clean_text(label)
        combined = f"{absolute} {text}"
        if not (LINK_HINT_RE.search(combined) or DETAIL_URL_HINT_RE.search(absolute)):
            continue
        key = absolute.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        score = 0
        if LINK_HINT_RE.search(combined):
            score += 3
        if DETAIL_URL_HINT_RE.search(absolute):
            score += 2
        if text:
            score += 1
        found.append((score, key))
    return [url for _score, url in sorted(found, key=lambda item: (-item[0], item[1]))[:MAX_DETAIL_PAGES]]


def extract_title(block: str) -> str | None:
    candidates = []
    for pattern in (
        r"<(?:h1|h2|h3|h4|strong)[^>]*>(.*?)</(?:h1|h2|h3|h4|strong)>",
        r'<[^>]+class=["\'][^"\']*(?:title|tit|subject|name|card)[^"\']*["\'][^>]*>(.*?)</[^>]+>',
        r'alt=["\']([^"\']{4,180})["\']',
        r'title=["\']([^"\']{4,180})["\']',
    ):
        for match in re.finditer(pattern, block, re.S | re.I):
            title = clean_text(match.group(1))
            if not (4 <= len(title) <= 150) or BAD_TITLE_RE.search(title) or DATE_RE.search(title):
                continue
            candidates.append(title)
    if not candidates:
        return None
    return sorted(set(candidates), key=lambda value: (-len(value), value))[0]


def extract_image(base_url: str, block: str) -> str | None:
    for tag in re.findall(r"<img[^>]*>", block, re.S | re.I):
        match = re.search(r'(?:src|data-src|data-original)=["\']([^"\']+)["\']', tag, re.I)
        if not match:
            continue
        source = html.unescape(match.group(1)).strip()
        if not source or source.startswith("data:"):
            continue
        if re.search(r"(logo|icon|btn|arrow|facebook|instagram|youtube)", source, re.I):
            continue
        return urljoin(base_url, source)
    return None


def extract_link(base_url: str, block: str) -> str:
    for href in re.findall(r'<a[^>]+href=["\']([^"\']+)["\']', block, re.S | re.I):
        href = html.unescape(href).strip()
        if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
            return urljoin(base_url, href)
    return base_url


def content_type(text: str) -> str:
    if re.search(r"(강연|특강|토크|lecture|talk)", text, re.I):
        return "강연"
    if re.search(r"(교육|체험|워크숍|workshop|education|program)", text, re.I):
        return "교육"
    if re.search(r"(행사|event)", text, re.I):
        return "행사"
    return "전시"


def event_blocks(page: str) -> list[str]:
    blocks = []
    for match in DATE_RANGE_RE.finditer(page):
        blocks.append(page[max(0, match.start() - 1800): min(len(page), match.end() + 1800)])
    return blocks[:80]


def extract_events(institution: dict, pages: list[tuple[str, str]]) -> list[dict]:
    events = []
    seen = set()
    for page_url, page in pages:
        for block in event_blocks(page):
            range_match = DATE_RANGE_RE.search(block)
            if not range_match:
                continue
            start_date = normalize_date(range_match.group(1))
            end_date = normalize_date(range_match.group(2))
            if not start_date or not end_date or end_date < TODAY.isoformat():
                continue
            title = extract_title(block)
            if not title:
                continue
            text = clean_text(block)
            source_url = extract_link(page_url, block)
            hints = VENUE_HINTS.get(institution["name"], ())
            if hints and not any(hint.casefold() in f"{title} {text}".casefold() for hint in hints):
                continue
            key = (title, start_date, end_date)
            if key in seen:
                continue
            seen.add(key)
            events.append(
                {
                    "institution_name": institution["name"],
                    "content_type": content_type(f"{title} {text}"),
                    "title": title,
                    "start_date": start_date,
                    "end_date": end_date,
                    "location": institution["name"],
                    "region": institution["region"],
                    "price": None,
                    "description": text[:700],
                    "keywords": None,
                    "image_url": extract_image(page_url, block),
                    "source_url": source_url,
                    "status": "예정" if start_date > TODAY.isoformat() else "진행중",
                    "raw_text": "adaptive official collector; verified title and explicit date range; " + text[:1000],
                }
            )
    return events


def targets() -> list[dict]:
    placeholders = ",".join("?" for _ in ADAPTIVE_INSTITUTION_NAMES)
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            f"""
            SELECT name, region, exhibition_url, program_url
            FROM institutions
            WHERE active = 1 AND name IN ({placeholders})
            ORDER BY priority, name
            """,
            ADAPTIVE_INSTITUTION_NAMES,
        ).fetchall()
    return [
        {"name": name, "region": region, "urls": [url for url in (exhibition_url, program_url) if url]}
        for name, region, exhibition_url, program_url in rows
    ]


def collect_one(institution: dict) -> tuple[str, list[dict], tuple[str, str]]:
    """Fetch one institution without allowing a single slow site to stop the batch."""
    if not institution["urls"]:
        return institution["name"], [], ("failed", "official exhibition/program URL is missing")
    pages = []
    errors = []
    for root_url in institution["urls"]:
        try:
            final_url, page = fetch_html(root_url)
            pages.append((final_url, page))
            for detail_url in candidate_links(final_url, page):
                try:
                    pages.append(fetch_html(detail_url))
                except Exception as exc:  # Detail pages are optional evidence.
                    errors.append(str(exc))
        except Exception as exc:
            errors.append(str(exc))
    if not pages:
        return institution["name"], [], ("failed", "; ".join(errors)[:600])
    found = extract_events(institution, pages)
    if found:
        return institution["name"], found, ("collected", f"official pages produced {len(found)} dated event(s)")
    if any(EMPTY_MARKER_RE.search(clean_text(page)) for _url, page in pages):
        return institution["name"], [], ("empty", "official pages explicitly report no current listing")
    return (
        institution["name"],
        [],
        ("review", "official pages loaded, but no title/date pair met the automatic quality threshold"),
    )


def collect_adaptive_official_events() -> AdaptiveCollectionResult:
    events = []
    checks: dict[str, tuple[str, str]] = {}
    institutions = targets()
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(institutions)))) as executor:
        futures = [executor.submit(collect_one, institution) for institution in institutions]
        for future in as_completed(futures):
            name, found, check = future.result()
            events.extend(found)
            checks[name] = check
    return AdaptiveCollectionResult(events=events, checks=checks)
