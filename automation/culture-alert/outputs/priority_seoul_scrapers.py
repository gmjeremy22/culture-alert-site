import html as html_lib
import hashlib
import json
import re
import ssl
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from lxml import html as lxml_html


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/125 Safari/537.36"
)
DATE_TOKEN_RE = re.compile(r"20\d{2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{1,2}")
GENERIC_TITLES = {
    "current",
    "current exhibition",
    "current exhibitions",
    "exhibitions",
    "전시",
    "현재전시",
    "현재 전시",
    "자세히 보기",
    "learn more",
    "read more",
}


def clean_text(value):
    if hasattr(value, "text_content"):
        value = value.text_content()
    text = re.sub(r"<script.*?</script>", " ", str(value or ""), flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def relaxed_context(low_security=False):
    context = ssl.create_default_context()
    if low_security:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        try:
            context.set_ciphers("DEFAULT:@SECLEVEL=0")
        except ssl.SSLError:
            pass
    return context


def url_variants(url):
    parsed = urlparse(url)
    variants = [url]
    for scheme in (parsed.scheme, "https", "http"):
        for host in (parsed.netloc, parsed.netloc.removeprefix("www."), f"www.{parsed.netloc.removeprefix('www.')}"):
            candidate = urlunparse(
                (scheme, host, parsed.path, parsed.params, parsed.query, parsed.fragment)
            )
            if candidate not in variants:
                variants.append(candidate)
    return variants


def fetch_html(url):
    errors = []
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    for candidate in url_variants(url):
        for low_security in (False, True):
            try:
                request = Request(candidate, headers=headers)
                with urlopen(
                    request, timeout=28, context=relaxed_context(low_security)
                ) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    return response.read().decode(charset, "replace"), response.geturl()
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")
    raise RuntimeError(" / ".join(errors[-4:]))


def fetch_json(url):
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.daelimmuseum.org",
            "Referer": "https://www.daelimmuseum.org/",
        },
    )
    with urlopen(request, timeout=28, context=relaxed_context()) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def valid_date(year, month, day):
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def iso_date(year, month, day):
    parsed = valid_date(year, month, day)
    return parsed.isoformat() if parsed else None


def parse_period(text):
    value = clean_text(text).replace("−", "-").replace("—", "-").replace("–", "-")
    numeric = re.search(
        r"(20\d{2})\s*[./년-]\s*(\d{1,2})\s*[./월-]\s*(\d{1,2})\s*일?"
        r"\s*(?:~|-|부터)\s*"
        r"(?:(20\d{2})\s*[./년-]\s*)?(\d{1,2})\s*[./월-]\s*(\d{1,2})",
        value,
    )
    if numeric:
        start = iso_date(numeric.group(1), numeric.group(2), numeric.group(3))
        end = iso_date(
            numeric.group(4) or numeric.group(1), numeric.group(5), numeric.group(6)
        )
        if start and end:
            return start, end

    korean = re.search(
        r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일?"
        r"\s*(?:~|-|부터)\s*"
        r"(?:(20\d{2})\s*년\s*)?(\d{1,2})\s*월\s*(\d{1,2})",
        value,
    )
    if korean:
        start = iso_date(korean.group(1), korean.group(2), korean.group(3))
        end = iso_date(
            korean.group(4) or korean.group(1), korean.group(5), korean.group(6)
        )
        if start and end:
            return start, end

    english = re.search(
        r"([A-Za-z]{3,9})\s+(\d{1,2})\s*-\s*([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(20\d{2})",
        value,
    )
    if english:
        try:
            start = datetime.strptime(
                f"{english.group(1)} {english.group(2)} {english.group(5)}", "%b %d %Y"
            ).date()
        except ValueError:
            try:
                start = datetime.strptime(
                    f"{english.group(1)} {english.group(2)} {english.group(5)}",
                    "%B %d %Y",
                ).date()
            except ValueError:
                start = None
        try:
            end = datetime.strptime(
                f"{english.group(3)} {english.group(4)} {english.group(5)}", "%b %d %Y"
            ).date()
        except ValueError:
            try:
                end = datetime.strptime(
                    f"{english.group(3)} {english.group(4)} {english.group(5)}",
                    "%B %d %Y",
                ).date()
            except ValueError:
                end = None
        if start and end:
            return start.isoformat(), end.isoformat()

    dates = []
    for match in DATE_TOKEN_RE.finditer(value):
        parts = re.findall(r"\d+", match.group(0))
        parsed = iso_date(parts[0], parts[1], parts[2])
        if parsed and parsed not in dates:
            dates.append(parsed)
    if len(dates) >= 2:
        return dates[0], dates[1]
    if dates:
        return dates[0], None
    return None, None


