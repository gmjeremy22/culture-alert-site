import csv
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
RAW_PATH = BASE_DIR / "raw-event-candidates.csv"
SHORTLIST_CSV = BASE_DIR / "curated-candidate-shortlist.csv"
REPORT_PATH = BASE_DIR / "curated-candidate-shortlist.md"


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def is_current_or_future(row):
    today = date.today()
    end_date = parse_date(row.get("end_date"))
    start_date = parse_date(row.get("start_date"))
    if end_date:
        return end_date >= today
    if start_date:
        return start_date >= today
    return False


def is_likely_noise(row):
    title = row.get("title", "")
    snippet = row.get("snippet", "")
    source_url = row.get("source_url", "")
    noisy_words = [
        "채용",
        "입찰",
        "공고",
        "공지",
        "보도자료",
        "개인정보",
        "회원가입",
        "로그인",
        "저작권",
        "오시는 길",
    ]
    combined = f"{title} {snippet} {source_url}"
    if any(word in combined for word in noisy_words):
        return True
    if len(title.strip()) < 4:
        return True
    return False


def quality_bucket(row):
    confidence = float(row.get("confidence") or 0)
    has_period = bool(row.get("start_date") and row.get("end_date"))
    has_image = bool(row.get("image_url"))
    content_type = row.get("content_type")
    tier = row.get("tier")
    score = confidence
    if has_period:
        score += 2
    if has_image:
        score += 1
    if content_type == "전시":
        score += 1
    if tier == "A":
        score += 1
    if score >= 12:
        return "A"
    if score >= 10:
        return "B"
    return "C"


def dedupe(rows):
    best = {}
    for row in rows:
        key = (
            row["institution_name"].strip(),
            row["title"].strip(),
            row.get("start_date") or "",
            row.get("end_date") or "",
        )
        previous = best.get(key)
        if not previous:
            best[key] = row
            continue
        previous_score = float(previous.get("confidence") or 0)
        score = float(row.get("confidence") or 0)
        if score > previous_score:
            best[key] = row
    return list(best.values())


def main():
    raw_rows = list(csv.DictReader(RAW_PATH.open("r", encoding="utf-8-sig")))
    filtered = []
    for row in raw_rows:
        if not is_current_or_future(row):
            continue
        if is_likely_noise(row):
            continue
        if float(row.get("confidence") or 0) < 7:
            continue
        row["review_bucket"] = quality_bucket(row)
        filtered.append(row)

    filtered = dedupe(filtered)
    filtered.sort(
        key=lambda row: (
            row["review_bucket"],
            {"A": 0, "B": 1, "C": 2}.get(row.get("tier"), 9),
            {"전시": 0, "강연": 1, "교육": 2, "행사": 3}.get(row.get("content_type"), 9),
            row.get("end_date") or "9999-12-31",
            row.get("institution_name"),
            row.get("title"),
        )
    )

    fieldnames = list(filtered[0].keys()) if filtered else list(raw_rows[0].keys()) + ["review_bucket"]
    with SHORTLIST_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(filtered)

    by_type = Counter(row["content_type"] for row in filtered)
    by_bucket = Counter(row["review_bucket"] for row in filtered)
    by_institution = Counter(row["institution_name"] for row in filtered)
    grouped = defaultdict(list)
    for row in filtered:
        grouped[row["review_bucket"]].append(row)

    lines = [
        "# 정리된 후보 쇼트리스트",
        "",
        f"- 원시 후보: {len(raw_rows)}건",
        f"- 현재/미래 + 노이즈 제거 후: {len(filtered)}건",
        f"- 유형별: {dict(by_type)}",
        f"- 검토 등급별: {dict(by_bucket)}",
        "",
        "## 기관별 후보가 많은 곳",
        "",
    ]
    for institution, count in by_institution.most_common(20):
        lines.append(f"- {institution}: {count}건")

    for bucket in ["A", "B", "C"]:
        rows = grouped[bucket]
        lines.extend(["", f"## {bucket}급 후보", ""])
        for row in rows[:80]:
            period = " ~ ".join(
                value for value in [row.get("start_date"), row.get("end_date")] if value
            ) or "기간 확인 필요"
            lines.append(
                f"- {row['title']} / {row['institution_name']} / {row['content_type']} / {period}"
            )
            lines.append(f"  - 링크: {row.get('source_url')}")
            if row.get("image_url"):
                lines.append(f"  - 이미지: {row.get('image_url')}")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"raw={len(raw_rows)} shortlist={len(filtered)}")
    print(f"csv={SHORTLIST_CSV}")
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
