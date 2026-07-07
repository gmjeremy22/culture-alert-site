import argparse
import csv
import hashlib
import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import culture_alert_scraper as scraper
from culture_image_utils import clean_image_url, is_bad_image_url


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "culture-alert.sqlite"
CSV_PATH = BASE_DIR / "semi-auto-candidates.csv"
JSON_PATH = BASE_DIR / "semi-auto-candidates.json"
REPORT_PATH = BASE_DIR / "semi-auto-candidate-report.md"

AUTO_MERGE_THRESHOLD = 10
REVIEW_THRESHOLD = 5

NOISE_RE = re.compile(
    r"(login|privacy|copyright|footer|site map|sitemap|404|403|not found|"
    r"채용|입찰|공고|공지사항|보도자료|개인정보|회원가입|로그인|"
    r"오시는 길|관람안내|이용안내|사이트맵|저작권|푸터)",
    re.I,
)
EVENT_HINT_RE = re.compile(
    r"(전시|교육|강연|행사|프로그램|체험|워크숍|exhibition|program|education|workshop|lecture|talk)",
    re.I,
)
AUTO_MERGE_STATUSES = {"auto_merge"}
REVIEWABLE_STATUSES = {"auto_merge", "needs_review", "discard"}
FETCH_TIMEOUT_SECONDS = 6
FETCH_WORKERS = 10


def clean_text(value):
    return scraper.clean_text(str(value or ""))


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def valid_url(value):
    parsed = urlparse(value or "")
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def candidate_id_for(candidate):
    key = "|".join(
        [
            candidate.get("collection_group") or "",
            candidate.get("institution_name") or "",
            candidate.get("title") or "",
            candidate.get("start_date") or "",
            candidate.get("end_date") or "",
            candidate.get("source_url") or "",
        ]
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def ensure_candidate_schema(conn):
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
    columns = {row[1] for row in conn.execute("PRAGMA table_info(event_candidates)")}
    additions = {
        "collection_group": "TEXT",
        "review_status": "TEXT",
        "validation_score": "REAL",
        "validation_reasons": "TEXT",
        "merged_event_id": "INTEGER",
        "merge_note": "TEXT",
        "reviewed_at": "TEXT",
    }
    for column, column_type in additions.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE event_candidates ADD COLUMN {column} {column_type}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_event_candidates_institution ON event_candidates(institution_name)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_event_candidates_dates ON event_candidates(start_date, end_date)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_event_candidates_review ON event_candidates(review_status, validation_score)"
    )
    conn.commit()


def risky_sources():
    sources = []
    for source in scraper.backfill_source_groups():
        group = source.get("backfill_group")
        if group not in scraper.PROMOTED_LOW_GRADE_GROUPS:
            continue
        status = scraper.promoted_low_grade_source_status(source)
        if status in {"hold", "hold-no-events"}:
            item = dict(source)
            item["semi_auto_source_status"] = status
            sources.append(item)
    return sources


def fetch_page(url):
    if not url:
        return "", "", "source URL missing"
    primary = scraper.OFFICIAL_PAGE_FETCH_OVERRIDES.get(url, url)
    targets = [primary]
    if primary != url:
        targets.append(url)
    headers = {
        "User-Agent": "Mozilla/5.0 culture-alert-semi-auto/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    errors = []
    for target in targets:
        for low_security in (False, True):
            try:
                request = Request(target, headers=headers)
                with urlopen(
                    request,
                    timeout=FETCH_TIMEOUT_SECONDS,
                    context=scraper.relaxed_ssl_context(low_security),
                ) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    return response.read().decode(charset, "replace"), response.geturl(), ""
            except Exception as exc:
                errors.append(f"{target}: {exc}")
    return "", primary, " / ".join(errors[-3:])


def fetch_pages(urls):
    unique_urls = [url for url in dict.fromkeys(urls) if url]
    cache = {}
    if not unique_urls:
        return cache
    workers = min(FETCH_WORKERS, len(unique_urls))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(fetch_page, url): url for url in unique_urls}
        for future in as_completed(future_map):
            url = future_map[future]
            try:
                cache[url] = future.result()
            except Exception as exc:
                cache[url] = ("", url, str(exc))
    return cache


