import argparse
import json
import re
from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_HTML = BASE_DIR / "keyword-recommendation-report.html"
REPORT_PATH = BASE_DIR / "ui-quality-audit-report.md"


MOJIBAKE_MARKERS = (
    "\ufffd",
    "?섎",
    "?꾩",
    "?곗",
    "?대",
    "移대",
    "臾명",
    "誘몄",
    "愿",
    "湲곌",
    "嫄",
    "援먯",
    "由ы",
    "吏",
    "異",
    "꾨줈",
)

PAGE_NOISE_MARKERS = (
    "$(function",
    "$.ajax",
    "ManpaJs",
    'alert("code:',
    "document).delegate",
    "개인정보처리방침",
    "담당자 정보",
    "소속박물관 바로가기",
    "© National Museum of Korea",
    "현재전시.",
    "공식 페이지 모니터 수집.",
)

STALE_REASON_MARKERS = (
    "detailReason",
    "fields.reason",
    '"reason"',
    "추천 이유",
)

REQUIRED_IDS = {
    "featuredView": "추천 보기 영역",
    "allView": "기간 일정 영역",
    "permanentView": "상설전 영역",
    "curationHero": "대표 추천 영역",
    "heroSlot": "대표 추천 카드",
    "todayStack": "오늘의 추천 묶음",
    "endingStack": "곧 종료 묶음",
    "venueBundleList": "한 장소 묶음",
    "quickFilterRail": "빠른 필터",
    "advancedFilter": "상세 필터",
    "advancedFilterLabel": "상세 필터 상태",
    "detailOverlay": "세부창",
    "detailClose": "세부창 닫기",
    "detailTitle": "세부창 제목",
    "detailSource": "원문 링크",
    "detailWhy": "추천 판단 설명",
    "resetRecommendation": "추천 조건 초기화",
    "recommendationSummary": "추천 조건 요약",
}

REQUIRED_VIEWS = {"featured", "all", "permanent"}

EDITORIAL_BADGE_LABELS = {
    "취향 적합",
    "곧 종료",
    "가족 동선 좋음",
    "같이 보기 좋음",
    "주요 기관",
    "이번 주 추천",
    "상설로 여유롭게",
    "서울권 접근성 좋음",
    "기간한정",
}

EDITORIAL_BADGE_TONES = {"deadline", "gold", "calm"}

SCRIPT_FLOW_MARKERS = {
    "카드 클릭으로 세부창 열기": 'document.querySelectorAll("[data-index]")',
    "보기 전환 버튼": 'document.querySelectorAll("[data-view]")',
    "관심 키워드 선택": 'document.querySelectorAll("[data-keyword-choice]")',
    "지역 선택": 'document.querySelectorAll("[data-region-choice]")',
    "일정 유형 선택": 'document.querySelectorAll("[data-type-choice]")',
    "우선순위 선택": 'document.querySelectorAll("[data-priority-choice]")',
    "빠른 필터 선택": "function applyQuickFilter",
    "첫 화면 큐레이션 렌더링": "function renderCuration",
    "상세 필터 상태 표시": "advancedFilterLabel.textContent",
    "추천 초기화": "resetRecommendation.addEventListener",
    "기간 일정 필터": 'document.querySelectorAll("[data-filter]")',
    "닫기 버튼": "closeButton.addEventListener",
    "바깥 클릭 닫기": "overlay.addEventListener",
    "Esc 닫기": 'event.key === "Escape"',
    "세부 회차 표시": "function fillSchedule",
    "추천 판단 설명 표시": "function fillWhy",
    "같은 장소 다른 일정 표시": "function fillCompanions",
    "후기/검색 링크 표시": "function fillRelated",
}

TEXT_FIELDS = (
    "institution",
    "venueLabel",
    "displayVenue",
    "type",
    "natureLabel",
    "title",
    "displayTitle",
    "period",
    "location",
    "detailLocation",
    "region",
    "price",
    "status",
    "keywords",
    "description",
)


class CardHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.views = []
        self.filters = []
        self.data_indexes = []
        self.feature_indexes = []
        self.feature_cards = 0
        self.list_cards = 0
        self.visible_text_parts = []
        self.skip_stack = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = dict(attrs)
        if tag in {"script", "style"}:
            self.skip_stack.append(tag)
            return

        element_id = attrs.get("id")
        if element_id:
            self.ids.add(element_id)
        if "data-view" in attrs:
            self.views.append(attrs["data-view"])
        if "data-filter" in attrs:
            self.filters.append(attrs["data-filter"])
        if "data-index" in attrs:
            self.data_indexes.append(attrs["data-index"])
        classes = set((attrs.get("class") or "").split())
        if {"card", "feature-card"} <= classes:
            self.feature_cards += 1
            if "data-feature-index" in attrs:
                self.feature_indexes.append(attrs["data-feature-index"])
        if {"card", "list-card"} <= classes:
            self.list_cards += 1

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.skip_stack and self.skip_stack[-1] == tag:
            self.skip_stack.pop()

    def handle_data(self, data):
        if self.skip_stack:
            return
        text = " ".join((data or "").split())
        if text:
            self.visible_text_parts.append(text)

    @property
    def visible_text(self):
        return " ".join(self.visible_text_parts)


def parse_args():
    parser = argparse.ArgumentParser(description="최종 카드 HTML 사용자 UI 품질 점검")
    parser.add_argument("--html", type=Path, default=DEFAULT_HTML, help="점검할 HTML 파일")
    parser.add_argument("--report", type=Path, default=REPORT_PATH, help="저장할 리포트 파일")
    return parser.parse_args()


def shorten(value, limit=180):
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def context_sample(text, marker, radius=70):
    index = text.find(marker)
    if index < 0:
        return shorten(text)
    start = max(0, index - radius)
    end = min(len(text), index + len(marker) + radius)
    return shorten(text[start:end], radius * 2 + len(marker) + 3)