def infer_status(start_date, end_date):
    today = date.today().isoformat()
    if end_date and end_date < today:
        return "종료"
    if start_date and start_date > today:
        return "예정"
    return "진행중"


def meta_content(document, prop):
    values = document.xpath(
        f'//meta[@property="{prop}"]/@content | //meta[@name="{prop}"]/@content'
    )
    return clean_text(values[0]) if values else ""


def usable_title(value):
    text = clean_text(value)
    if not (2 <= len(text) <= 130):
        return False
    if text.casefold() in GENERIC_TITLES:
        return False
    if re.fullmatch(r"[\d\s./~-]+", text):
        return False
    if "재단은" in text or "enen메뉴" in text or text.startswith("닫음"):
        return False
    return True


def strip_title_suffix(value):
    text = clean_text(value)
    reserved = re.match(r"^\[([^\]]+)\]\s*전시관람 예약", text)
    if reserved:
        return reserved.group(1).strip()
    bracketed = re.match(r"^(《[^》]+》)", text)
    if bracketed:
        return bracketed.group(1)
    marker = re.search(r"\s+20\d{2}\s*[./-]", text)
    if marker:
        text = text[: marker.start()].strip()
    text = re.sub(
        r"\s*[|–-]\s*(?:환기미술관|김종영미술관|일민미술관|한원미술관)(?:\s*\|.*)?\s*$",
        "",
        text,
    )
    return text.strip(" -|·")


def best_anchor_title(anchor):
    candidates = []
    for node in anchor.xpath(
        './/*[self::h1 or self::h2 or self::h3 or self::h4 or self::strong '
        'or contains(@class,"title") or contains(@class,"tit")]'
    ):
        candidates.append(clean_text(node.text_content()))
    candidates.append(clean_text(anchor.text_content()))
    candidates = [strip_title_suffix(value) for value in candidates]
    candidates = [value for value in candidates if usable_title(value)]
    if not candidates:
        return ""
    candidates.sort(key=lambda value: (DATE_TOKEN_RE.search(value) is not None, len(value)))
    return candidates[0]


def anchor_context(anchor):
    options = []
    node = anchor
    for _depth in range(5):
        node = node.getparent()
        if node is None:
            break
        text = clean_text(node.text_content())
        if 8 <= len(text) <= 1800:
            options.append(text)
        if parse_period(text) != (None, None) and len(text) <= 1000:
            return text
    return min(options, key=len) if options else clean_text(anchor.text_content())


def first_image(document, base_url):
    image = meta_content(document, "og:image")
    if image and not re.search(r"logo|icon|og_logo|/sub/tit_", image, re.I):
        return urljoin(base_url, image)
    for src in document.xpath('//img/@src | //img/@data-src | //img/@data-lazy-src'):
        if not src or src.startswith("data:"):
            continue
        if re.search(
            r"logo|icon|arrow|sns|spinner|loading|og_logo|/sub/tit_|menu|gnb|top_",
            src,
            re.I,
        ):
            continue
        return urljoin(base_url, src)
    for srcset in document.xpath('//img/@srcset | //img/@data-srcset'):
        candidates = [
            item.strip().split()[0]
            for item in srcset.split(",")
            if item.strip() and not item.strip().startswith("data:")
        ]
        for src in reversed(candidates):
            if not re.search(r"logo|icon|arrow|sns|spinner|loading|menu|gnb", src, re.I):
                return urljoin(base_url, src)
    return None


def fetch_details(links):
    def one(item):
        try:
            page, final_url = fetch_html(item["url"])
            return item, page, final_url, None
        except Exception as exc:
            return item, "", item["url"], str(exc)

    results = []
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(links)))) as executor:
        futures = [executor.submit(one, item) for item in links]
        for future in as_completed(futures):
            results.append(future.result())
    return results