def page_match_score(institution_name, title, page_text):
    if not page_text:
        return 0, []
    reasons = []
    score = 0
    text = clean_text(page_text)
    if institution_name and institution_name.replace(" ", "") in text.replace(" ", ""):
        score += 1
        reasons.append("institution_name_seen")
    title_tokens = [
        token
        for token in re.split(r"[\s:：,·ㆍ<>\[\](){}]+", title or "")
        if len(token) >= 3
    ]
    if title and title in text:
        score += 3
        reasons.append("exact_title_seen")
    elif title_tokens:
        matched = sum(1 for token in title_tokens[:5] if token in text)
        if matched >= max(1, min(2, len(title_tokens))):
            score += 2
            reasons.append("title_tokens_seen")
    if EVENT_HINT_RE.search(text):
        score += 1
        reasons.append("event_words_seen")
    return score, reasons


def validate_candidate(candidate, page_text, fetch_error):
    score = 0
    reasons = []
    title = clean_text(candidate.get("title"))
    source_url = candidate.get("source_url")
    start_date = parse_date(candidate.get("start_date"))
    end_date = parse_date(candidate.get("end_date"))
    today = date.today()

    if 4 <= len(title) <= 120:
        score += 2
        reasons.append("title_ok")
    else:
        reasons.append("bad_title_length")
    if "모니터" in title:
        score -= 6
        reasons.append("monitor_placeholder")

    combined = " ".join(
        [
            title,
            clean_text(candidate.get("snippet")),
            source_url or "",
        ]
    )
    if NOISE_RE.search(combined):
        score -= 2
        reasons.append("noise_text")
    else:
        score += 2
        reasons.append("noise_check_ok")

    if EVENT_HINT_RE.search(combined):
        score += 2
        reasons.append("event_words")

    if candidate.get("content_type") in {"전시", "교육", "강연", "행사"}:
        score += 1
        reasons.append("content_type_ok")

    if candidate.get("start_date") and not start_date:
        score -= 3
        reasons.append("bad_start_date")
    if candidate.get("end_date") and not end_date:
        score -= 3
        reasons.append("bad_end_date")
    if start_date and end_date and start_date > end_date:
        score -= 6
        reasons.append("date_order_bad")
    if end_date and end_date < today:
        score -= 8
        reasons.append("ended")
    elif start_date and not end_date and start_date < today and candidate.get("status") not in {"상설전", "상설전시"}:
        score -= 2
        reasons.append("open_past_single_date")
    elif start_date or end_date:
        score += 2
        reasons.append("current_or_future_date")
    elif candidate.get("status") in {"상설전", "상설전시"}:
        score += 1
        reasons.append("permanent_without_dates")
    else:
        reasons.append("date_missing")

    if valid_url(source_url):
        score += 1
        reasons.append("source_url_ok")
    else:
        score -= 5
        reasons.append("source_url_bad")

    if fetch_error:
        score -= 3
        reasons.append("fetch_failed")
    else:
        score += 2
        reasons.append("source_fetch_ok")
        match_score, match_reasons = page_match_score(
            candidate.get("institution_name"),
            title,
            page_text,
        )
        score += match_score
        reasons.extend(match_reasons)

    image_url = clean_image_url(candidate.get("image_url"))
    if image_url and not is_bad_image_url(image_url):
        score += 1
        reasons.append("image_ok")
        candidate["image_url"] = image_url
    elif candidate.get("image_url"):
        candidate["image_url"] = ""
        reasons.append("image_dropped")

    if "ended" in reasons or "date_order_bad" in reasons or "source_url_bad" in reasons:
        status = "discard"
    elif fetch_error:
        status = "needs_review" if score >= REVIEW_THRESHOLD else "discard"
    elif (
        score >= AUTO_MERGE_THRESHOLD
        and "noise_text" not in reasons
        and "monitor_placeholder" not in reasons
        and "open_past_single_date" not in reasons
    ):
        status = "auto_merge"
    elif score >= REVIEW_THRESHOLD:
        status = "needs_review"
    else:
        status = "discard"
    return status, score, reasons


