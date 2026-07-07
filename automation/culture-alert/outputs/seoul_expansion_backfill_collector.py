import sqlite3
from pathlib import Path

from a_grade_backfill_collector import DB_PATH, ensure_tables
from c_grade_backfill_collector import get_institution_id, load_metadata, upsert_event


BASE_DIR = Path(__file__).resolve().parent
REPORT_PATH = BASE_DIR / "seoul-expansion-backfill-report.md"
PROMOTED_PHASE = "phase2-auto-monitor"


PUBLIC_SOURCES = [
    (
        "둘리뮤지엄",
        "https://www.doolymuseum.or.kr",
        "둘리와 한국 만화 캐릭터 문화를 중심으로 한 가족형 박물관. 어린이 체험, 전시, 교육 일정을 우선 모니터링한다.",
        "만화;캐릭터;어린이;가족;체험;공립;서울;도봉구",
    ),
    (
        "서대문형무소역사관",
        "https://www.sphh.sscmc.or.kr",
        "근현대사와 독립운동사를 다루는 역사관. 역사 전시와 시민 대상 교육·해설 일정을 우선 모니터링한다.",
        "근현대사;독립운동;역사;교육;공립;서울;서대문구",
    ),
    (
        "서울상상나라",
        "https://www.seoulchildrensmuseum.org",
        "어린이 체험 전시와 가족 교육이 중심인 공립 어린이박물관. 주말·방학 프로그램을 함께 모니터링한다.",
        "어린이;가족;체험;교육;주말;공립;서울;광진구",
    ),
    (
        "서울약령시한의약박물관",
        "https://kmedi.ddm.go.kr",
        "한의약, 약령시, 생활 건강 문화를 다루는 박물관. 전시와 체험 교육 일정을 우선 모니터링한다.",
        "한의학;의학;생활문화;체험;교육;공립;서울;동대문구",
    ),
    (
        "손기정기념관",
        "https://www.sonkeechung.com",
        "손기정 선수와 한국 스포츠사를 다루는 기념관. 스포츠·근현대사 전시와 교육 일정을 모니터링한다.",
        "스포츠;근현대사;인물;역사;공립;서울;중구",
    ),
    (
        "송파책박물관",
        "https://www.bookmuseum.go.kr",
        "책, 출판, 독서 문화를 다루는 박물관. 기획전, 강연, 독서·출판 교육 일정을 우선 모니터링한다.",
        "책;출판;문학;강연;교육;공립;서울;송파구",
    ),
    (
        "수도박물관",
        "https://arisu.seoul.go.kr/arisumuseum",
        "서울 수돗물과 도시 기반 시설의 역사를 다루는 박물관. 도시사·생활사 전시와 해설 일정을 모니터링한다.",
        "도시사;생활사;환경;물;역사;공립;서울;성동구",
    ),
    (
        "암사동선사유적박물관",
        "https://sunsa.gangdong.go.kr",
        "선사시대 유적과 고고학 체험을 다루는 박물관. 어린이·가족 체험 교육 일정을 우선 모니터링한다.",
        "선사;고고학;역사;어린이;체험;공립;서울;강동구",
    ),
    (
        "용산역사박물관",
        "https://museum.yongsan.go.kr",
        "용산 지역사와 도시 변화를 다루는 박물관. 지역사 전시와 시민 강연·교육 일정을 모니터링한다.",
        "지역사;도시사;근현대사;강연;공립;서울;용산구",
    ),
    (
        "G밸리산업박물관",
        "https://www.seoul.go.kr/museumg/index.do",
        "구로공단과 G밸리 산업사를 다루는 박물관. 산업사, 노동사, 도시사 전시를 우선 모니터링한다.",
        "산업사;노동사;도시사;근현대사;공립;서울;구로구",
    ),
    (
        "성북근현대문학관",
        "https://www.instagram.com/.culturalspace264?igsh=YmtiZWwwZzg5NTN2",
        "성북의 근현대 문학 자원을 다루는 공립 문학 공간. 전시와 문학 강연·낭독 일정을 우선 모니터링한다.",
        "문학;근현대사;지역사;강연;공립;서울;성북구",
    ),
    (
        "DDP디자인뮤지엄",
        "https://www.ddp.or.kr",
        "디자인, 건축, 도시문화 전시가 중심인 DDP의 미술관 성격 공간. 디자인 전시와 시민 프로그램을 모니터링한다.",
        "디자인;건축;도시문화;현대미술;공립;서울;중구",
    ),
]


