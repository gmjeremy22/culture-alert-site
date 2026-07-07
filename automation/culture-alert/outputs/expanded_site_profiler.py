import csv
import html
import json
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent
INPUT_PATH = BASE_DIR / "expanded-institution-candidates.csv"
JSON_PATH = BASE_DIR / "expanded-site-profile-results.json"
REPORT_PATH = BASE_DIR / "expanded-site-profile-report.md"

DATE_RE = re.compile(
    r"(?:20\d{2}[./-]\d{1,2}[./-]\d{1,2}|20\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일)"
)
LINK_HINT_RE = re.compile(
    r"(전시|교육|강연|행사|프로그램|문화행사|소식|일정|exhibit|exhibition|program|education|event|whatson|plan|calendar|schedule)",
    re.I,
)
BAD_LINK_RE = re.compile(r"(login|member|privacy|terms|facebook|instagram|youtube|kakao|naver)", re.I)


def clean_text(value):
    value = re.sub(r"<script.*?</script>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<style.*?</style>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def same_site(url, candidate):
    try:
        base = urlparse(url).netloc.replace("www.", "")
        other = urlparse(candidate).netloc.replace("www.", "")
        return base == other
    except Exception:
        return False


def fetch(url):
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 culture-alert expanded profiler; personal-use"
        },
    )
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.geturl(), response.read().decode(charset, "replace")


def extract_links(base_url, page):
    links = []
    for href, label in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, flags=re.S | re.I):
        href = html.unescape(href).strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        absolute = urljoin(base_url, href)
        text = clean_text(label)
        combined = f"{absolute} {text}"
        if BAD_LINK_RE.search(combined):
            continue
        if not LINK_HINT_RE.search(combined):
            continue
        links.append({"url": absolute, "label": text[:140]})

    seen = set()
    unique = []
    for item in links:
        key = item["url"].split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:40]


def extract_images(base_url, page):
    images = []
    for match in re.finditer(r"<img[^>]+>", page, flags=re.S | re.I):
        tag = match.group(0)
        src_match = re.search(r'(?:src|data-src|data-isrc)="([^"]+)"', tag, flags=re.I)
        if not src_match:
            continue
        src = html.unescape(src_match.group(1)).strip()
        if not src:
            continue
        alt_match = re.search(r'alt="([^"]*)"', tag, flags=re.I)
        alt_text = clean_text(alt_match.group(1)) if alt_match else ""
        images.append({"url": urljoin(base_url, src), "alt": alt_text[:140]})
    return images[:40]


def extract_date_snippets(page):
    text = clean_text(page)
    snippets = []
    for match in DATE_RE.finditer(text):
        start = max(0, match.start() - 90)
        end = min(len(text), match.end() + 140)
        snippets.append(text[start:end])
    seen = set()
    unique = []
    for snippet in snippets:
        if snippet in seen:
            continue
        seen.add(snippet)
        unique.append(snippet)
    return unique[:15]


def profile_url(url):
    final_url, page = fetch(url)
    text = clean_text(page)
    links = extract_links(final_url, page)
    images = extract_images(final_url, page)
    date_snippets = extract_date_snippets(page)
    return {
        "url": url,
        "final_url": final_url,
        "ok": True,
        "html_length": len(page),
        "date_count": len(DATE_RE.findall(text)),
        "image_count": len(images),
        "candidate_links": links,
        "candidate_images": images,
        "date_snippets": date_snippets,
        "error": None,
    }


def load_institutions():
    rows = []
    with INPUT_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("tier") == "OUT":
                continue
            url = (row.get("official_url") or "").strip()
            if not url:
                continue
            rows.append(row)
    return rows


def score_profile(profile):
    if not profile["ok"]:
        return -100
    score = 0
    score += min(profile["date_count"], 20) * 3
    score += min(profile["image_count"], 15)
    score += min(len(profile["candidate_links"]), 20)
    return score