def candidate_from_event(source, event, page_text, final_url, fetch_error):
    metadata = scraper.load_candidate_metadata()
    meta = metadata.get(source.get("name", ""), {})
    source_url = scraper.clean_href(
        event.get("source_url") or source.get("official_url") or meta.get("official_url") or ""
    )
    title = clean_text(event.get("title"))
    snippet = clean_text(page_text)[:800] if page_text else clean_text(fetch_error)[:800]
    candidate = {
        "institution_name": source.get("name"),
        "region": source.get("region") or meta.get("region"),
        "city": source.get("city") or meta.get("city"),
        "category": source.get("category") or meta.get("category"),
        "tier": source.get("tier") or meta.get("tier"),
        "content_type": event.get("content_type") or "전시",
        "title": title,
        "start_date": event.get("start_date"),
        "end_date": event.get("end_date"),
        "image_url": event.get("image_url") or (scraper.image_from_block(final_url, page_text) if page_text else ""),
        "source_url": source_url,
        "page_url": final_url or source_url,
        "confidence": 0,
        "reason": "",
        "snippet": snippet,
        "extracted_at": datetime.now().isoformat(timespec="seconds"),
        "collection_group": "semi-auto-risky",
        "review_status": "",
        "validation_score": 0,
        "validation_reasons": "",
        "merged_event_id": None,
        "merge_note": "",
        "reviewed_at": datetime.now().isoformat(timespec="seconds"),
        "status": event.get("status") or scraper.infer_status(event.get("start_date"), event.get("end_date")),
        "location": event.get("location"),
        "price": event.get("price"),
        "description": clean_text(event.get("description") or "") or snippet[:360],
        "keywords": event.get("keywords"),
        "raw_source_status": source.get("semi_auto_source_status"),
    }
    candidate["candidate_id"] = candidate_id_for(candidate)
    review_status, validation_score, validation_reasons = validate_candidate(
        candidate,
        page_text,
        fetch_error,
    )
    candidate["review_status"] = review_status
    candidate["validation_score"] = validation_score
    candidate["validation_reasons"] = "; ".join(validation_reasons)
    candidate["confidence"] = validation_score
    candidate["reason"] = candidate["validation_reasons"]
    return candidate


def collect_candidates(limit_sources=None):
    targets = risky_sources()
    if limit_sources:
        targets = targets[:limit_sources]
    pending = []
    urls = []
    for source in targets:
        events = source.get("events") or []
        if not events:
            continue
        for event in events:
            metadata = scraper.load_candidate_metadata()
            meta = metadata.get(source.get("name", ""), {})
            source_url = scraper.clean_href(
                event.get("source_url") or source.get("official_url") or meta.get("official_url") or ""
            )
            pending.append((source, event, source_url))
            urls.append(source_url)
    page_cache = fetch_pages(urls)
    candidates = []
    for source, event, source_url in pending:
        page_text, final_url, fetch_error = page_cache.get(
            source_url,
            ("", source_url, "not fetched"),
        )
        candidates.append(candidate_from_event(source, event, page_text, final_url, fetch_error))
    return dedupe_candidates(candidates)


def dedupe_candidates(candidates):
    best = {}
    for candidate in candidates:
        key = (
            candidate["institution_name"],
            candidate["title"],
            candidate.get("start_date") or "",
            candidate.get("source_url") or "",
        )
        previous = best.get(key)
        if previous is None or candidate["validation_score"] > previous["validation_score"]:
            best[key] = candidate
    return sorted(
        best.values(),
        key=lambda item: (
            {"auto_merge": 0, "needs_review": 1, "discard": 2}.get(item["review_status"], 9),
            -float(item["validation_score"] or 0),
            item["institution_name"] or "",
            item["title"] or "",
        ),
    )