def linked_exhibitions(
    institution_name,
    listing_urls,
    link_pattern,
    location,
    include_unknown_dates=False,
    anchor_text_pattern=None,
):
    link_map = {}
    for listing_url in listing_urls:
        page, final_url = fetch_html(listing_url)
        document = lxml_html.fromstring(page)
        document.make_links_absolute(final_url)
        for anchor in document.xpath('//a[@href]'):
            href = anchor.get("href") or ""
            if not re.search(link_pattern, href, re.I):
                continue
            raw_anchor_text = clean_text(anchor.text_content())
            if anchor_text_pattern and not re.search(
                anchor_text_pattern, raw_anchor_text, re.I
            ):
                continue
            if href.rstrip("/") == final_url.rstrip("/"):
                continue
            title = best_anchor_title(anchor)
            context = anchor_context(anchor)
            current = link_map.get(href)
            candidate = {"url": href, "title": title, "context": context}
            if current is None:
                link_map[href] = candidate
            else:
                if len(title) > len(current["title"]):
                    current["title"] = title
                current_period = parse_period(current["context"])
                candidate_period = parse_period(context)
                if bool(candidate_period[1]) > bool(current_period[1]):
                    current["context"] = context

    events = []
    for item, page, final_url, error in fetch_details(list(link_map.values())):
        if error:
            continue
        document = lxml_html.fromstring(page)
        document.make_links_absolute(final_url)
        context = item["context"]
        body = clean_text(document.text_content())
        title_candidates = [
            item["title"],
            meta_content(document, "og:title"),
            clean_text(document.xpath("string(//h1[1])")),
            clean_text(document.xpath("string(//h2[1])")),
            clean_text(document.xpath("string(//title)")),
        ]
        title = next(
            (strip_title_suffix(value) for value in title_candidates if usable_title(strip_title_suffix(value))),
            "",
        )
        if not title:
            continue
        if title.casefold() == institution_name.casefold() or title.casefold().replace(" ", "") in {
            "songeun",
            "송은",
        }:
            continue
        start_date, end_date = parse_period(context)
        if not start_date:
            start_date, end_date = parse_period(body)
        if not start_date and not include_unknown_dates:
            continue
        status = infer_status(start_date, end_date)
        if status == "종료":
            continue
        description = meta_content(document, "og:description")
        if (
            not description
            or len(description) < 20
            or "전시관람 예약" in description
            or description == item["title"]
        ):
            paragraphs = [
                clean_text(node.text_content())
                for node in document.xpath("//main//p | //article//p | //div[contains(@class,'content')]//p")
            ]
            description = next((text for text in paragraphs if len(text) >= 40), "")
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
                "description": description[:1200] or None,
                "keywords": None,
                "image_url": first_image(document, final_url),
                "source_url": final_url,
                "status": status,
                "raw_text": f"priority dedicated scraper; institution={institution_name}; context={context[:700]}",
            }
        )
    return dedupe(events)


def dated_blocks(institution_name, url, location):
    page, final_url = fetch_html(url)
    document = lxml_html.fromstring(page)
    document.make_links_absolute(final_url)
    events = []
    for node in document.xpath(
        '//*[@data-type="song_eun_text_module_version"]'
        ' | //div[contains(concat(" ", normalize-space(@class), " "), " exhibition-loop-item ")]'
        ' | //article | //section | //li'
    ):
        text = clean_text(node.text_content())
        if not (12 <= len(text) <= 1800):
            continue
        start_date, end_date = parse_period(text)
        if not start_date:
            continue
        title_candidates = [
            clean_text(value.text_content())
            for value in node.xpath(
                './/*[self::h1 or self::h2 or self::h3 or self::h4 or self::strong][1]'
            )
        ]
        date_match = re.search(r"20\d{2}\s*[./년-]", text)
        if date_match:
            title_candidates.append(text[: date_match.start()].strip())
        title = next(
            (strip_title_suffix(value) for value in title_candidates if usable_title(strip_title_suffix(value))),
            "",
        )
        if not title:
            continue
        if title.casefold() == institution_name.casefold() or title.casefold().replace(" ", "") in {
            "songeun",
            "송은",
        }:
            continue
        status = infer_status(start_date, end_date)
        if status == "종료":
            continue
        image = None
        for src in node.xpath('.//img/@src | .//img/@data-src | .//img/@data-lazy-src'):
            if src and not src.startswith("data:"):
                image = urljoin(final_url, src)
                break
        if not image:
            for srcset in node.xpath('.//img/@srcset | .//img/@data-srcset'):
                candidates = [
                    item.strip().split()[0]
                    for item in srcset.split(",")
                    if item.strip() and not item.strip().startswith("data:")
                ]
                if candidates:
                    image = urljoin(final_url, candidates[-1])
                    break
        source_key = hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]
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
                "description": text[:1200],
                "keywords": None,
                "image_url": image,
                "source_url": f"{final_url}#culture-alert-{source_key}",
                "status": status,
                "raw_text": f"priority dedicated dated-block scraper; institution={institution_name}; block={text[:700]}",
            }
        )
    return dedupe(events)


