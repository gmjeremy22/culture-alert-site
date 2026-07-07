import csv
import hashlib
import html
import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent
PROFILE_PATH = BASE_DIR / "expanded-site-profile-results.json"
DB_PATH = BASE_DIR / "culture-alert.sqlite"
CSV_PATH = BASE_DIR / "raw-event-candidates.csv"
JSON_PATH = BASE_DIR / "raw-event-candidates.json"
REPORT_PATH = BASE_DIR / "raw-event-candidates-report.md"

DATE_RE = re.compile(r"20\d{2}[./-]\d{1,2}[./-]\d{1,2}")
BAD_TEXT_RE = re.compile(
    r"(개인정보|이메일|저작권|copyright|로그인|회원가입|오시는 길|사이트맵|보도자료|채용|입찰|공고|공지사항)",
    re.I,
)


def clean_text(value):
    value = re.sub(r"<script.*?</script>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<style.*?</style>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_date(value):
    match = re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})", value or "")
    if not match:
        return None
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def extract_date_pair(text):
    dates = [normalize_date(match.group(0)) for match in DATE_RE.finditer(text)]
    dates = [value for value in dates if value]
    if not dates:
        return None, None
    if len(dates) == 1:
        return dates[0], None
    return dates[0], dates[1]


def fetch(url):
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 culture-alert candidate extractor; personal-use"
        },
    )
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.geturl(), response.read().decode(charset, "replace")


def candidate_title(block):
    patterns = [
        r'<(?:h1|h2|h3|h4|strong)[^>]*>(.*?)</(?:h1|h2|h3|h4|strong)>',
        r'<[^>]+class="[^"]*(?:subject|title|tit|name|o_h1|card-title)[^"]*"[^>]*>(.*?)</[^>]+>',
        r'alt="([^"]{4,160})"',
        r'title="([^"]{4,160})"',
    ]
    options = []
    for pattern in patterns:
        for match in re.finditer(pattern, block, flags=re.S | re.I):
            text = clean_text(match.group(1))
            if not (4 <= len(text) <= 120):
                continue
            if DATE_RE.search(text) or BAD_TEXT_RE.search(text):
                continue
            if text in {"전시", "교육", "프로그램", "행사", "자세히 보기", "바로가기"}:
                continue
            options.append(text)
    if not options:
        plain = clean_text(block)
        pieces = re.split(r"\s{2,}|[|]", plain)
        for piece in pieces:
            piece = piece.strip()
            if 8 <= len(piece) <= 80 and not DATE_RE.search(piece) and not BAD_TEXT_RE.search(piece):
                options.append(piece)
                break
    if not options:
        return None
    options.sort(key=lambda value: (-len(value), value))
    return options[0]


def candidate_image(base_url, block):
    for match in re.finditer(r"<img[^>]+>", block, flags=re.S | re.I):
        tag = match.group(0)
        src_match = re.search(r'(?:src|data-src|data-isrc)="([^"]+)"', tag, flags=re.I)
        if not src_match:
            continue
        src = html.unescape(src_match.group(1)).strip()
        if not src or src.startswith("data:"):
            continue
        if re.search(r"(logo|icon|btn|arrow|sns|facebook|instagram|youtube)", src, re.I):
            continue
        return urljoin(base_url, src)
    return None


def candidate_link(base_url, block, fallback_url):
    links = []
    for href in re.findall(r'<a[^>]+href="([^"]+)"', block, flags=re.S | re.I):
        href = html.unescape(href).strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        if re.search(r"(login|member|privacy|terms)", href, re.I):
            continue
        links.append(urljoin(base_url, href))
    return links[0] if links else fallback_url


def classify_type(text):
    if re.search(r"강연|특강|렉처|lecture|talk", text, re.I):
        return "강연"
    if re.search(r"교육|체험|워크숍|수업|program|education|workshop", text, re.I):
        return "교육"
    if re.search(r"행사|event|공연", text, re.I):
        return "행사"
    return "전시"


def score_candidate(title, text, image_url, source_url, start_date, end_date):
    score = 0
    reasons = []
    if title:
        score += 2
        reasons.append("제목")
    if start_date and end_date:
        score += 3
        reasons.append("기간")
    elif start_date:
        score += 1
        reasons.append("날짜")
    if image_url:
        score += 1
        reasons.append("이미지")
    if source_url:
        score += 1
        reasons.append("링크")
    if re.search(r"전시|교육|강연|프로그램|exhibit|exhibition|program|education", text, re.I):
        score += 2
        reasons.append("문화 키워드")
    if BAD_TEXT_RE.search(text):
        score -= 2
        reasons.append("잡음 가능")
    return score, ", ".join(reasons)


def blocks_around_dates(page):
    blocks = []
    for match in DATE_RE.finditer(page):
        start = max(0, match.start() - 2200)
        end = min(len(page), match.end() + 2200)
        block = page[start:end]
        blocks.append(block)
    return blocks[:80]


def load_pages_to_scan():
    profiles = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    pages = []
    for row in profiles:
        for page in row.get("pages", []):
            profile = page.get("profile") or {}
            if not profile.get("ok"):
                continue
            pages.append(
                {
                    "institution_name": row["institution_name"],
                    "region": row["region"],
                    "city": row["city"],
                    "category": row["category"],
                    "tier": row["tier"],
                    "page_url": page["url"],
                }
            )
    seen = set()
    unique = []
    for page in pages:
        key = (page["institution_name"], page["page_url"].split("#", 1)[0])
        if key in seen:
            continue
        seen.add(key)
        unique.append(page)
    return unique