def write_candidates(conn, candidates):
    ensure_candidate_schema(conn)
    conn.execute("DELETE FROM event_candidates WHERE collection_group = 'semi-auto-risky'")
    columns = [
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
        "collection_group",
        "review_status",
        "validation_score",
        "validation_reasons",
        "merged_event_id",
        "merge_note",
        "reviewed_at",
    ]
    for candidate in candidates:
        conn.execute(
            f"""
            INSERT OR REPLACE INTO event_candidates ({", ".join(columns)})
            VALUES ({", ".join(":" + column for column in columns)})
            """,
            {column: candidate.get(column) for column in columns},
        )
    conn.commit()


def candidate_to_event(candidate):
    return {
        "institution_name": candidate["institution_name"],
        "content_type": candidate.get("content_type") or "전시",
        "title": candidate["title"],
        "start_date": candidate.get("start_date"),
        "end_date": candidate.get("end_date"),
        "location": candidate.get("location"),
        "region": candidate.get("region"),
        "price": candidate.get("price"),
        "description": candidate.get("description"),
        "keywords": candidate.get("keywords"),
        "image_url": candidate.get("image_url"),
        "source_url": candidate.get("source_url"),
        "status": candidate.get("status") or scraper.infer_status(candidate.get("start_date"), candidate.get("end_date")),
        "raw_text": (
            "semi-auto candidate merge. "
            f"score={candidate.get('validation_score')}; "
            f"reasons={candidate.get('validation_reasons')}; "
            f"snippet={candidate.get('snippet')}"
        ),
    }


def lookup_event_id(conn, event):
    row = conn.execute(
        """
        SELECT e.id
        FROM cultural_events e
        JOIN institutions i ON i.id = e.institution_id
        WHERE i.name = ?
          AND e.title = ?
          AND COALESCE(e.start_date, '') = COALESCE(?, '')
          AND e.source_url = ?
        ORDER BY e.updated_at DESC
        LIMIT 1
        """,
        (
            event["institution_name"],
            event["title"],
            event.get("start_date"),
            event["source_url"],
        ),
    ).fetchone()
    return row[0] if row else None


def cleanup_stale_semi_auto_events(conn, auto_candidates):
    keep_keys = {
        (
            candidate["institution_name"],
            candidate["title"],
            candidate.get("start_date") or "",
            candidate["source_url"],
        )
        for candidate in auto_candidates
    }
    rows = conn.execute(
        """
        SELECT e.id, i.name, e.title, COALESCE(e.start_date, '') AS start_date, e.source_url
        FROM cultural_events e
        JOIN institutions i ON i.id = e.institution_id
        WHERE e.raw_text LIKE 'semi-auto candidate merge.%'
        """
    ).fetchall()
    stale_ids = [
        row[0]
        for row in rows
        if (row[1], row[2], row[3], row[4]) not in keep_keys
    ]
    if not stale_ids:
        return 0
    placeholders = ",".join("?" for _ in stale_ids)
    for table in ("event_occurrences", "event_keywords", "recommendations", "related_links"):
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if exists:
            conn.execute(f"DELETE FROM {table} WHERE event_id IN ({placeholders})", stale_ids)
    cursor = conn.execute(
        f"DELETE FROM cultural_events WHERE id IN ({placeholders})",
        stale_ids,
    )
    return cursor.rowcount


def merge_auto_candidates(conn, candidates):
    auto_candidates = [item for item in candidates if item.get("review_status") == "auto_merge"]
    removed_stale = cleanup_stale_semi_auto_events(conn, auto_candidates)
    if not auto_candidates:
        conn.commit()
        return {"inserted": 0, "updated": 0, "merged": 0, "removed_stale": removed_stale}
    scraper.ensure_schema(conn)
    inserted = 0
    updated = 0
    merged = 0
    for candidate in auto_candidates:
        event = candidate_to_event(candidate)
        try:
            add_count, update_count = scraper.upsert_events(conn, [event])
            event_id = lookup_event_id(conn, event)
            conn.execute(
                """
                UPDATE event_candidates
                SET merged_event_id = ?,
                    merge_note = ?,
                    reviewed_at = CURRENT_TIMESTAMP
                WHERE candidate_id = ?
                """,
                (
                    event_id,
                    f"merged auto candidate: inserted={add_count}, updated={update_count}",
                    candidate["candidate_id"],
                ),
            )
            inserted += add_count
            updated += update_count
            merged += 1
        except Exception as exc:
            conn.execute(
                """
                UPDATE event_candidates
                SET review_status = 'needs_review',
                    merge_note = ?,
                    reviewed_at = CURRENT_TIMESTAMP
                WHERE candidate_id = ?
                """,
                (f"auto merge failed: {exc}", candidate["candidate_id"]),
            )
    conn.commit()
    return {
        "inserted": inserted,
        "updated": updated,
        "merged": merged,
        "removed_stale": removed_stale,
    }