def dedupe(events):
    best = {}
    for event in events:
        key = (event["institution_name"], event["title"], event.get("start_date"))
        previous = best.get(key)
        if previous is None or len(event.get("description") or "") > len(
            previous.get("description") or ""
        ):
            best[key] = event
    return sorted(
        best.values(),
        key=lambda item: (item.get("start_date") or "9999-12-31", item["title"]),
    )


def prefer_shortest_per_period(events):
    best = {}
    for event in events:
        key = (event["institution_name"], event.get("start_date"), event.get("end_date"))
        previous = best.get(key)
        if previous is None or len(event["title"]) < len(previous["title"]):
            best[key] = event
    return sorted(
        best.values(),
        key=lambda item: (item.get("start_date") or "9999-12-31", item["title"]),
    )


def extract_pompidou_hanwha():
    return linked_exhibitions(
        "퐁피두센터 한화 서울",
        [
            "https://www.centrepompidou-hanwha.kr/exhibition/list",
            "https://www.centrepompidou-hanwha.kr/exhibition/list?status=scheduled",
        ],
        r"/exhibition/detail",
        "퐁피두센터 한화 서울",
    )


def extract_dmuseum():
    endpoint = (
        "https://api.daelimmuseum.org/v1/program/exhibition/"
        "searchCurrentExhibition?pageNo=1&prgPlcCds=PG00701"
    )
    payload = fetch_json(endpoint)
    rows = ((payload.get("data") or {}).get("data") or [])
    events = []
    for row in rows:
        title = clean_text(row.get("prgNm"))
        if not title:
            continue
        start_date = row.get("prgStartDt")
        end_date = row.get("prgEndDt")
        status = infer_status(start_date, end_date)
        if status == "종료":
            continue
        event_id = row.get("prgIdx")
        events.append(
            {
                "institution_name": "디뮤지엄",
                "content_type": "전시",
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "location": clean_text(row.get("prgPlcVal")) or "디뮤지엄",
                "region": "서울",
                "price": None,
                "description": clean_text(row.get("prgDesc") or row.get("ehbGenre")) or None,
                "keywords": clean_text(row.get("ehbGenre")) or None,
                "image_url": row.get("prgImgFileUrl"),
                "source_url": f"https://www.daelimmuseum.org/exhibition/current/{event_id}",
                "status": status,
                "raw_text": f"priority dedicated API scraper; endpoint={endpoint}; id={event_id}",
            }
        )
    return dedupe(events)


def extract_apma():
    return linked_exhibitions(
        "아모레퍼시픽미술관",
        ["https://apma.amorepacific.com/contents/exhibition/index.do"],
        r"/contents/exhibition/\d+/view\.do",
        "아모레퍼시픽미술관",
        anchor_text_pattern=r"전시관람 예약",
    )


def extract_arko():
    return linked_exhibitions(
        "아르코미술관",
        ["https://www.arko.or.kr/artcenter/"],
        r"/artcenter/board/view/506\?",
        "아르코미술관",
    )


def extract_kumho():
    return linked_exhibitions(
        "금호미술관",
        [
            "http://www.kumhomuseum.com/designer/skin/02/01.html",
            "http://www.kumhomuseum.com/designer/skin/02/03.html",
        ],
        r"detail_exb\.html",
        "금호미술관",
    )


