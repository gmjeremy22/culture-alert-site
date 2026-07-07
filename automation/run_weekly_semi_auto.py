import argparse
import os
import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from init_culture_db import DB_PATH, OUTPUTS_DIR, initialize_database
from run_daily_update import (
    BUILD_SCRIPT,
    PUBLIC_INDEX,
    RECOMMENDATION_HTML,
    REPO_ROOT,
    VERIFY_SCRIPT,
    node_command,
    require_password,
    run,
    run_collection_and_render,
)


CARD_HTML = OUTPUTS_DIR / "culture-card-gallery.html"
SEMI_AUTO_REPORT = OUTPUTS_DIR / "semi-auto-candidate-report.md"
SEMI_AUTO_CSV = OUTPUTS_DIR / "semi-auto-candidates.csv"
SEMI_AUTO_JSON = OUTPUTS_DIR / "semi-auto-candidates.json"
WEEKLY_REPORT = OUTPUTS_DIR / "weekly-semi-auto-update-report.md"


def add_outputs_to_path():
    outputs = str(OUTPUTS_DIR)
    if outputs not in sys.path:
        sys.path.insert(0, outputs)


def rerender_cards():
    add_outputs_to_path()
    import culture_card_gallery
    import culture_keyword_tagger
    from refresh_event_statuses import refresh_statuses

    status_updated, status_counts = refresh_statuses(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        summary = culture_keyword_tagger.tag_events(conn)
        scored = culture_keyword_tagger.score_recommendations(
            conn, culture_keyword_tagger.DEFAULT_PERSON
        )
        culture_keyword_tagger.write_report(
            summary,
            scored,
            culture_keyword_tagger.DEFAULT_PERSON,
        )
    total_cards, card_counts = culture_card_gallery.render()
    shutil.copyfile(CARD_HTML, RECOMMENDATION_HTML)
    return {
        "status_updated": status_updated,
        "status_counts": status_counts,
        "total_cards": total_cards,
        "card_counts": card_counts,
        "positive_recommendations": len([item for item in scored if item[0] > 0]),
    }


def run_semi_auto(merge_auto=True, limit_sources=None):
    add_outputs_to_path()
    import semi_auto_candidate_pipeline

    return semi_auto_candidate_pipeline.run_pipeline(
        db_path=DB_PATH,
        merge_auto=merge_auto,
        limit_sources=limit_sources,
    )


def run_audits():
    run([sys.executable, "culture_data_audit.py"], cwd=OUTPUTS_DIR)
    run([sys.executable, "culture_ui_audit.py"], cwd=OUTPUTS_DIR)
    if os.environ.get("RUN_IMAGE_AUDIT") == "1":
        run([sys.executable, "culture_image_audit.py"], cwd=OUTPUTS_DIR)


def build_protected_site(output_path):
    require_password()
    run(
        [
            node_command(),
            str(BUILD_SCRIPT),
            "--input",
            str(RECOMMENDATION_HTML),
            "--output",
            str(output_path),
        ],
        cwd=REPO_ROOT,
    )
    run(
        [
            node_command(),
            str(VERIFY_SCRIPT),
            "--html",
            str(output_path),
            "--leak",
            "feature-card",
        ],
        cwd=REPO_ROOT,
    )


def write_weekly_report(candidates, merge_result, render_result, args):
    status_counts = Counter(candidate["review_status"] for candidate in candidates)
    lines = [
        "# 주간 반자동 후보 점검 리포트",
        "",
        f"- 후보 수: {len(candidates)}건",
        f"- 자동 병합: {status_counts.get('auto_merge', 0)}건",
        f"- 검토 필요: {status_counts.get('needs_review', 0)}건",
        f"- 폐기: {status_counts.get('discard', 0)}건",
        f"- 병합 실행: {'예' if not args.no_merge else '아니오'}",
        f"- 병합 후보: {merge_result.get('merged', 0)}건",
        f"- 신규 병합: {merge_result.get('inserted', 0)}건",
        f"- 기존 갱신: {merge_result.get('updated', 0)}건",
        f"- 이전 반자동 카드 제거: {merge_result.get('removed_stale', 0)}건",
        f"- 최종 카드: {render_result['total_cards']}건",
        f"- 추천 반영: {render_result['positive_recommendations']}건",
        f"- 보호 HTML 생성: {'아니오' if args.skip_site_build else '예'}",
        "",
        "## 카드 유형",
        "",
    ]
    for content_type, count in render_result["card_counts"].items():
        lines.append(f"- {content_type}: {count}건")

    lines.extend(["", "## 상태별 일정 수", ""])
    for status, count in sorted(render_result["status_counts"].items()):
        lines.append(f"- {status}: {count}건")

    lines.extend(
        [
            "",
            "## 생성 파일",
            "",
            f"- 후보 상세: `{SEMI_AUTO_REPORT.name}`",
            f"- 후보 CSV: `{SEMI_AUTO_CSV.name}`",
            f"- 후보 JSON: `{SEMI_AUTO_JSON.name}`",
            f"- 카드 HTML: `{RECOMMENDATION_HTML.name}`",
        ]
    )
    WEEKLY_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(description="Run weekly semi-auto candidate review")
    parser.add_argument("--output", type=Path, default=PUBLIC_INDEX)
    parser.add_argument(
        "--skip-baseline",
        action="store_true",
        help="Use the existing database instead of rebuilding the stable daily baseline.",
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Store and report candidates without merging auto-approved rows.",
    )
    parser.add_argument("--limit-sources", type=int)
    parser.add_argument(
        "--skip-site-build",
        action="store_true",
        help="Skip password-protected HTML build and verification.",
    )
    parser.add_argument(
        "--skip-audits",
        action="store_true",
        help="Skip data/UI audits. Intended only for quick local smoke tests.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    output_path = args.output.resolve()

    if not args.skip_baseline:
        initialize_database(reset=True)
        run_collection_and_render()
    elif not DB_PATH.exists():
        raise FileNotFoundError(f"database not found: {DB_PATH}")

    candidates, merge_result = run_semi_auto(
        merge_auto=not args.no_merge,
        limit_sources=args.limit_sources,
    )
    render_result = rerender_cards()
    if not args.skip_audits:
        run_audits()
    if not args.skip_site_build:
        build_protected_site(output_path)
    write_weekly_report(candidates, merge_result, render_result, args)

    counts = Counter(candidate["review_status"] for candidate in candidates)
    print(f"db={DB_PATH}")
    print(f"candidates={len(candidates)}")
    print(f"auto_merge={counts.get('auto_merge', 0)}")
    print(f"needs_review={counts.get('needs_review', 0)}")
    print(f"discard={counts.get('discard', 0)}")
    print(f"merged={merge_result.get('merged', 0)}")
    print(f"removed_stale={merge_result.get('removed_stale', 0)}")
    print(f"cards={render_result['total_cards']}")
    print(f"report={WEEKLY_REPORT}")
    if not args.skip_site_build:
        print(f"encrypted_html={output_path}")


if __name__ == "__main__":
    main()
