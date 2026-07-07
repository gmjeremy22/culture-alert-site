import sqlite3
from pathlib import Path

from a_grade_backfill_collector import DB_PATH, ensure_tables
from c_grade_backfill_collector import get_institution_id, load_metadata, upsert_event


BASE_DIR = Path(__file__).resolve().parent
REPORT_PATH = BASE_DIR / "small-local-backfill-report.md"


SMALL_LOCAL_SOURCES = [
    {
        "name": "겸재정선미술관",
        "tier": "C",
        "collection_strategy": "강서구 문화시설 공식 미술관 소개와 전시 공지 기준. 현재 진행 전시는 종료 시점이 가까워 우선 상설/대표 관람 항목으로 모니터링.",
        "events": [
            {
                "content_type": "전시",
                "title": "겸재정선미술관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "겸재정선미술관",
                "price": "일반 1,000원",
                "description": "겸재 정선의 예술세계와 진경산수화의 흐름을 소개하는 강서구립 미술관 상설 관람 항목.",
                "keywords": "한국미술;회화;역사;상설전시",
                "source_url": "https://culture.gangseo.seoul.kr/gsfc/main/contents.do?menuNo=800054",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "허준박물관",
        "tier": "C",
        "collection_strategy": "강서구 문화시설 공식 교육 목록과 허준박물관 소개 기준. 진행 중인 교육과 상설전시를 함께 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "허준박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "허준박물관",
                "price": None,
                "description": "구암 허준과 동의보감, 한의학 문화를 소개하는 공립박물관 상설전시.",
                "keywords": "역사;의학;한의학;어린이;가족;상설전시",
                "source_url": "https://www.much.go.kr/cooperation/net/hgm.do",
                "status": "상설전시",
            },
            {
                "content_type": "교육",
                "title": "2026 주말체험",
                "start_date": "2026-02-08",
                "end_date": "2026-07-18",
                "location": "허준박물관 체험교육실",
                "price": None,
                "description": "청소년 및 가족 대상 허준박물관 주말 체험 프로그램. 공식 교육 상세 기준으로 접수 기간은 2026-01-21~2026-07-18.",
                "keywords": "교육;체험;어린이;가족;주말;의학",
                "source_url": "https://culture.gangseo.seoul.kr/gsfc/education/view.do?eduSn=147&menuNo=800077",
            },
        ],
    },
    {
        "name": "성북구립미술관",
        "tier": "C",
        "collection_strategy": "성북구립미술관 공식 전시 상세 기준. 현재 전시가 바뀌면 deep 수집기와 공식 페이지 모니터가 함께 갱신.",
        "events": [
            {
                "content_type": "전시",
                "title": "2025 성북구립미술관 공공미술 프로젝트《생이 깃든 소나무: 이길래》",
                "start_date": "2025-02-26",
                "end_date": "2026-06-30",
                "location": "성북구립미술관 거리갤러리",
                "price": "무료",
                "description": "성북구립미술관 공공미술 프로젝트. 성북동 거리갤러리에서 이길래의 소나무 조각 작업을 중심으로 진행된다.",
                "keywords": "현대미술;한국미술;구립미술관;공공미술;조각",
                "source_url": "https://sma.sbculture.or.kr/sma/exhibition/current.do?mode=view&articleNo=43458&article.offset=0&articleLimit=10",
            }
        ],
    },
    {
        "name": "성북구립 최만린미술관",
        "tier": "C",
        "collection_strategy": "성북문화재단 최만린미술관 공식 전시 페이지 기준.",
        "events": [
            {
                "content_type": "전시",
                "title": "집: 두 조각가를 잇다",
                "start_date": "2026-04-02",
                "end_date": "2026-11-28",
                "location": "성북구립 최만린미술관 전관",
                "price": "무료",
                "description": "최만린과 박병욱의 관계를 조명하는 성북구립 최만린미술관 2026 기획전.",
                "keywords": "현대미술;조각;작가미술관;무료;장기전시",
                "source_url": "https://sma.sbculture.or.kr/cml/exhibition/past.do?articleNo=53327&mode=view",
            }
        ],
    },
    {
        "name": "성북선잠박물관",
        "tier": "C",
        "collection_strategy": "성북선잠박물관 공식 전시실 안내 기준.",
        "events": [
            {
                "content_type": "전시",
                "title": "성북선잠박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "성북선잠박물관",
                "price": "무료",
                "description": "선잠단, 선잠제, 친잠례와 전통 의생활 문화를 소개하는 공립박물관 상설전시.",
                "keywords": "역사;생활사;복식;공예;상설전시;무료",
                "source_url": "https://museum.sb.go.kr/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "종로구립 박노수미술관",
        "tier": "C",
        "collection_strategy": "종로문화재단 박노수미술관 공식 전시 안내 기준.",
        "events": [
            {
                "content_type": "전시",
                "title": "산수·격물 山水·格物",
                "start_date": "2025-09-19",
                "end_date": "2026-12-06",
                "location": "종로구립 박노수미술관",
                "price": None,
                "description": "박노수미술관 개관 12주년 기념전. 산수의 이치를 탐구하는 박노수의 사유와 조형 감각을 조명.",
                "keywords": "한국미술;회화;작가미술관;장기전시",
                "source_url": "https://www.jfac.or.kr/site/main/content/parkns01",
            }
        ],
    },
    {
        "name": "종로구립 고희동미술관",
        "tier": "C",
        "collection_strategy": "종로문화재단/문화포털 전시 안내 기준. 공식 페이지가 늦게 갱신되는 경우 문화포털 보조 출처를 함께 사용.",
        "events": [
            {
                "content_type": "전시",
                "title": "만고상청萬古常靑: 군자의 품격",
                "start_date": "2025-09-05",
                "end_date": "2026-12-27",
                "location": "종로구립 고희동미술관",
                "price": "무료",
                "description": "고희동미술관 재개관 6주년 기념전. 사계화조와 군자의 품격을 주제로 한 장기 전시.",
                "keywords": "한국미술;회화;작가미술관;무료;장기전시",
                "source_url": "https://www.culture.go.kr/portal/cltInfo/oneCltInfo/oneCltInfoView.do?menuNo=200010&pblprfrSn=366684",
            }
        ],
    },
    {
        "name": "은평역사한옥박물관",
        "tier": "C",
        "collection_strategy": "은평역사한옥박물관 공식 홈페이지와 서울관광재단 전시실 소개 기준.",
        "events": [
            {
                "content_type": "전시",
                "title": "은평역사한옥박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "은평역사한옥박물관",
                "price": None,
                "description": "은평역사실과 한옥전시실을 중심으로 은평의 역사와 한옥 문화를 소개하는 상설전시.",
                "keywords": "역사;건축;한옥;생활사;상설전시",
                "source_url": "https://museum.ep.go.kr/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "서대문자연사박물관",
        "tier": "C",
        "collection_strategy": "서대문자연사박물관 공식 홈페이지와 정규 교육 소개 기준.",
        "events": [
            {
                "content_type": "전시",
                "title": "서대문자연사박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "서대문자연사박물관",
                "price": None,
                "description": "지구환경관, 생명진화관, 인간과 자연관을 중심으로 자연사를 시간 순서로 소개하는 공립 자연사박물관 상설전시.",
                "keywords": "자연사;과학;공룡;어린이;가족;상설전시",
                "source_url": "https://namu.sdm.go.kr/web/main/main",
                "status": "상설전시",
            },
            {
                "content_type": "교육",
                "title": "서대문자연사박물관 정규 프로그램",
                "start_date": None,
                "end_date": None,
                "location": "서대문자연사박물관",
                "price": None,
                "description": "박물관 교실, 박물관 투어, 가족과 함께하는 달보기, 과학강연 등 자연사 기반 정규 교육 프로그램.",
                "keywords": "교육;과학;자연사;어린이;가족",
                "source_url": "https://namu.sdm.go.kr/web/main/contents/education_introduction_regular_list",
                "status": "상설전시",
            },
        ],
    },
    {
        "name": "서소문성지 역사박물관",
        "tier": "C",
        "collection_strategy": "서소문성지 역사박물관 공식 특별전시 페이지와 서울문화포털 전시 정보 기준.",
        "events": [
            {
                "content_type": "전시",
                "title": "THE FACE: 마주하다",
                "start_date": "2026-06-06",
                "end_date": "2026-09-06",
                "location": "서소문성지 역사박물관 기획전시실",
                "price": None,
                "description": "한불수교 140주년 기념 특별기획전. 임직순, 정현, 홍순모의 구상 예술을 통해 얼굴과 인간 존재를 조명.",
                "keywords": "한국미술;조각;회화;해외문화;기획전시",
                "source_url": "https://www.seosomun.org/exhibit/list.do",
            }
        ],
    },
    {
        "name": "김중업건축박물관",
        "tier": "C",
        "collection_strategy": "안양문화예술재단 김중업건축박물관 공식 시설 안내 기준.",
        "events": [
            {
                "content_type": "전시",
                "title": "김중업건축박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "김중업건축박물관",
                "price": None,
                "description": "김중업 건축과 안양의 건축유산을 소개하는 상설전시 및 야외전시 공간.",
                "keywords": "건축;현대미술;지역사;상설전시",
                "source_url": "https://ayac.or.kr/museum/contents/view?contentsNo=52&menuLevel=2&menuNo=46",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "과천시 추사박물관",
        "tier": "C",
        "collection_strategy": "과천시 추사박물관 공식 홈페이지 상설전시 안내 기준.",
        "events": [
            {
                "content_type": "전시",
                "title": "추사박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "과천시 추사박물관",
                "price": None,
                "description": "추사 김정희의 생애와 학예, 후지츠카 기증실을 중심으로 구성된 상설전시.",
                "keywords": "한국미술;서예;역사;상설전시",
                "source_url": "https://www.gccity.go.kr/chusamuseum/main.do",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "양주시립회암사지박물관",
        "tier": "C",
        "collection_strategy": "양주시 회암사지박물관 공식 홈페이지와 경기문화재단 소개 기준.",
        "events": [
            {
                "content_type": "전시",
                "title": "회암사지박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "양주시립회암사지박물관",
                "price": "일반 2,000원",
                "description": "고려 말·조선 초 왕실사찰 회암사지의 역사와 유물을 소개하는 시립박물관 상설전시.",
                "keywords": "역사;불교미술;왕실;상설전시",
                "source_url": "https://www.yangju.go.kr/museum/index.do",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "인천개항박물관",
        "tier": "C",
        "collection_strategy": "인천중구문화재단 인천개항박물관 공식 시설 안내 기준.",
        "events": [
            {
                "content_type": "전시",
                "title": "인천개항박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "인천개항박물관",
                "price": None,
                "description": "1883년 개항 이후 근대 인천의 역사와 문물을 소개하는 상설전시.",
                "keywords": "근현대사;개항;인천;상설전시",
                "source_url": "https://ijcf.or.kr/main/space/museum2.jsp",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "인천개항장 근대건축전시관",
        "tier": "C",
        "collection_strategy": "인천 중구 문화관광 공식 시설 안내 기준.",
        "events": [
            {
                "content_type": "전시",
                "title": "인천개항장 근대건축전시관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "인천개항장 근대건축전시관",
                "price": None,
                "description": "개항장 일대 근대건축물과 조계지 풍경, 근대 초기 건축 문화를 소개하는 상설전시.",
                "keywords": "근현대사;건축;인천;상설전시",
                "source_url": "https://www.icjg.go.kr/tour/cttu0101a03",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "대불호텔전시관",
        "tier": "C",
        "collection_strategy": "인천중구문화재단 대불호텔전시관 공식 시설 안내 기준.",
        "events": [
            {
                "content_type": "전시",
                "title": "대불호텔전시관·중구생활사전시관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "대불호텔전시관",
                "price": None,
                "description": "우리나라 최초의 서양식 호텔로 알려진 대불호텔의 역사와 인천 중구 생활사를 소개하는 상설전시.",
                "keywords": "근현대사;생활사;인천;상설전시",
                "source_url": "https://ijcf.or.kr/main/space/museum6.jsp",
                "status": "상설전시",
            }
        ],
    },
]


def build_report(results):
    lines = [
        "# 소규모/구립 박물관·미술관 보강 리포트",
        "",
        f"- 확인 기관: {len(SMALL_LOCAL_SOURCES)}개",
        f"- 반영 일정: {len(results)}건",
        f"- 신규: {sum(1 for item in results if item['result'] == 'inserted')}건",
        f"- 갱신: {sum(1 for item in results if item['result'] == 'updated')}건",
        "",
        "## 반영 일정",
        "",
    ]
    for item in results:
        lines.append(f"- {item['institution']} - {item['title']} ({item['status']})")
        lines.append(f"  - 출처: {item['source_url']}")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    metadata = load_metadata()
    missing = [item["name"] for item in SMALL_LOCAL_SOURCES if item["name"] not in metadata]
    if missing:
        raise RuntimeError(f"후보 목록에 없는 기관: {', '.join(missing)}")
    results = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_tables(conn)
        for source in SMALL_LOCAL_SOURCES:
            row_meta = metadata[source["name"]]
            source["region"] = row_meta.get("region")
            institution_id = get_institution_id(conn, source, row_meta)
            for event in source["events"]:
                results.append(upsert_event(conn, institution_id, source, event))
        conn.commit()
    build_report(results)
    print(f"checked={len(SMALL_LOCAL_SOURCES)}")
    print(f"events={len(results)}")
    print(f"inserted={sum(1 for item in results if item['result'] == 'inserted')}")
    print(f"updated={sum(1 for item in results if item['result'] == 'updated')}")
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