def valid_url(value):
    parsed = urlparse(str(value or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def extract_items(html_text):
    marker = "const items = "
    start = html_text.find(marker)
    if start < 0:
        raise ValueError("HTML 안에서 카드 데이터(const items)를 찾지 못했습니다.")
    start += len(marker)
    end_marker = ";\n    const overlay"
    end = html_text.find(end_marker, start)
    if end < 0:
        match = re.search(r"const items = (\[.*?\]);\s+const overlay", html_text, re.DOTALL)
        if not match:
            raise ValueError("카드 데이터의 끝을 찾지 못했습니다.")
        payload = match.group(1)
    else:
        payload = html_text[start:end]
    return json.loads(payload)


def add_finding(findings, priority, title, detail, evidence=""):
    findings.append(
        {
            "priority": priority,
            "title": title,
            "detail": detail,
            "evidence": shorten(evidence, 260),
        }
    )


def scan_text_for_markers(findings, label, text, priority="P1"):
    if not text:
        return
    for marker in MOJIBAKE_MARKERS:
        if marker in text:
            add_finding(
                findings,
                priority,
                "깨진 글자 의심",
                f"{label}에 인코딩이 깨진 듯한 조각이 있습니다.",
                context_sample(text, marker),
            )
            break
    for marker in PAGE_NOISE_MARKERS:
        if marker in text:
            add_finding(
                findings,
                "P1",
                "페이지 코드/푸터 문구 노출",
                f"{label}에 사용자에게 보이면 안 되는 원문 페이지 잡음이 섞였습니다.",
                context_sample(text, marker),
            )
            break


def iter_item_texts(item):
    item_id = item.get("id", "?")
    title = shorten(item.get("displayTitle") or item.get("title") or "제목 없음", 80)
    for field in TEXT_FIELDS:
        value = item.get(field)
        if value:
            yield f"event {item_id} {title} / {field}", str(value)
    for keyword in item.get("keywordList") or []:
        yield f"event {item_id} {title} / keyword", str(keyword)
    for keyword in item.get("keywordMeta") or []:
        yield f"event {item_id} {title} / keywordMeta", str(keyword.get("label", ""))
    for badge in item.get("curationBadges") or []:
        yield f"event {item_id} {title} / curationBadge", str(badge.get("label", ""))
    for occurrence in item.get("occurrences") or []:
        for field in ("dateText", "time", "label", "note"):
            value = occurrence.get(field)
            if value:
                yield f"event {item_id} {title} / occurrence.{field}", str(value)
    for companion in item.get("companionEvents") or []:
        for field in ("title", "displayTitle", "displayVenue", "period", "location", "status"):
            value = companion.get(field)
            if value:
                yield f"event {item_id} {title} / companion.{field}", str(value)
    for link in item.get("relatedLinks") or []:
        if link.get("title"):
            yield f"event {item_id} {title} / related.title", str(link["title"])


def check_html_structure(findings, parser, html_text, items):
    for element_id, label in REQUIRED_IDS.items():
        if element_id not in parser.ids:
            add_finding(
                findings,
                "P1",
                "필수 UI 요소 누락",
                f"{label} 요소(id={element_id})가 HTML에 없습니다.",
            )

    missing_views = REQUIRED_VIEWS - set(parser.views)
    if missing_views:
        add_finding(
            findings,
            "P1",
            "보기 전환 버튼 누락",
            "추천 보기/기간 일정/상설전 전환 중 일부가 없습니다.",
            ", ".join(sorted(missing_views)),
        )

    for label, marker in SCRIPT_FLOW_MARKERS.items():
        if marker not in html_text:
            add_finding(
                findings,
                "P1",
                "상호작용 연결 누락",
                f"{label} 흐름을 연결하는 스크립트 조각을 찾지 못했습니다.",
                marker,
            )

    for marker in STALE_REASON_MARKERS:
        if marker in html_text:
            add_finding(
                findings,
                "P1",
                "제거하기로 한 이유 항목 잔존",
                "세부창이나 카드 데이터에 이전 '이유' 항목 흔적이 남아 있습니다.",
                context_sample(html_text, marker),
            )
            break

    scan_text_for_markers(findings, "화면에 보이는 HTML 텍스트", parser.visible_text)

    if "editorial-badge" not in html_text:
        add_finding(
            findings,
            "P2",
            "추천 배지 UI 누락",
            "추천 카드에서 클릭할 이유를 빠르게 보여주는 editorial badge가 렌더링되지 않았습니다.",
        )
    for marker, label in [
        ("오늘의 대표 추천", "대표 추천 헤딩"),
        ("오늘의 추천", "오늘 추천 스택"),
        ("곧 끝나요", "마감 임박 스택"),
        ("한 장소에서 묶어보기", "장소 묶음 섹션"),
        ("추천 전체", "추천 전체 그리드"),
        ("왜 추천하나요", "세부창 추천 판단 설명"),
    ]:
        if marker not in parser.visible_text and marker not in html_text:
            add_finding(
                findings,
                "P2",
                "큐레이션 홈 문구 누락",
                f"{label} 문구가 없어 첫 화면이 추천 리포트처럼 읽히기 어렵습니다.",
                marker,
            )
    advanced_match = re.search(r"<details[^>]*id=\"advancedFilter\"[^>]*>", html_text)
    if advanced_match and " open" in advanced_match.group(0):
        add_finding(
            findings,
            "P2",
            "상세 필터 기본 펼침",
            "첫 화면에서는 상세 필터가 접힌 상태로 시작해야 합니다.",
            advanced_match.group(0),
        )
    for marker in ("raw score", "추천 점수", "score:"):
        if marker in parser.visible_text:
            add_finding(
                findings,
                "P2",
                "점수형 추천 정보 노출",
                "추천 이유가 사용자 언어가 아니라 원시 점수처럼 보입니다.",
                marker,
            )
    if "같은 장소에서 함께 볼 것" not in html_text or "companion-action" not in html_text:
        add_finding(
            findings,
            "P2",
            "같은 장소 큐레이션 UI 누락",
            "세부창의 같은 장소 일정이 방문 동선 큐레이션 섹션으로 표시되지 않습니다.",
        )

    total = len(items)
    timed = [item for item in items if not item.get("isPermanent")]
    permanent = [item for item in items if item.get("isPermanent")]
    if total == 0:
        add_finding(findings, "P1", "카드 없음", "최종 리포트에 표시할 카드 데이터가 없습니다.")
        return

    if parser.feature_cards != len(timed):
        add_finding(
            findings,
            "P2",
            "추천 보기 카드 수 불일치",
            "추천 보기 영역의 카드 수와 기간 일정 데이터 수가 다릅니다.",
            f"feature_cards={parser.feature_cards}, timed_items={len(timed)}",
        )
    if parser.list_cards != total:
        add_finding(
            findings,
            "P2",
            "목록 카드 수 불일치",
            "기간 일정/상설전 목록 카드 수와 전체 카드 데이터 수가 다릅니다.",
            f"list_cards={parser.list_cards}, total_items={total}",
        )

    expected_static_card_buttons = len(timed) * 2 + len(permanent)
    if len(parser.data_indexes) != expected_static_card_buttons:
        add_finding(
            findings,
            "P2",
            "클릭 가능한 카드 버튼 수 불일치",
            "정적 HTML의 카드 버튼 개수가 데이터 구조와 맞지 않습니다.",
            f"data-index={len(parser.data_indexes)}, expected={expected_static_card_buttons}",
        )

    valid_indexes = set(range(total))
    parsed_card_indexes = []
    for raw in parser.data_indexes:
        try:
            parsed_card_indexes.append(int(raw))
        except ValueError:
            add_finding(findings, "P1", "잘못된 카드 인덱스", "카드 버튼의 data-index가 숫자가 아닙니다.", raw)
    invalid_indexes = sorted(set(parsed_card_indexes) - valid_indexes)
    if invalid_indexes:
        add_finding(
            findings,
            "P1",
            "없는 카드로 연결되는 버튼",
            "클릭하면 세부창을 열 수 없는 data-index가 있습니다.",
            ", ".join(map(str, invalid_indexes[:20])),
        )

    missing_card_indexes = sorted(valid_indexes - set(parsed_card_indexes))
    if missing_card_indexes:
        add_finding(
            findings,
            "P2",
            "화면에서 접근 불가한 카드",
            "데이터에는 있지만 카드 버튼으로 열 수 없는 일정이 있습니다.",
            ", ".join(map(str, missing_card_indexes[:20])),
        )

    for raw in parser.feature_indexes:
        try:
            index = int(raw)
        except ValueError:
            continue
        if 0 <= index < total and items[index].get("isPermanent"):
            add_finding(
                findings,
                "P1",
                "상설전이 추천 보기 영역에 섞임",
                "추천 보기는 기간 일정만 보여야 하는데 상설전 카드가 포함됐습니다.",
                f"index={index}, title={items[index].get('displayTitle')}",
            )
            break

    summary_match = re.search(r"진행/예정\s+(\d+)건", parser.visible_text)
    if summary_match and int(summary_match.group(1)) != total:
        add_finding(
            findings,
            "P2",
            "상단 카드 수 표시 불일치",
            "상단 요약의 카드 수와 실제 데이터 수가 다릅니다.",
            f"summary={summary_match.group(1)}, total={total}",
        )


def check_items(findings, items):
    seen_ids = set()
    duplicate_ids = []
    source_missing = []
    image_bad = []
    companion_bad = []
    badge_bad = []
    timed_badge_count = 0

    for index, item in enumerate(items):
        item_id = item.get("id")
        title = shorten(item.get("displayTitle") or item.get("title") or "제목 없음", 90)
        if item_id in seen_ids:
            duplicate_ids.append(str(item_id))
        seen_ids.add(item_id)

        for field in ("displayTitle", "displayVenue", "period", "type", "status"):
            if not str(item.get(field) or "").strip():
                add_finding(
                    findings,
                    "P1",
                    "카드 핵심 문구 누락",
                    f"event {item_id} '{title}'의 {field} 값이 비었습니다.",
                )

        if not valid_url(item.get("sourceUrl")):
            source_missing.append(f"{item_id} | {title} | {item.get('sourceUrl')}")

        image_url = item.get("imageUrl")
        if image_url and not valid_url(image_url):
            image_bad.append(f"{item_id} | {title} | {image_url}")

        badges = item.get("curationBadges") or []
        if badges and not item.get("isPermanent"):
            timed_badge_count += 1
        for badge in badges:
            label = badge.get("label")
            tone = badge.get("tone")
            if label not in EDITORIAL_BADGE_LABELS or tone not in EDITORIAL_BADGE_TONES:
                badge_bad.append(f"{item_id} | {title} | {label} | {tone}")

        description = item.get("description") or ""
        if len(description) > 700:
            add_finding(
                findings,
                "P3",
                "세부 설명 과다",
                "세부창 설명이 너무 길어 카드 리포트에서 읽기 어려울 수 있습니다.",
                f"{item_id} | {title} | {shorten(description, 220)}",
            )

        for label, text in iter_item_texts(item):
            scan_text_for_markers(findings, label, text)

        for companion in item.get("companionEvents") or []:
            companion_index = companion.get("index")
            if not isinstance(companion_index, int) or not 0 <= companion_index < len(items):
                companion_bad.append(f"{item_id} | {title} -> {companion_index}")

        for link in item.get("relatedLinks") or []:
            if not valid_url(link.get("url")):
                add_finding(
                    findings,
                    "P2",
                    "후기/검색 링크 오류",
                    "세부창에 표시되는 후기/검색 링크 URL이 유효하지 않습니다.",
                    f"{item_id} | {title} | {link.get('title')} | {link.get('url')}",
                )

    if duplicate_ids:
        add_finding(
            findings,
            "P2",
            "중복 카드 ID",
            "같은 일정 ID가 카드 데이터에 여러 번 들어 있습니다.",
            ", ".join(duplicate_ids[:40]),
        )
    if source_missing:
        add_finding(
            findings,
            "P1",
            "원문 링크 오류",
            "세부창의 '원문 보기'가 열리지 않을 카드가 있습니다.",
            "\n".join(source_missing[:20]),
        )
    if image_bad:
        add_finding(
            findings,
            "P3",
            "이미지 URL 형식 오류",
            "이미지 감사에서 별도 확인할 이미지 URL 형식 문제가 있습니다.",
            "\n".join(image_bad[:20]),
        )
    if not timed_badge_count:
        add_finding(
            findings,
            "P2",
            "추천 카드 배지 데이터 없음",
            "기간 일정 추천 카드에 사람이 바로 이해할 수 있는 큐레이션 배지가 없습니다.",
        )
    if badge_bad:
        add_finding(
            findings,
            "P2",
            "추천 배지 값 오류",
            "정의되지 않은 추천 배지 문구나 색상 톤이 카드 데이터에 들어 있습니다.",
            "\n".join(badge_bad[:20]),
        )
    if companion_bad:
        add_finding(
            findings,
            "P1",
            "같은 장소 다른 일정 연결 오류",
            "세부창의 같은 장소 버튼이 존재하지 않는 카드로 연결됩니다.",
            "\n".join(companion_bad[:20]),
        )


def verdict(findings):
    priorities = Counter(item["priority"] for item in findings)
    if priorities["P1"] or priorities["P2"]:
        return "확인 필요"
    if priorities["P3"]:
        return "주의"
    return "통과"


def render_findings(lines, findings):
    if not findings:
        lines.append("- 없음")
        return
    priority_order = {"P1": 1, "P2": 2, "P3": 3}
    for item in sorted(findings, key=lambda row: (priority_order.get(row["priority"], 9), row["title"])):
        lines.append(f"- [{item['priority']}] {item['title']}: {item['detail']}")
        if item.get("evidence"):
            evidence = item["evidence"].replace("\n", " / ")
            lines.append(f"  - 증거: {evidence}")


def manual_review_checklist():
    return [
        "첫 화면: 대표 추천, 오늘의 추천, 곧 끝나요, 한 장소에서 묶어보기 순서가 추천 리포트처럼 읽히는지 확인",
        "빠른 필터: 무료/가족/이번 주/교육/전시/서울/경기/인천을 각각 눌러 대표 추천과 추천 전체가 함께 바뀌는지 확인",
        "상세 필터: 기본 접힘 상태에서 열기, 관심 키워드/지역/일정/우선순위/초기화를 눌러 요약 문구가 자연스럽게 바뀌는지 확인",
        "추천 전체: 카드 제목이 2줄 안에서 정리되고 배지가 1-2초 안에 이해되는지 확인",
        "기간 일정: 전체/전시/강연/교육/행사 필터를 누르고 숨김 카드가 남거나 빈 공간이 어색하지 않은지 확인",
        "상설전: 상설전 탭의 첫 12개와 이미지 없는 카드 몇 개를 열어 기간/상태 문구가 기간 일정과 섞이지 않는지 확인",
        "세부창: 왜 추천하나요, 원문 보기, 후기/검색 링크, 같은 장소에서 함께 볼 것, 세부 회차 목록이 있는 카드와 없는 카드를 각각 확인",
        "문구 품질: 국립중앙박물관, 자동 모니터 출신 기관, 설명이 긴 카드에서 코드/푸터/깨진 글자가 보이지 않는지 확인",
        "화면 크기: 데스크톱 1366x900과 모바일 390x844에서 버튼, 카드 제목, 세부창 텍스트가 겹치거나 잘리지 않는지 확인",
    ]


def write_report(report_path, html_path, parser, items, findings):
    timed = [item for item in items if not item.get("isPermanent")]
    permanent = [item for item in items if item.get("isPermanent")]
    priorities = Counter(item["priority"] for item in findings)
    lines = [
        "# UI 품질 자동 점검 리포트",
        "",
        f"- 판정: {verdict(findings)}",
        f"- 실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 대상 HTML: {html_path}",
        f"- 전체 카드: {len(items)}건",
        f"- 기간 일정: {len(timed)}건",
        f"- 상설전: {len(permanent)}건",
        f"- 추천 보기 카드 DOM: {parser.feature_cards}개",
        f"- 목록 카드 DOM: {parser.list_cards}개",
        f"- 확인 필요: P1 {priorities['P1']}건, P2 {priorities['P2']}건, P3 {priorities['P3']}건",
        "",
        "## 자동 점검 결과",
        "",
    ]
    render_findings(lines, findings)
    lines.extend(
        [
            "",
            "## 수동 클릭 리뷰 체크리스트",
            "",
        ]
    )
    for item in manual_review_checklist():
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## 판정 기준",
            "",
            "- P1: 사용자가 바로 신뢰를 잃거나 기능을 쓸 수 없는 문제",
            "- P2: 흐름은 가능하지만 카드/세부창/보기 전환의 일관성이 깨지는 문제",
            "- P3: 다음 정리 때 함께 다듬으면 좋은 작은 품질 문제",
            "",
        ]
    )
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    args = parse_args()
    html_path = args.html
    report_path = args.report
    findings = []

    if not html_path.exists():
        add_finding(findings, "P1", "HTML 파일 없음", "점검할 최종 리포트 파일이 없습니다.", str(html_path))
        parser = CardHtmlParser()
        items = []
    else:
        try:
            html_text = html_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            html_text = ""
            add_finding(
                findings,
                "P1",
                "HTML 인코딩 오류",
                "최종 리포트를 UTF-8로 읽지 못했습니다.",
                str(exc),
            )

        parser = CardHtmlParser()
        parser.feed(html_text)
        try:
            items = extract_items(html_text) if html_text else []
        except (ValueError, json.JSONDecodeError) as exc:
            items = []
            add_finding(
                findings,
                "P1",
                "카드 데이터 파싱 실패",
                "HTML 안의 카드 데이터를 읽지 못해 클릭 흐름을 검증할 수 없습니다.",
                str(exc),
            )
        if html_text:
            check_html_structure(findings, parser, html_text, items)
        if items:
            check_items(findings, items)

    write_report(report_path, html_path, parser, items, findings)
    print(f"verdict={verdict(findings)}")
    print(f"p1={Counter(item['priority'] for item in findings)['P1']}")
    print(f"p2={Counter(item['priority'] for item in findings)['P2']}")
    print(f"p3={Counter(item['priority'] for item in findings)['P3']}")
    print(f"report={report_path}")


if __name__ == "__main__":
    main()
