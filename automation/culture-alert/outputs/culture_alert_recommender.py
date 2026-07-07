import argparse
import html
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "culture-alert.sqlite"
REPORT_PATH = BASE_DIR / "keyword-recommendation-report.md"
HTML_REPORT_PATH = BASE_DIR / "keyword-recommendation-report.html"


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def days_until(value):
    parsed = parse_date(value)
    if not parsed:
        return None
    return (parsed - date.today()).days


def load_interests(conn, person_name):
    return conn.execute(
        """
        SELECT keyword, weight
        FROM interests
        WHERE person_name = ? AND active = 1
        ORDER BY weight DESC, keyword
        """,
        (person_name,),
    ).fetchall()


def load_events(conn):
    return conn.execute(
        """
        SELECT
          e.id,
          i.name AS institution_name,
          e.title,
          e.start_date,
          e.end_date,
          e.location,
          e.status,
          e.description,
          e.keywords,
          e.source_url,
          e.raw_text,
          e.image_url
        FROM cultural_events e
        JOIN institutions i ON i.id = e.institution_id
        WHERE e.status != '종료'
        ORDER BY COALESCE(e.end_date, '9999-12-31'), e.start_date, e.title
        """
    ).fetchall()


def load_related_links(conn, event_ids):
    if not event_ids:
        return {}
    table_exists = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'related_links'
        """
    ).fetchone()
    if not table_exists:
        return {}
    placeholders = ",".join("?" for _ in event_ids)
    rows = conn.execute(
        f"""
        SELECT event_id, title, url, source, link_type
        FROM related_links
        WHERE event_id IN ({placeholders})
        ORDER BY event_id, rank, title
        """,
        event_ids,
    ).fetchall()
    links_by_event = {}
    for event_id, title, url, source, link_type in rows:
        links_by_event.setdefault(event_id, []).append(
            {
                "title": title,
                "url": url,
                "source": source,
                "type": link_type,
            }
        )
    return links_by_event


def score_event(event, interests):
    (
        event_id,
        institution_name,
        title,
        start_date,
        end_date,
        location,
        status,
        description,
        keywords,
        source_url,
        raw_text,
        image_url,
    ) = event
    searchable = " ".join(
        value or ""
        for value in [institution_name, title, location, description, keywords, raw_text]
    ).lower()
    matched = []
    score = 0
    for keyword, weight in interests:
        if keyword.lower() in searchable:
            matched.append(keyword)
            score += weight

    until_end = days_until(end_date)
    if until_end is not None:
        if 0 <= until_end <= 14:
            score += 3
            matched.append("곧 종료")
        elif 0 <= until_end <= 30:
            score += 1

    until_start = days_until(start_date)
    if until_start is not None and 0 <= until_start <= 14:
        score += 1
        matched.append("곧 시작")

    return score, matched


def upsert_recommendations(conn, person_name, scored_events):
    conn.execute("DELETE FROM recommendations WHERE person_name = ?", (person_name,))
    for event, score, matched in scored_events:
        reason = ", ".join(dict.fromkeys(matched))
        conn.execute(
            """
            INSERT INTO recommendations (event_id, person_name, score, matched_keywords, reason)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event[0], person_name, score, reason, reason),
        )
    conn.commit()


def format_period(start_date, end_date):
    if start_date and end_date:
        return f"{start_date} ~ {end_date}"
    if start_date:
        return f"{start_date} ~"
    if end_date:
        return f"~ {end_date}"
    return "기간 확인 필요"