def write_outputs(candidates, merge_result):
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
        "review_status",
        "validation_score",
        "validation_reasons",
        "merge_note",
        "snippet",
        "extracted_at",
    ]
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow({field: candidate.get(field, "") for field in fieldnames})
    JSON_PATH.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    status_counts = Counter(candidate["review_status"] for candidate in candidates)
    lines = [
        "# Semi-auto candidate review report",
        "",
        f"- generated_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- risky_sources: {len(risky_sources())}",
        f"- candidates: {len(candidates)}",
        f"- auto_merge: {status_counts.get('auto_merge', 0)}",
        f"- needs_review: {status_counts.get('needs_review', 0)}",
        f"- discard: {status_counts.get('discard', 0)}",
        f"- merged_candidates: {merge_result.get('merged', 0)}",
        f"- merged_inserted: {merge_result.get('inserted', 0)}",
        f"- merged_updated: {merge_result.get('updated', 0)}",
        f"- removed_stale_semi_auto_events: {merge_result.get('removed_stale', 0)}",
        "",
        "## Candidate Table",
        "",
        "| status | score | institution | title | period | reason | source |",
        "| --- | ---: | --- | --- | --- | --- | --- |",
    ]
    for candidate in candidates:
        period = " ~ ".join(
            value for value in [candidate.get("start_date"), candidate.get("end_date")] if value
        ) or "date needed"
        lines.append(
            "| "
            + " | ".join(
                [
                    candidate.get("review_status") or "",
                    str(candidate.get("validation_score") or 0),
                    clean_text(candidate.get("institution_name")).replace("|", "\\|"),
                    clean_text(candidate.get("title")).replace("|", "\\|"),
                    period.replace("|", "\\|"),
                    clean_text(candidate.get("validation_reasons")).replace("|", "\\|")[:180],
                    clean_text(candidate.get("source_url")).replace("|", "\\|"),
                ]
            )
            + " |"
        )
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_pipeline(db_path=DEFAULT_DB, merge_auto=True, limit_sources=None):
    candidates = collect_candidates(limit_sources=limit_sources)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        write_candidates(conn, candidates)
        merge_result = merge_auto_candidates(conn, candidates) if merge_auto else {
            "inserted": 0,
            "updated": 0,
            "merged": 0,
            "removed_stale": 0,
        }
    write_outputs(candidates, merge_result)
    return candidates, merge_result


def parse_args():
    parser = argparse.ArgumentParser(description="Run semi-auto risky candidate review")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--no-merge", action="store_true")
    parser.add_argument("--limit-sources", type=int)
    return parser.parse_args()


def main():
    args = parse_args()
    candidates, merge_result = run_pipeline(
        db_path=args.db,
        merge_auto=not args.no_merge,
        limit_sources=args.limit_sources,
    )
    counts = Counter(candidate["review_status"] for candidate in candidates)
    print(f"candidates={len(candidates)}")
    print(f"auto_merge={counts.get('auto_merge', 0)}")
    print(f"needs_review={counts.get('needs_review', 0)}")
    print(f"discard={counts.get('discard', 0)}")
    print(f"merged={merge_result.get('merged', 0)}")
    print(f"inserted={merge_result.get('inserted', 0)}")
    print(f"updated={merge_result.get('updated', 0)}")
    print(f"removed_stale={merge_result.get('removed_stale', 0)}")
    print(f"report={REPORT_PATH}")
    print(f"csv={CSV_PATH}")


if __name__ == "__main__":
    main()