def extract_kimchongyung():
    return linked_exhibitions(
        "김종영미술관",
        [
            "http://kimchongyung.com/archives/exhibition_type/current",
            "http://kimchongyung.com/archives/exhibition_type/upcoming",
        ],
        r"/archives/exhibition/",
        "김종영미술관",
    )


def extract_whanki():
    return linked_exhibitions(
        "환기미술관",
        ["http://whankimuseum.org/museum/exhibition/current/"],
        r"/exhibitions/",
        "환기미술관",
    )


def extract_total():
    return linked_exhibitions(
        "토탈미술관",
        ["http://totalmuseum.org/category/exhibition/current-exhibition/"],
        r"/exhibition/current-exhibition/",
        "토탈미술관",
        include_unknown_dates=True,
    )


def extract_hanwon():
    return linked_exhibitions(
        "한원미술관",
        ["http://www.hanwon.org/exhibition/exhibition/?dataKey=present#nowExhibition"],
        r"/display/|post_type=display",
        "한원미술관",
        include_unknown_dates=True,
    )


def extract_myart():
    return linked_exhibitions(
        "마이아트뮤지엄",
        [
            "http://myartmuseum.co.kr/exhibit/exhibit_ing.php",
            "http://myartmuseum.co.kr/exhibit/exhibit_sch.php",
        ],
        r"ptype=view.*(?:catcode=10000000|catcode=11000000)",
        "마이아트뮤지엄",
    )


def extract_songeun():
    return prefer_shortest_per_period(
        dated_blocks("송은", "https://www.songeun.or.kr/", "송은")
    )


def extract_ilmin():
    return dated_blocks("일민미술관", "https://ilmin.org/exhibitions/current/", "일민미술관")


PRIORITY_SCRAPERS = {
    "priority-apma": extract_apma,
    "priority-arko": extract_arko,
    "priority-dmuseum": extract_dmuseum,
    "priority-ilmin": extract_ilmin,
    "priority-kimchongyung": extract_kimchongyung,
    "priority-kumho": extract_kumho,
    "priority-myart": extract_myart,
    "priority-pompidou-hanwha": extract_pompidou_hanwha,
    "priority-songeun": extract_songeun,
    "priority-total": extract_total,
    "priority-whanki": extract_whanki,
    "priority-hanwon": extract_hanwon,
}

PRIORITY_SOURCE_INSTITUTIONS = {
    "priority-apma": "아모레퍼시픽미술관",
    "priority-arko": "아르코미술관",
    "priority-dmuseum": "디뮤지엄",
    "priority-ilmin": "일민미술관",
    "priority-kimchongyung": "김종영미술관",
    "priority-kumho": "금호미술관",
    "priority-myart": "마이아트뮤지엄",
    "priority-pompidou-hanwha": "퐁피두센터 한화 서울",
    "priority-songeun": "송은",
    "priority-total": "토탈미술관",
    "priority-whanki": "환기미술관",
    "priority-hanwon": "한원미술관",
}


def reconcile_priority_events(conn, source_name, current_events):
    """End missing rows only after a priority source completed successfully."""
    institution_name = PRIORITY_SOURCE_INSTITUTIONS.get(source_name)
    if not institution_name:
        return 0
    row = conn.execute(
        "SELECT id FROM institutions WHERE name = ?", (institution_name,)
    ).fetchone()
    if not row:
        return 0

    current_urls = {event.get("source_url") for event in current_events if event.get("source_url")}
    existing = conn.execute(
        """
        SELECT id, source_url
        FROM cultural_events
        WHERE institution_id = ?
          AND raw_text LIKE 'priority dedicated%'
          AND status != '종료'
        """,
        (row[0],),
    ).fetchall()
    missing_ids = [event_id for event_id, source_url in existing if source_url not in current_urls]
    if not missing_ids:
        return 0
    placeholders = ",".join("?" for _ in missing_ids)
    cursor = conn.execute(
        f"""
        UPDATE cultural_events
        SET status = '종료', last_checked_at = CURRENT_TIMESTAMP
        WHERE id IN ({placeholders})
        """,
        missing_ids,
    )
    conn.commit()
    return cursor.rowcount