def build_report(person_name, interests, scored_events, all_events):
    keyword_text = ", ".join(f"{keyword}({weight})" for keyword, weight in interests)
    top_matches = [item for item in scored_events if item[1] > 0][:12]
    ending_soon = [
        event
        for event in all_events
        if (days_until(event[4]) is not None and 0 <= days_until(event[4]) <= 30)
    ][:8]

    lines = [
        "# 관심 키워드 추천 리포트",
        "",
        f"- 대상: {person_name}",
        f"- 관심 키워드: {keyword_text or '없음'}",
        f"- 검토한 일정: {len(all_events)}건",
        f"- 키워드에 걸린 일정: {len([item for item in scored_events if item[1] > 0])}건",
        "",
        "## 추천 일정",
        "",
    ]

    if not top_matches:
        lines.append("현재 관심 키워드와 직접 맞는 일정을 찾지 못했습니다.")
    for event, score, matched in top_matches:
        (
            _event_id,
            institution_name,
            title,
            start_date,
            end_date,
            location,
            status,
            _description,
            _keywords,
            source_url,
            _raw_text,
            _image_url,
        ) = event
        reason = ", ".join(dict.fromkeys(matched)) or "일정 우선순위"
        lines.append(f"- {title}")
        lines.append(f"  - 기관: {institution_name}")
        lines.append(f"  - 기간: {format_period(start_date, end_date)}")
        lines.append(f"  - 장소: {location or '확인 필요'}")
        lines.append(f"  - 추천 이유: {reason} / 점수 {score}")
        lines.append(f"  - 링크: {source_url}")

    lines.extend(["", "## 곧 끝나는 일정", ""])
    if not ending_soon:
        lines.append("30일 안에 종료되는 일정이 없습니다.")
    for event in ending_soon:
        (
            _event_id,
            institution_name,
            title,
            start_date,
            end_date,
            location,
            status,
            _description,
            _keywords,
            source_url,
            _raw_text,
            _image_url,
        ) = event
        remaining = days_until(end_date)
        lines.append(f"- {title}")
        lines.append(f"  - 기관: {institution_name}")
        lines.append(f"  - 기간: {format_period(start_date, end_date)}")
        lines.append(f"  - 종료까지: {remaining}일")
        lines.append(f"  - 장소: {location or '확인 필요'}")
        lines.append(f"  - 링크: {source_url}")

    lines.extend(["", "## 키워드별 일정", ""])
    for keyword, _weight in interests:
        matches = []
        for event in all_events:
            searchable = " ".join(str(value or "") for value in event).lower()
            if keyword.lower() in searchable:
                matches.append(event)
        lines.append(f"### {keyword}")
        lines.append("")
        if not matches:
            lines.append("- 현재 매칭된 일정 없음")
            lines.append("")
            continue
        for event in matches[:8]:
            lines.append(
                f"- {event[2]} / {event[1]} / {format_period(event[3], event[4])}"
            )
        lines.append("")

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_html_report(person_name, interests, scored_events, all_events, related_links):
    top_matches = [item for item in scored_events if item[1] > 0][:12]
    keyword_text = ", ".join(keyword for keyword, _weight in interests)

    def detail_text(description, raw_text):
        text = description or raw_text or ""
        text = " ".join(str(text).split())
        if len(text) > 260:
            return text[:260].rstrip() + "..."
        return text

    details = []

    def card(index, event, score=None, matched=None):
        (
            event_id,
            institution_name,
            title,
            start_date,
            end_date,
            location,
            status,
            description,
            _keywords,
            source_url,
            raw_text,
            image_url,
        ) = event
        image = image_url or ""
        reason = ", ".join(dict.fromkeys(matched or [])) or "관심 일정"
        period = format_period(start_date, end_date)
        details.append(
            {
                "title": title,
                "institution": institution_name,
                "period": period,
                "location": location or "확인 필요",
                "status": status or "확인 필요",
                "reason": reason,
                "score": f"{score:g}" if score is not None else "",
                "sourceUrl": source_url,
                "imageUrl": image,
                "description": detail_text(description, raw_text),
                "relatedLinks": related_links.get(event_id, []),
            }
        )
        image_html = (
            f'<img src="{html.escape(image)}" alt="{html.escape(title)}">'
            if image
            else '<div class="image-placeholder">NO IMAGE</div>'
        )
        score_html = f'<span class="score">추천 {score:g}</span>' if score is not None else ""
        return f"""
        <article class="card">
          <button class="card-button" type="button" data-detail-index="{index}">
            <div class="poster">{image_html}</div>
            <div class="body">
              <div class="meta">
                <span>{html.escape(institution_name)}</span>
                {score_html}
              </div>
              <h2>{html.escape(title)}</h2>
              <dl>
                <div><dt>기간</dt><dd>{html.escape(period)}</dd></div>
                <div><dt>장소</dt><dd>{html.escape(location or "확인 필요")}</dd></div>
                <div><dt>이유</dt><dd>{html.escape(reason)}</dd></div>
              </dl>
            </div>
          </button>
        </article>
        """

    cards = "\n".join(
        card(index, event, score, matched)
        for index, (event, score, matched) in enumerate(top_matches)
    )
    if not cards:
        cards = '<p class="empty">현재 관심 키워드와 직접 맞는 일정을 찾지 못했습니다.</p>'
    details_json = json.dumps(details, ensure_ascii=False).replace("</", "<\\/")

    html_text = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>관심 키워드 추천 리포트</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #1f2933;
      --muted: #667085;
      --line: #d8dee8;
      --paper: #f7f4ef;
      --panel: #ffffff;
      --accent: #0f766e;
      --accent-soft: #e0f2ef;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.55;
    }}
    main {{
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto;
      padding: 32px 0 48px;
    }}
    header {{
      margin-bottom: 24px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 18px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 28px;
      line-height: 1.2;
      letter-spacing: 0;
    }}
    .summary {{
      margin: 0;
      color: var(--muted);
      font-size: 15px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 18px;
    }}
    .card {{
      display: grid;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }}
    .card-button {{
      display: grid;
      grid-template-rows: auto 1fr;
      width: 100%;
      height: 100%;
      padding: 0;
      border: 0;
      background: transparent;
      color: inherit;
      text-align: left;
      font: inherit;
      cursor: pointer;
    }}
    .card-button:focus-visible {{
      outline: 3px solid var(--accent);
      outline-offset: 3px;
    }}
    .card:hover {{
      border-color: #aab4c3;
      box-shadow: 0 12px 28px rgba(31, 41, 51, 0.12);
      transform: translateY(-2px);
      transition: box-shadow 160ms ease, transform 160ms ease, border-color 160ms ease;
    }}
    .poster {{
      aspect-ratio: 4 / 3;
      background: #e8edf2;
      color: inherit;
    }}
    .poster img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }}
    .image-placeholder {{
      display: grid;
      place-items: center;
      height: 100%;
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0;
    }}
    .body {{
      padding: 16px;
    }}
    .meta {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
      font-size: 13px;
    }}
    .score {{
      flex: 0 0 auto;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      padding: 2px 8px;
      font-weight: 700;
    }}
    h2 {{
      margin: 8px 0 14px;
      font-size: 18px;
      line-height: 1.35;
      letter-spacing: 0;
    }}
    dl {{
      display: grid;
      gap: 8px;
      margin: 0;
      font-size: 14px;
    }}
    dl div {{
      display: grid;
      grid-template-columns: 44px 1fr;
      gap: 8px;
    }}
    dt {{
      color: var(--muted);
    }}
    dd {{
      margin: 0;
    }}
    .empty {{
      margin: 0;
      color: var(--muted);
    }}
    .overlay {{
      position: fixed;
      inset: 0;
      z-index: 10;
      display: grid;
      place-items: center;
      padding: 24px;
      background: rgba(31, 41, 51, 0.48);
    }}
    .overlay[hidden] {{
      display: none;
    }}
    .detail-panel {{
      width: min(860px, 100%);
      max-height: min(780px, calc(100vh - 48px));
      overflow: auto;
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 24px 70px rgba(31, 41, 51, 0.28);
    }}
    .detail-layout {{
      display: grid;
      grid-template-columns: minmax(220px, 340px) 1fr;
    }}
    .detail-image {{
      min-height: 100%;
      background: #e8edf2;
    }}
    .detail-image img {{
      width: 100%;
      height: 100%;
      min-height: 420px;
      object-fit: cover;
      display: block;
    }}
    .detail-body {{
      padding: 24px;
    }}
    .detail-top {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      margin-bottom: 12px;
    }}
    .close-button {{
      flex: 0 0 auto;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fff;
      color: var(--ink);
      width: 36px;
      height: 36px;
      cursor: pointer;
      font-size: 18px;
      line-height: 1;
    }}
    .detail-kicker {{
      margin: 0 0 6px;
      color: var(--muted);
      font-size: 14px;
    }}
    .detail-title {{
      margin: 0;
      font-size: 26px;
      line-height: 1.28;
      letter-spacing: 0;
    }}
    .detail-description {{
      margin: 18px 0;
      color: #3d4852;
      font-size: 15px;
    }}
    .source-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 40px;
      border-radius: 6px;
      background: var(--accent);
      color: #fff;
      padding: 0 14px;
      font-weight: 700;
      text-decoration: none;
    }}
    .link-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 14px;
    }}
    .related-links {{
      margin-top: 18px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
    }}
    .related-title {{
      margin: 0 0 10px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }}
    .related-list {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .related-link {{
      display: inline-flex;
      align-items: center;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
      padding: 0 12px;
      font-size: 13px;
      font-weight: 700;
      text-decoration: none;
    }}
    .modal-open {{
      overflow: hidden;
    }}
    @media (max-width: 720px) {{
      main {{
        width: min(100% - 24px, 1120px);
        padding-top: 22px;
      }}
      .overlay {{
        padding: 12px;
      }}
      .detail-layout {{
        grid-template-columns: 1fr;
      }}
      .detail-image img {{
        min-height: 240px;
        max-height: 320px;
      }}
      .detail-title {{
        font-size: 22px;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{html.escape(person_name)} 관심 문화 일정 추천</h1>
      <p class="summary">관심 키워드: {html.escape(keyword_text or "없음")} · 검토한 일정 {len(all_events)}건</p>
    </header>
    <section class="grid">
      {cards}
    </section>
  </main>
  <div class="overlay" id="detailOverlay" hidden>
    <section class="detail-panel" role="dialog" aria-modal="true" aria-labelledby="detailTitle">
      <div class="detail-layout">
        <div class="detail-image" id="detailImage"></div>
        <div class="detail-body">
          <div class="detail-top">
            <div>
              <p class="detail-kicker" id="detailInstitution"></p>
              <h2 class="detail-title" id="detailTitle"></h2>
            </div>
            <button class="close-button" type="button" id="detailClose" aria-label="닫기">×</button>
          </div>
          <dl>
            <div><dt>기간</dt><dd id="detailPeriod"></dd></div>
            <div><dt>장소</dt><dd id="detailLocation"></dd></div>
            <div><dt>상태</dt><dd id="detailStatus"></dd></div>
            <div><dt>이유</dt><dd id="detailReason"></dd></div>
          </dl>
          <p class="detail-description" id="detailDescription"></p>
          <div class="link-row">
            <a class="source-link" id="detailSource" href="#" target="_blank" rel="noopener">원문 보기</a>
          </div>
          <div class="related-links" id="detailRelated"></div>
        </div>
      </div>
    </section>
  </div>
  <script>
    const details = {details_json};
    const overlay = document.getElementById("detailOverlay");
    const closeButton = document.getElementById("detailClose");
    const imageBox = document.getElementById("detailImage");
    const fields = {{
      institution: document.getElementById("detailInstitution"),
      title: document.getElementById("detailTitle"),
      period: document.getElementById("detailPeriod"),
      location: document.getElementById("detailLocation"),
      status: document.getElementById("detailStatus"),
      reason: document.getElementById("detailReason"),
      description: document.getElementById("detailDescription"),
      source: document.getElementById("detailSource"),
      related: document.getElementById("detailRelated")
    }};

    function openDetail(index) {{
      const item = details[index];
      if (!item) return;
      imageBox.textContent = "";
      if (item.imageUrl) {{
        const img = document.createElement("img");
        img.src = item.imageUrl;
        img.alt = item.title;
        imageBox.appendChild(img);
      }} else {{
        const placeholder = document.createElement("div");
        placeholder.className = "image-placeholder";
        placeholder.textContent = "NO IMAGE";
        imageBox.appendChild(placeholder);
      }}
      fields.institution.textContent = item.institution + (item.score ? ` · 추천 ${{item.score}}` : "");
      fields.title.textContent = item.title;
      fields.period.textContent = item.period;
      fields.location.textContent = item.location;
      fields.status.textContent = item.status;
      fields.reason.textContent = item.reason;
      fields.description.textContent = item.description || "추가 설명은 원문에서 확인할 수 있습니다.";
      fields.source.href = item.sourceUrl;
      fields.related.textContent = "";
      if (item.relatedLinks && item.relatedLinks.length) {{
        const title = document.createElement("p");
        title.className = "related-title";
        title.textContent = "후기/검색";
        const list = document.createElement("div");
        list.className = "related-list";
        item.relatedLinks.forEach((link) => {{
          const anchor = document.createElement("a");
          anchor.className = "related-link";
          anchor.href = link.url;
          anchor.target = "_blank";
          anchor.rel = "noopener";
          anchor.textContent = link.title;
          list.appendChild(anchor);
        }});
        fields.related.appendChild(title);
        fields.related.appendChild(list);
        fields.related.hidden = false;
      }} else {{
        fields.related.hidden = true;
      }}
      overlay.hidden = false;
      document.body.classList.add("modal-open");
      closeButton.focus();
    }}

    function closeDetail() {{
      overlay.hidden = true;
      document.body.classList.remove("modal-open");
    }}

    document.querySelectorAll("[data-detail-index]").forEach((button) => {{
      button.addEventListener("click", () => openDetail(Number(button.dataset.detailIndex)));
    }});
    closeButton.addEventListener("click", closeDetail);
    overlay.addEventListener("click", (event) => {{
      if (event.target === overlay) closeDetail();
    }});
    document.addEventListener("keydown", (event) => {{
      if (event.key === "Escape" && !overlay.hidden) closeDetail();
    }});
  </script>
</body>
</html>
"""
    HTML_REPORT_PATH.write_text(html_text, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="관심 키워드 기반 전시 추천 리포트 생성기")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--person", default="가족")
    args = parser.parse_args()

    with sqlite3.connect(args.db) as conn:
        interests = load_interests(conn, args.person)
        events = load_events(conn)
        related_links = load_related_links(conn, [event[0] for event in events])
        scored_events = []
        for event in events:
            score, matched = score_event(event, interests)
            scored_events.append((event, score, matched))
        scored_events.sort(
            key=lambda item: (
                -item[1],
                days_until(item[0][4]) if days_until(item[0][4]) is not None else 99999,
                item[0][2],
            )
        )
        upsert_recommendations(conn, args.person, scored_events)
        build_report(args.person, interests, scored_events, events)
        build_html_report(args.person, interests, scored_events, events, related_links)

    print(f"events={len(events)} recommendations={len(scored_events)}")
    print(f"report={REPORT_PATH}")
    print(f"html_report={HTML_REPORT_PATH}")


if __name__ == "__main__":
    main()
