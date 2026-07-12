import argparse
import csv
import difflib
import json
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "culture-alert.sqlite"
DEFAULT_REFERENCE = BASE_DIR / "seoul-institution-reference.csv"
REPORT_PATH = BASE_DIR / "institution-coverage-audit-report.md"
JSON_PATH = BASE_DIR / "institution-coverage-audit-report.json"
ENDED_STATUS = "종료"
MONITOR_MARKER = "전시·교육 모니터"
PERMANENT_MARKER = "상설"
GENERIC_TAGS = {
    "전시",
    "상설",
    "상설전시",
    "기간한정",
    "기간확인",
    "장기",
    "기획전시",
    "특별전시",
}


def normalize_name(value):
    text = str(value or "").casefold()
    text = re.sub(r"\(재\)|재단법인|주식회사|museum|미술관|박물관", "", text)
    return re.sub(r"[^0-9a-z가-힣]+", "", text)


def read_reference(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["priority"] = int(row.get("priority") or 3)
        row["names"] = [row["canonical_name"]]
        row["names"].extend(
            name.strip() for name in (row.get("aliases") or "").split("|") if name.strip()
        )
    return rows


def table_exists(conn, name):
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
    )


def parse_timestamp(value):
    if not value:
        return None
    cleaned = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned).date()
    except ValueError:
        try:
            return datetime.strptime(cleaned[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def institution_rows(conn):
    return conn.execute(
        """
        SELECT id, name, region, city, category, priority, collection_phase,
               exhibition_url, program_url, active
        FROM institutions
        WHERE active = 1
        ORDER BY name
        """
    ).fetchall()


def event_stats(conn, institution_id):
    rows = conn.execute(
        """
        SELECT title, status, event_nature, description, last_checked_at
        FROM cultural_events
        WHERE institution_id = ?
        """,
        (institution_id,),
    ).fetchall()
    monitor_rows = [row for row in rows if MONITOR_MARKER in (row[0] or "")]
    real_rows = [row for row in rows if MONITOR_MARKER not in (row[0] or "")]
    visible = [
        row
        for row in real_rows
        if row[1] != ENDED_STATUS
    ]
    latest = max((row[4] for row in rows if row[4]), default=None)
    permanent = [
        row
        for row in visible
        if row[2] == "permanent"
        or PERMANENT_MARKER in (row[1] or "")
        or PERMANENT_MARKER in (row[0] or "")
    ]
    return {
        "all_events": len(rows),
        "real_events": len(real_rows),
        "monitor_events": len(monitor_rows),
        "current_cards": len(visible),
        "permanent_cards": len(permanent),
        "latest_checked_at": latest,
    }


def closest_matches(reference, institutions, limit=3):
    target_names = [normalize_name(name) for name in reference["names"]]
    scored = []
    for row in institutions:
        normalized = normalize_name(row[1])
        score = max(
            (difflib.SequenceMatcher(None, target, normalized).ratio() for target in target_names),
            default=0,
        )
        if score >= 0.62:
            scored.append((score, row[1]))
    return [name for _score, name in sorted(scored, reverse=True)[:limit]]


def match_reference(reference, institutions):
    normalized_lookup = {}
    for row in institutions:
        normalized_lookup.setdefault(normalize_name(row[1]), []).append(row)
    for name in reference["names"]:
        matches = normalized_lookup.get(normalize_name(name), [])
        if matches:
            return matches[0]
    return None


def coverage_reason(stats, exhibition_url, program_url):
    reasons = []
    if stats["all_events"] == 0:
        reasons.append("수집된 일정 없음")
    elif stats["real_events"] == 0 and stats["monitor_events"]:
        reasons.append("공식 페이지 감시만 있고 실제 일정 미수집")
    elif stats["current_cards"] == 0:
        reasons.append("수집된 실제 일정이 모두 종료")
    if not (exhibition_url or program_url):
        reasons.append("수집 URL 없음")
    checked = parse_timestamp(stats["latest_checked_at"])
    if checked and (date.today() - checked).days > 14:
        reasons.append(f"마지막 확인 {(date.today() - checked).days}일 전")
    return reasons


def permanent_concept_summary(conn):
    events = conn.execute(
        """
        SELECT id, title, description
        FROM cultural_events
        WHERE event_nature='permanent'
           OR status IN ('상설전', '상설전시')
           OR title LIKE '%상설%'
        """
    ).fetchall()
    keyword_map = {}
    if table_exists(conn, "event_keywords"):
        for event_id, keyword in conn.execute(
            "SELECT event_id, keyword FROM event_keywords"
        ).fetchall():
            keyword_map.setdefault(event_id, set()).add(keyword)
    strong = 0
    partial = 0
    weak = []
    for event_id, title, description in events:
        topical = {
            tag for tag in keyword_map.get(event_id, set()) if tag not in GENERIC_TAGS
        }
        has_description = bool((description or "").strip())
        if has_description and topical:
            strong += 1
        elif has_description or topical:
            partial += 1
        else:
            weak.append({"event_id": event_id, "title": title})
    return {
        "total": len(events),
        "with_description": sum(bool((row[2] or "").strip()) for row in events),
        "strong_concept": strong,
        "partial_concept": partial,
        "weak_concept": len(weak),
        "weak_examples": weak[:20],
    }


def audit(db_path, reference_path):
    reference_rows = read_reference(reference_path)
    with sqlite3.connect(db_path) as conn:
        institutions = institution_rows(conn)
        results = []
        for reference in reference_rows:
            matched = match_reference(reference, institutions)
            if not matched:
                results.append(
                    {
                        "canonical_name": reference["canonical_name"],
                        "kind": reference.get("kind") or "",
                        "priority": reference["priority"],
                        "status": "missing",
                        "matched_name": "",
                        "all_events": 0,
                        "current_cards": 0,
                        "permanent_cards": 0,
                        "reasons": ["기관 DB에 없음"],
                        "similar_names": closest_matches(reference, institutions),
                        "source_url": reference.get("source_url") or "",
                    }
                )
                continue
            (
                institution_id,
                matched_name,
                _region,
                _city,
                _category,
                _priority,
                _collection_phase,
                exhibition_url,
                program_url,
                _active,
            ) = matched
            stats = event_stats(conn, institution_id)
            reasons = coverage_reason(stats, exhibition_url, program_url)
            results.append(
                {
                    "canonical_name": reference["canonical_name"],
                    "kind": reference.get("kind") or "",
                    "priority": reference["priority"],
                    "status": "covered" if stats["current_cards"] else "zero_current",
                    "matched_name": matched_name,
                    **stats,
                    "reasons": reasons,
                    "similar_names": [],
                    "source_url": reference.get("source_url") or "",
                }
            )
        concepts = permanent_concept_summary(conn)
        all_seoul_zero_current = []
        for institution in institutions:
            (
                institution_id,
                institution_name,
                region,
                _city,
                category,
                priority,
                collection_phase,
                exhibition_url,
                program_url,
                _active,
            ) = institution
            if region != "서울":
                continue
            stats = event_stats(conn, institution_id)
            if stats["current_cards"]:
                continue
            all_seoul_zero_current.append(
                {
                    "institution_name": institution_name,
                    "category": category,
                    "priority": priority,
                    "collection_phase": collection_phase,
                    **stats,
                    "reasons": coverage_reason(stats, exhibition_url, program_url),
                }
            )
        seoul_total = conn.execute(
            "SELECT COUNT(*) FROM institutions WHERE active=1 AND region='서울'"
        ).fetchone()[0]
        seoul_with_current = conn.execute(
            """
            SELECT COUNT(DISTINCT i.id)
            FROM institutions i
            JOIN cultural_events e ON e.institution_id=i.id
            WHERE i.active=1 AND i.region='서울'
              AND e.status != ?
              AND e.title NOT LIKE ?
            """,
            (ENDED_STATUS, f"%{MONITOR_MARKER}%"),
        ).fetchone()[0]

    summary = {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "reference_count": len(results),
        "missing_count": sum(item["status"] == "missing" for item in results),
        "zero_current_count": sum(item["status"] == "zero_current" for item in results),
        "covered_count": sum(item["status"] == "covered" for item in results),
        "priority_one_missing": sum(
            item["status"] == "missing" and item["priority"] == 1 for item in results
        ),
        "priority_one_zero_current": sum(
            item["status"] == "zero_current" and item["priority"] == 1
            for item in results
        ),
        "seoul_institutions": seoul_total,
        "seoul_with_current_cards": seoul_with_current,
        "seoul_zero_current_cards": len(all_seoul_zero_current),
        "seoul_without_any_events": sum(
            item["all_events"] == 0 for item in all_seoul_zero_current
        ),
        "seoul_monitor_only": sum(
            item["real_events"] == 0 and item["monitor_events"] > 0
            for item in all_seoul_zero_current
        ),
        "seoul_with_only_old_events": sum(
            item["real_events"] > 0 for item in all_seoul_zero_current
        ),
    }
    return {
        "summary": summary,
        "institutions": results,
        "all_seoul_zero_current": all_seoul_zero_current,
        "permanent_concepts": concepts,
    }


def markdown_report(payload):
    summary = payload["summary"]
    concepts = payload["permanent_concepts"]
    lines = [
        "# 기관 누락 및 수집 커버리지 점검",
        "",
        f"- 점검 시각: {summary['checked_at']}",
        f"- 서울 등록 기관: {summary['seoul_institutions']}곳",
        f"- 현재 카드가 있는 서울 기관: {summary['seoul_with_current_cards']}곳",
        f"- 현재 카드가 0건인 서울 기관: {summary['seoul_zero_current_cards']}곳",
        f"  - 일정이 한 번도 수집되지 않음: {summary['seoul_without_any_events']}곳",
        f"  - 감시용 행만 있고 실제 일정 미수집: {summary['seoul_monitor_only']}곳",
        f"  - 수집된 실제 일정이 모두 종료: {summary['seoul_with_only_old_events']}곳",
        f"- 우선 점검 기준표: {summary['reference_count']}곳",
        f"- 완전 누락: {summary['missing_count']}곳",
        f"- 등록됐지만 현재 카드 0건: {summary['zero_current_count']}곳",
        f"- 현재 카드 확인: {summary['covered_count']}곳",
        "",
        "## 완전 누락 기관",
        "",
        "| 우선 | 기관 | 구분 | 유사 이름 |",
        "| --- | --- | --- | --- |",
    ]
    missing = [item for item in payload["institutions"] if item["status"] == "missing"]
    for item in sorted(missing, key=lambda value: (value["priority"], value["canonical_name"])):
        similar = ", ".join(item["similar_names"]) or "-"
        lines.append(
            f"| {item['priority']} | {item['canonical_name']} | {item['kind']} | {similar} |"
        )
    if not missing:
        lines.append("| - | 없음 | - | - |")

    lines.extend(
        [
            "",
            "## 등록됐지만 현재 카드 0건",
            "",
            "| 우선 | 기관 | 전체 일정 | 마지막 확인 | 원인 후보 |",
            "| --- | --- | ---: | --- | --- |",
        ]
    )
    zero_current = [
        item for item in payload["institutions"] if item["status"] == "zero_current"
    ]
    for item in sorted(
        zero_current, key=lambda value: (value["priority"], value["canonical_name"])
    ):
        reason = "; ".join(item["reasons"]) or "확인 필요"
        lines.append(
            f"| {item['priority']} | {item['matched_name']} | {item['all_events']} | "
            f"{item['latest_checked_at'] or '-'} | {reason} |"
        )
    if not zero_current:
        lines.append("| - | 없음 | 0 | - | - |")

    lines.extend(
        [
            "",
            "## 서울 기관 전체 카드 0건",
            "",
            "| 기관 | 구분 | 수집 단계 | 전체 일정 | 원인 후보 |",
            "| --- | --- | --- | ---: | --- |",
        ]
    )
    for item in sorted(
        payload["all_seoul_zero_current"],
        key=lambda value: (value["priority"], value["institution_name"]),
    ):
        reason = "; ".join(item["reasons"]) or "확인 필요"
        lines.append(
            f"| {item['institution_name']} | {item['category']} | "
            f"{item['collection_phase']} | {item['all_events']} | {reason} |"
        )

    lines.extend(
        [
            "",
            "## 상설전 주제 정보 품질",
            "",
            f"- 상설전 판정 카드: {concepts['total']}건",
            f"- 설명이 수집된 카드: {concepts['with_description']}건",
            f"- 설명과 주제 태그가 모두 있는 카드: {concepts['strong_concept']}건",
            f"- 설명 또는 주제 태그 중 하나만 있는 카드: {concepts['partial_concept']}건",
            f"- 이름 외 주제 정보가 거의 없는 카드: {concepts['weak_concept']}건",
            "",
            "### 주제 정보가 약한 상설전 예시",
            "",
        ]
    )
    if concepts["weak_examples"]:
        lines.extend(
            f"- {item['event_id']} | {item['title']}" for item in concepts["weak_examples"]
        )
    else:
        lines.append("- 없음")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Audit institution and permanent-exhibition coverage")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--json", type=Path, default=JSON_PATH)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when a priority-1 institution is missing or has no current cards",
    )
    args = parser.parse_args()
    payload = audit(args.db, args.reference)
    args.report.write_text(markdown_report(payload), encoding="utf-8")
    args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = payload["summary"]
    print(
        "institution_coverage "
        f"reference={summary['reference_count']} "
        f"missing={summary['missing_count']} "
        f"zero_current={summary['zero_current_count']} "
        f"covered={summary['covered_count']}"
    )
    print(
        "permanent_concepts "
        f"total={payload['permanent_concepts']['total']} "
        f"strong={payload['permanent_concepts']['strong_concept']} "
        f"weak={payload['permanent_concepts']['weak_concept']}"
    )
    print(f"report={args.report}")
    if args.strict and (
        summary["priority_one_missing"] or summary["priority_one_zero_current"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
