import csv
import html
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent
SEED_PATH = BASE_DIR / "institutions-seed.csv"
JSON_PATH = BASE_DIR / "site-profile-results.json"
REPORT_PATH = BASE_DIR / "site-profile-report.md"

DATE_RE = re.compile(
    r"(?:20\d{2}[./-]\d{1,2}[./-]\d{1,2}|20\d{2}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일)"
)
LINK_HINT_RE = re.compile(
    r"(전시|교육|강연|행사|프로그램|exhibit|exhibition|program|education|event|whatson|plan)",
    re.I,
)


def clean_text(value):
    value = re.sub(r"<script.*?</script>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<style.*?</style>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def fetch(url):
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 culture-alert site profiler; personal-use"
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
        text = clean_text(label)
        absolute = urljoin(base_url, href)
        if LINK_HINT_RE.search(href) or LINK_HINT_RE.search(text):
            links.append({"url": absolute, "label": text[:120]})

    seen = set()
    unique = []
    for item in links:
        key = item["url"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:30]


def extract_images(base_url, page):
    images = []
    for src, alt in re.findall(r'<img[^>]+src="([^"]+)"[^>]*(?:alt="([^"]*)")?', page, flags=re.S | re.I):
        src = html.unescape(src).strip()
        if not src:
            continue
        absolute = urljoin(base_url, src)
        alt_text = clean_text(alt)
        images.append({"url": absolute, "alt": alt_text[:120]})
    return images[:30]


def extract_date_snippets(page):
    text = clean_text(page)
    snippets = []
    for match in DATE_RE.finditer(text):
        start = max(0, match.start() - 80)
        end = min(len(text), match.end() + 120)
        snippets.append(text[start:end])
    seen = set()
    unique = []
    for snippet in snippets:
        if snippet in seen:
            continue
        seen.add(snippet)
        unique.append(snippet)
    return unique[:20]


def profile_url(url):
    final_url, page = fetch(url)
    return {
        "url": url,
        "final_url": final_url,
        "ok": True,
        "html_length": len(page),
        "date_count": len(DATE_RE.findall(clean_text(page))),
        "date_snippets": extract_date_snippets(page),
        "candidate_links": extract_links(final_url, page),
        "candidate_images": extract_images(final_url, page),
        "error": None,
    }


def load_targets():
    targets = []
    with SEED_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            for field in ["exhibition_url", "program_url"]:
                url = (row.get(field) or "").strip()
                if not url:
                    continue
                targets.append(
                    {
                        "institution_name": row["institution_name"],
                        "region": row["region"],
                        "phase": row["collection_phase"],
                        "kind": field.replace("_url", ""),
                        "url": url,
                    }
                )
    seen = set()
    unique = []
    for item in targets:
        key = (item["institution_name"], item["kind"], item["url"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def build_report(results):
    lines = [
        "# 사이트 프로파일링 결과",
        "",
        f"- 실행 시각: {datetime.now().isoformat(timespec='seconds')}",
        f"- 확인 URL: {len(results)}개",
        f"- 성공: {sum(1 for item in results if item['profile']['ok'])}개",
        f"- 실패: {sum(1 for item in results if not item['profile']['ok'])}개",
        "",
        "## 우선 확인할 후보",
        "",
    ]
    ranked = sorted(
        results,
        key=lambda item: (
            not item["profile"]["ok"],
            -item["profile"].get("date_count", 0),
            item["phase"],
            item["institution_name"],
        ),
    )
    for item in ranked:
        profile = item["profile"]
        status = "성공" if profile["ok"] else "실패"
        lines.append(
            f"- {item['institution_name']} / {item['kind']} / {status} / 날짜 후보 {profile.get('date_count', 0)}개"
        )
        lines.append(f"  - URL: {item['url']}")
        if profile["error"]:
            lines.append(f"  - 오류: {profile['error']}")
        for link in profile.get("candidate_links", [])[:5]:
            label = link["label"] or "(라벨 없음)"
            lines.append(f"  - 후보 링크: {label} / {link['url']}")
        for snippet in profile.get("date_snippets", [])[:3]:
            lines.append(f"  - 날짜 문맥: {snippet}")
        lines.append("")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main():
    targets = load_targets()
    results = []
    for index, target in enumerate(targets, start=1):
        print(f"[{index}/{len(targets)}] {target['institution_name']} {target['kind']}")
        try:
            profile = profile_url(target["url"])
        except Exception as exc:
            profile = {
                "url": target["url"],
                "final_url": None,
                "ok": False,
                "html_length": 0,
                "date_count": 0,
                "date_snippets": [],
                "candidate_links": [],
                "candidate_images": [],
                "error": repr(exc),
            }
        results.append({**target, "profile": profile})
        time.sleep(1.0)

    JSON_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    build_report(results)
    print(f"json={JSON_PATH}")
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