PRIVATE_SOURCES = [
    (
        "가회민화박물관",
        "https://www.gahoemuseum.org",
        "민화와 전통 생활문화를 다루는 사립 박물관. 민화 전시와 체험 교육 일정을 우선 모니터링한다.",
        "민화;전통;한국미술;공예;체험;서울;종로구",
    ),
    (
        "간송박물관",
        "https://kansong.org",
        "한국 고미술과 문화재를 중심으로 한 박물관. 고미술 특별전과 관련 강연 일정을 우선 모니터링한다.",
        "고미술;한국미술;문화재;전통;강연;서울;성북구",
    ),
    (
        "김달진미술자료박물관",
        "https://daljinmuseum.com",
        "한국 미술 자료와 아카이브를 중심으로 한 박물관. 미술사 자료 전시와 연구형 강연을 모니터링한다.",
        "미술자료;아카이브;미술사;강연;서울;종로구",
    ),
    (
        "목인박물관 목석원",
        "https://www.mokinmuseum.com",
        "목조각, 석조각, 민속 조형물을 다루는 박물관. 전통 조형과 가족 관람 일정을 우선 모니터링한다.",
        "목조각;석조각;민속;전통;가족;서울;종로구",
    ),
    (
        "뮤지엄김치간",
        "https://www.kimchikan.com",
        "김치와 발효 음식 문화를 다루는 박물관. 음식문화 전시와 체험 교육 일정을 모니터링한다.",
        "음식문화;김치;발효;생활문화;체험;서울;종로구",
    ),
    (
        "불교중앙박물관",
        "https://museum.buddhism.or.kr",
        "불교 문화재와 불교미술을 다루는 박물관. 불교미술 전시와 인문 강연 일정을 모니터링한다.",
        "불교미술;문화재;종교;전통;강연;서울;종로구",
    ),
    (
        "세계장신구박물관",
        "https://www.wjm.or.kr",
        "세계 장신구와 공예 문화를 다루는 박물관. 공예·디자인 전시와 체험 프로그램을 모니터링한다.",
        "장신구;공예;디자인;세계문화;서울;종로구",
    ),
    (
        "우리옛돌박물관",
        "https://www.koreanstonemuseum.com",
        "석조 유물과 정원 문화를 다루는 박물관. 전통 조형과 야외 관람 정보를 모니터링한다.",
        "석조;전통;야외전시;한국미술;서울;성북구",
    ),
    (
        "혜곡최순우기념관",
        "https://ntculture.or.kr",
        "최순우 선생의 삶과 한국 미학을 다루는 기념관. 전통미술, 공예, 인문 강연을 우선 모니터링한다.",
        "한국미학;전통;공예;인문;강연;서울;성북구",
    ),
    (
        "자하미술관",
        "https://www.zahamuseum.org",
        "현대미술 전시를 중심으로 운영되는 사립 미술관. 기획전과 작가 프로그램을 우선 모니터링한다.",
        "현대미술;작가;기획전;서울;종로구",
    ),
    (
        "토탈미술관",
        "https://totalmuseum.org",
        "현대미술과 건축적 공간 경험이 결합된 미술관. 전시와 작가·기획자 프로그램을 모니터링한다.",
        "현대미술;건축;작가;강연;서울;종로구",
    ),
    (
        "OCI미술관",
        "https://ocimuseum.org",
        "현대미술과 신진 작가 전시가 중심인 미술관. 전시와 작가 대화 일정을 우선 모니터링한다.",
        "현대미술;신진작가;작가;강연;서울;종로구",
    ),
    (
        "K현대미술관",
        "https://www.kmcaseoul.org",
        "대중 친화적 현대미술 전시가 중심인 강남권 미술관. 사진·미디어·체험형 전시를 우선 모니터링한다.",
        "현대미술;사진;미디어아트;체험;서울;강남구",
    ),
    (
        "롯데뮤지엄",
        "https://www.lottemuseum.com",
        "동시대 미술과 대형 기획전이 중심인 미술관. 특별전과 아티스트 토크 일정을 모니터링한다.",
        "현대미술;대형전시;특별전;강연;서울;송파구",
    ),
    (
        "세종문화회관 미술관",
        "https://www.sejongpac.or.kr",
        "세종문화회관 내 전시 공간. 미술 전시, 디자인, 대중 문화형 기획전을 우선 모니터링한다.",
        "미술;디자인;대중문화;전시;서울;종로구",
    ),
    (
        "세화미술관",
        "https://www.sehwamuseum.org",
        "현대미술 전시와 도심 속 미술 경험이 중심인 미술관. 전시와 공공 프로그램을 모니터링한다.",
        "현대미술;도시문화;공공프로그램;서울;종로구",
    ),
    (
        "아라리오뮤지엄 인 스페이스",
        "https://www.arariomuseum.org",
        "건축 공간과 현대미술 컬렉션이 결합된 미술관. 컬렉션 전시와 공간 관람 정보를 모니터링한다.",
        "현대미술;건축;컬렉션;서울;종로구",
    ),
    (
        "아트센터나비미술관",
        "https://www.nabi.or.kr",
        "미디어아트와 기술 기반 예술이 중심인 미술관. 전시, 워크숍, 강연 일정을 우선 모니터링한다.",
        "미디어아트;기술;디지털아트;워크숍;강연;서울;종로구",
    ),
    (
        "김세중미술관",
        "https://www.kimsechoong.com",
        "조각과 현대미술 전시가 중심인 미술관. 조각, 작가전, 교육 프로그램을 모니터링한다.",
        "조각;현대미술;작가;교육;서울;용산구",
    ),
    (
        "헬로우뮤지움",
        "https://www.hellomuseum.com",
        "어린이와 가족을 위한 현대미술 교육형 미술관. 체험 전시와 교육 일정을 우선 모니터링한다.",
        "어린이;가족;현대미술;체험;교육;서울;성동구",
    ),
]