def extract_from_page(page_info):
    final_url, page = fetch(page_info["page_url"])
    candidates = []
    for block in blocks_around_dates(page):
        text = clean_text(block)
        title = candidate_title(block)
        start_date, end_date = extract_date_pair(text)
        image_url = candidate_image(final_url, block)
        source_url = candidate_link(final_url, block, final_url)
        content_type = classify_type(text)
        score, reason = score_candidate(title, text, image_url, source_url, start_date, end_date)
        if score < 5 or not title:
            continue
        key = hashlib.sha1(
            "|".join(
                [
                    page_info["institution_name"],
                    title,
                    start_date or "",
                    end_date or "",
                    source_url,
                ]
            ).encode("utf-8")
        ).hexdigest()
        candidates.append(
            {
                "candidate_id": key,
                "institution_name": page_info["institution_name"],
                "region": page_info["region"],
                "city": page_info["city"],
                "category": page_info["category"],
                "tier": page_info["tier"],
                "content_type": content_type,
                "title": title,
                "start_date": start_date,
                "end_date": end_date,
                "image_url": image_url,
                "source_url": source_url,
                "page_url": final_url,
                "confidence": score,
                "reason": reason,
                "snippet": text[:500],
                "extracted_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
    return candidates


def dedupe(candidates):
    best = {}
    for candidate in candidates:
        key = (
            candidate["institution_name"],
            candidate["title"],
            candidate["start_date"],
            candidate["end_date"],
        )
        previous = best.get(key)
        if previous is None or candidate["confidence"] > previous["confidence"]:
            best[key] = candidate
    return sorted(
        best.values(),
        key=lambda item: (
            {"A": 0, "B": 1, "C": 2}.get(item["tier"], 9),
            -item["confidence"],
            item["institution_name"],
            item["title"],
        ),
    )


def write_outputs(candidates, page_count, errors):
    fieldnames = [
        "candidate_id",
        "institution_name",
        "region",
        "city",
        "category",
        "tier",
        "content_type",
        "title",
        "start_date",
        "end_date",
        "image_url",
        "source_url",
        "page_url",
        "confidence",
        "reason",
        "snippet",
        "extracted_at",
    ]
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(candidates)
    JSON_PATH.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS event_candidates (
              candidate_id TEXT PRIMARY KEY,
              institution_name TEXT,
              region TEXT,
              city TEXT,
              category TEXT,
              tier TEXT,
              content_type TEXT,
              title TEXT,
              start_date TEXT,
              end_date TEXT,
              image_url TEXT,
              source_url TEXT,
              page_url TEXT,
              confidence REAL,
              reason TEXT,
              snippet TEXT,
              extracted_at TEXT
            )
            """
        )
        conn.execute("DELETE FROM event_candidates")
        for candidate in candidates:
            conn.execute(
                """
                INSERT INTO event_candidates (
                  candidate_id, institution_name, region, city, category, tier, content_type,
                  title, start_date, end_date, image_url, source_url, page_url, confidence,
                  reason, snippet, extracted_at
                )
                VALUES (
                  :candidate_id, :institution_name, :region, :city, :category, :tier, :content_type,
                  :title, :start_date, :end_date, :image_url, :source_url, :page_url, :confidence,
                  :reason, :snippet, :extracted_at
                )
                """,
                candidate,
            )
        conn.commit()

    lines = [
        "# 원시 전시/교육 후보 추출 결과",
        "",
        f"- 실행 시각: {datetime.now().isoformat(timespec='seconds')}",
        f"- 훑은 페이지: {page_count}개",
        f"- 추출 후보: {len(candidates)}건",
        f"- 오류: {len(errors)}건",
        "",
        "## 상위 후보",
        "",
    ]
    for candidate in candidates[:80]:
        period = " ~ ".join(
            value for value in [candidate["start_date"], candidate["end_date"]] if value
        ) or "날짜 확인 필요"
        lines.append(
            f"- [{candidate['confidence']}] {candidate['title']} / {candidate['institution_name']} / {period}"
        )
        lines.append(f"  - 유형: {candidate['content_type']} / 이유: {candidate['reason']}")
        lines.append(f"  - 링크: {candidate['source_url']}")
        if candidate["image_url"]:
            lines.append(f"  - 이미지: {candidate['image_url']}")
    if errors:
        lines.extend(["", "## 오류", ""])
        for page, error in errors[:50]:
            lines.append(f"- {page}: {error}")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main():
    pages = load_pages_to_scan()
    all_candidates = []
    errors = []
    for index, page in enumerate(pages, start=1):
        print(f"[{index}/{len(pages)}] {page['institution_name']} {page['page_url']}")
        try:
            all_candidates.extend(extract_from_page(page))
        except Exception as exc:
            errors.append((page["page_url"], repr(exc)))
        time.sleep(0.8)
    candidates = dedupe(all_candidates)
    write_outputs(candidates, len(pages), errors)
    print(f"candidates={len(candidates)}")
    print(f"csv={CSV_PATH}")
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