def profile_all():
    institutions = load_institutions()
    cache = {}
    results = []
    for index, row in enumerate(institutions, start=1):
        name = row["institution_name"]
        root_url = row["official_url"]
        print(f"[{index}/{len(institutions)}] {name}")
        pages = []
        urls_to_visit = [{"url": root_url, "label": "official_url", "depth": 0}]

        cursor = 0
        while cursor < len(urls_to_visit):
            item = urls_to_visit[cursor]
            cursor += 1
            url = item["url"]
            if url not in cache:
                try:
                    cache[url] = profile_url(url)
                except Exception as exc:
                    cache[url] = {
                        "url": url,
                        "final_url": None,
                        "ok": False,
                        "html_length": 0,
                        "date_count": 0,
                        "image_count": 0,
                        "candidate_links": [],
                        "candidate_images": [],
                        "date_snippets": [],
                        "error": repr(exc),
                    }
                time.sleep(1.0)

            profile = cache[url]
            pages.append({**item, "profile": profile})

            if item["depth"] == 0 and profile["ok"]:
                follow = []
                for link in profile["candidate_links"]:
                    if same_site(profile["final_url"] or url, link["url"]):
                        follow.append(link)
                    if len(follow) >= 5:
                        break
                seen_urls = {entry["url"].split("#", 1)[0] for entry in urls_to_visit}
                for link in follow:
                    key = link["url"].split("#", 1)[0]
                    if key in seen_urls:
                        continue
                    seen_urls.add(key)
                    urls_to_visit.append({"url": link["url"], "label": link["label"], "depth": 1})

        best_page = max(pages, key=lambda page: score_profile(page["profile"])) if pages else None
        results.append({**row, "pages": pages, "best_page": best_page})
    return results


def build_report(results):
    successful = sum(1 for row in results if row["best_page"] and row["best_page"]["profile"]["ok"])
    pages_checked = sum(len(row["pages"]) for row in results)
    lines = [
        "# 확장 후보 사이트 프로파일링 결과",
        "",
        f"- 실행 시각: {datetime.now().isoformat(timespec='seconds')}",
        f"- 기관 후보: {len(results)}개",
        f"- 확인한 페이지: {pages_checked}개",
        f"- 접근 성공 기관: {successful}개",
        "",
        "## 수집 우선순위 후보",
        "",
    ]

    ranked = sorted(
        results,
        key=lambda row: (
            {"A": 0, "B": 1, "C": 2}.get(row["tier"], 9),
            -score_profile(row["best_page"]["profile"]) if row["best_page"] else 999,
            row["region"],
            row["institution_name"],
        ),
    )

    for row in ranked:
        best = row["best_page"]
        profile = best["profile"] if best else None
        ok = profile and profile["ok"]
        lines.append(f"### {row['institution_name']} ({row['region']} {row['city']}, tier {row['tier']})")
        lines.append("")
        lines.append(f"- 공식 URL: {row['official_url']}")
        if not ok:
            err = profile["error"] if profile else "확인 실패"
            lines.append(f"- 상태: 실패 / {err}")
            lines.append("")
            continue
        lines.append(f"- 최적 후보 페이지: {best['url']}")
        lines.append(f"- 날짜 후보: {profile['date_count']}개")
        lines.append(f"- 이미지 후보: {profile['image_count']}개")
        lines.append(f"- 후보 링크: {len(profile['candidate_links'])}개")
        for link in profile["candidate_links"][:5]:
            label = link["label"] or "(라벨 없음)"
            lines.append(f"  - {label}: {link['url']}")
        for snippet in profile["date_snippets"][:3]:
            lines.append(f"  - 날짜 문맥: {snippet}")
        lines.append("")

    by_region = defaultdict(int)
    by_tier = defaultdict(int)
    for row in results:
        by_region[row["region"]] += 1
        by_tier[row["tier"]] += 1
    lines.extend(
        [
            "## 요약",
            "",
            f"- 지역별: {dict(by_region)}",
            f"- 등급별: {dict(by_tier)}",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main():
    results = profile_all()
    JSON_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    build_report(results)
    print(f"json={JSON_PATH}")
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