UNIVERSITY_SOURCES = [
    (
        "서울과학기술대학교 미술관",
        "https://art.seoultech.ac.kr",
        "대학 미술관 전시와 학내외 예술 프로그램을 모니터링한다. 학생·지역 연계 전시를 우선 확인한다.",
        "대학미술관;현대미술;학생전;지역연계;서울;노원구",
    ),
    (
        "숙명여자대학교문신미술관",
        "https://home.sookmyung.ac.kr/moonshin/index.do",
        "문신 조각과 대학 미술관 전시를 중심으로 모니터링한다. 조각, 작가 연구, 교육 일정을 함께 확인한다.",
        "대학미술관;조각;작가;미술사;서울;용산구",
    ),
    (
        "한양대학교박물관",
        "https://museumuf.hanyang.ac.kr",
        "대학 박물관의 역사·문화 전시와 시민 공개 교육 일정을 모니터링한다.",
        "대학박물관;역사;문화;교육;서울;성동구",
    ),
]


def make_source(name, url, description, keywords, group):
    return {
        "name": name,
        "tier": "C",
        "collection_strategy": (
            "서울시 2026 박물관·미술관 정보와 공식 홈페이지 기준으로 1차 편입. "
            "대표 관람 카드를 먼저 만들고, 전시·교육 목록 구조가 안정적인 기관은 개별 자동수집기로 승격한다."
        ),
        "events": [
            {
                "content_type": "전시",
                "title": f"{name} 전시·교육 모니터",
                "start_date": None,
                "end_date": None,
                "location": name,
                "price": "기관별 확인",
                "description": description,
                "keywords": f"{keywords};{group};서울확장",
                "source_url": url,
                "status": "상설전시",
            }
        ],
    }


SEOUL_EXPANSION_SOURCES = [
    *(make_source(*item, "공립") for item in PUBLIC_SOURCES),
    *(make_source(*item, "사립") for item in PRIVATE_SOURCES),
    *(make_source(*item, "대학") for item in UNIVERSITY_SOURCES),
]


def build_report(results, totals):
    inserted = sum(1 for item in results if item["result"] == "inserted")
    updated = sum(1 for item in results if item["result"] == "updated")
    image_count = sum(1 for item in results if item.get("image_url"))
    lines = [
        "# 서울 소규모 기관 자동 모니터 승격 결과",
        "",
        f"- 대상 기관: {len(SEOUL_EXPANSION_SOURCES)}개",
        f"- 새로 넣은 카드: {inserted}개",
        f"- 갱신한 카드: {updated}개",
        f"- 자동 확인된 이미지: {image_count}개",
        "- 추천 카드 노출: 제외",
        "- 주간 공식 페이지 점검: 포함",
        f"- 현재 DB 기관 수: {totals['institutions']}개",
        f"- 현재 DB 전체 일정 수: {totals['events']}개",
        "",
        "## 처리 목록",
        "",
    ]
    for item in results:
        image_note = "이미지 확인" if item.get("image_url") else "이미지 없음"
        lines.append(f"- {item['result']} | {item['institution']} | {item['status']} | {image_note} | {item['source_url']}")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    metadata = load_metadata()
    missing_source_meta = [item["name"] for item in SEOUL_EXPANSION_SOURCES if item["name"] not in metadata]
    if missing_source_meta:
        raise RuntimeError(f"후보 목록에 없는 기관: {', '.join(missing_source_meta)}")

    results = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_tables(conn)
        for source in SEOUL_EXPANSION_SOURCES:
            row_meta = metadata[source["name"]]
            working_source = dict(source)
            working_source["region"] = row_meta.get("region")
            working_source["city"] = row_meta.get("city")
            institution_id = get_institution_id(conn, working_source, row_meta)
            conn.execute(
                """
                UPDATE institutions
                SET collection_phase = ?,
                    notes = COALESCE(notes, '서울 소규모 기관 자동 모니터 승격'),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (PROMOTED_PHASE, institution_id),
            )
            for event in working_source["events"]:
                results.append(upsert_event(conn, institution_id, working_source, event))
        conn.commit()
        totals = {
            "institutions": conn.execute("SELECT COUNT(*) FROM institutions").fetchone()[0],
            "events": conn.execute("SELECT COUNT(*) FROM cultural_events").fetchone()[0],
        }

    build_report(results, totals)
    print(f"checked={len(SEOUL_EXPANSION_SOURCES)}")
    print(f"events={len(results)}")
    print(f"inserted={sum(1 for item in results if item['result'] == 'inserted')}")
    print(f"updated={sum(1 for item in results if item['result'] == 'updated')}")
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
