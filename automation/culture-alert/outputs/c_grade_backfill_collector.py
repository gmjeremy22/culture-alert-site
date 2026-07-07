import csv
import sqlite3
from pathlib import Path

from a_grade_backfill_collector import (
    DB_PATH,
    clean_text,
    discover_image,
    ensure_tables,
    event_nature,
    infer_status,
)


BASE_DIR = Path(__file__).resolve().parent
REPORT_PATH = BASE_DIR / "c-grade-backfill-report.md"
INSTITUTION_CSV = BASE_DIR / "expanded-institution-candidates.csv"


C_GRADE_SOURCES = [
    {
        "name": "대림미술관",
        "tier": "A",
        "collection_strategy": "대림미술관/디뮤지엄 통합 공식 전시 페이지 기준. 대림미술관 본관은 전시 준비 중으로 보이고, 같은 대림문화재단의 현재 진행 전시를 우선 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "취향가옥 2: Art in Life, Life in Art 2",
                "start_date": "2025-06-28",
                "end_date": "2026-09-20",
                "location": "디뮤지엄",
                "price": None,
                "description": "대림문화재단 공식 현재 전시. 일상과 취향, 디자인/라이프스타일을 다루는 대중형 전시로 카드에는 실제 장소를 디뮤지엄으로 표시.",
                "keywords": "현대미술;디자인;라이프스타일;대형전시",
                "source_url": "https://www.daelimmuseum.org/exhibition/current",
            }
        ],
    },
    {
        "name": "경희궁",
        "tier": "C",
        "collection_strategy": "서울역사박물관 권역 문화유산. 전시형 행사보다는 상설 관람 정보로 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "경희궁 상설 관람",
                "start_date": None,
                "end_date": None,
                "location": "경희궁",
                "price": "무료",
                "description": "서울 5대 궁궐 중 하나인 경희궁의 숭정전 권역과 궁궐 유적을 상설 관람하는 항목.",
                "keywords": "역사;건축;서울;상설전시;무료",
                "source_url": "https://museum.seoul.go.kr/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "이화여자대학교박물관",
        "tier": "C",
        "collection_strategy": "공식 현재전시 페이지 기준. 140주년 특별전과 장기 기획전을 우선 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "진, 선, 미, 이화 140년 : 기억에서 미래로",
                "start_date": "2026-05-11",
                "end_date": "2026-12-31",
                "location": "이화여자대학교박물관",
                "price": None,
                "description": "이화 창립 140주년을 기념해 대학과 여성교육, 수집과 전시의 역사를 조명하는 특별전.",
                "keywords": "역사;여성사;대학박물관;기획전시",
                "source_url": "https://museum.ewha.ac.kr/museum/exhibition/exhibition.do",
            },
            {
                "content_type": "전시",
                "title": "포袍, 예를 갖추다",
                "start_date": "2026-04-20",
                "end_date": "2026-12-31",
                "location": "이화여자대학교박물관 지하 1층 장부덕기념실",
                "price": None,
                "description": "예복과 의례, 복식문화를 다루는 장기 전시.",
                "keywords": "복식;공예;한국미술;역사;장기전시",
                "source_url": "https://museum.ewha.ac.kr/museum/exhibition/exhibition.do",
            },
        ],
    },
    {
        "name": "이화여자대학교 자연사박물관",
        "tier": "C",
        "collection_strategy": "공식 자연사박물관 기획전시 공지 기준. 2026년 진행 중인 먹이사슬 주제전을 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "먹이, 생명을 잇다",
                "start_date": "2025-12-29",
                "end_date": "2026-10-30",
                "location": "이화여자대학교 자연사박물관",
                "price": None,
                "description": "생태계 속 먹이 관계와 생명 연결성을 다루는 자연사 기획전.",
                "keywords": "자연사;생태;과학;어린이;가족;장기전시",
                "source_url": "https://nhm.ewha.ac.kr/",
            }
        ],
    },
    {
        "name": "연세대학교박물관",
        "tier": "C",
        "collection_strategy": "공식 박물관 현재전시/공지 기준. 2026 한글 주제 특별전을 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "우리말, 한글, 연세얼",
                "start_date": "2026-05-15",
                "end_date": "2026-09-30",
                "location": "연세대학교박물관",
                "price": None,
                "description": "연세의 한글 연구와 우리말 교육의 흐름을 조명하는 특별전 1차 기간.",
                "keywords": "한글;문학;대학박물관;역사;기획전시",
                "source_url": "https://museum.yonsei.ac.kr/",
            }
        ],
    },
    {
        "name": "고려대학교박물관",
        "tier": "C",
        "collection_strategy": "공식 박물관 전시 안내 기준. 현재 확인 가능한 상설전시를 우선 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "고려대학교박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "고려대학교박물관",
                "price": None,
                "description": "고려대학교박물관의 소장 문화재와 대학사 자료를 중심으로 한 상설전시.",
                "keywords": "대학박물관;역사;한국미술;상설전시",
                "source_url": "https://museum.korea.ac.kr/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "숙명여자대학교박물관",
        "tier": "C",
        "collection_strategy": "공식 박물관 전시 공지 기준. 2026년 장기 특별전을 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "대한제국이 꿈꾸는 미래",
                "start_date": "2026-05-07",
                "end_date": "2026-12-30",
                "location": "숙명여자대학교박물관",
                "price": None,
                "description": "대한제국과 근대 전환기의 역사, 여성교육의 맥락을 함께 볼 수 있는 대학박물관 특별전.",
                "keywords": "근현대사;여성사;대학박물관;기획전시;장기전시",
                "source_url": "https://museum.sookmyung.ac.kr/",
            }
        ],
    },
    {
        "name": "서울교육박물관",
        "tier": "C",
        "collection_strategy": "공식 박물관 전시실 안내 기준. 교육사 상설전시로 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "우리나라 교육의 변천사",
                "start_date": None,
                "end_date": None,
                "location": "서울교육박물관",
                "price": None,
                "description": "개화기부터 현대까지 한국 교육의 흐름을 보여주는 교육사 상설전시.",
                "keywords": "교육;역사;서울;상설전시",
                "source_url": "https://edumuseum.sen.go.kr/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "경찰박물관",
        "tier": "C",
        "collection_strategy": "공식 박물관 전시 안내 기준. 경찰 역사와 과학수사 체험 성격의 상설전시로 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "국립경찰박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "국립경찰박물관",
                "price": "무료",
                "description": "경찰의 역사, 치안, 과학수사와 시민 안전을 다루는 상설전시.",
                "keywords": "역사;체험;어린이;가족;상설전시;무료",
                "source_url": "https://www.policemuseum.go.kr/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "우표박물관",
        "tier": "C",
        "collection_strategy": "공식 박물관 전시 안내 기준. 우정 역사와 우표 체험 상설전시로 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "우표박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "우표박물관",
                "price": "무료",
                "description": "우표와 우정 역사를 소개하고 우표 문화를 체험하는 상설전시.",
                "keywords": "역사;디자인;체험;어린이;가족;상설전시;무료",
                "source_url": "https://stampmuseum.kr/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "한국은행 화폐박물관",
        "tier": "C",
        "collection_strategy": "한국은행 화폐박물관 전시 공지 기준. 2026년 특별전과 상설전시를 함께 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "일상, 머금다 - 겹쳐진 풍경들",
                "start_date": "2026-03-31",
                "end_date": "2026-09-27",
                "location": "한국은행 화폐박물관",
                "price": "무료",
                "description": "한국은행 화폐박물관에서 진행 중인 2026년 특별전.",
                "keywords": "화폐;경제;근현대사;무료;기획전시",
                "source_url": "https://www.bok.or.kr/museum/",
            },
            {
                "content_type": "전시",
                "title": "한국은행 화폐박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "한국은행 화폐박물관",
                "price": "무료",
                "description": "화폐의 역사와 한국은행, 통화정책을 소개하는 상설전시.",
                "keywords": "화폐;경제;역사;상설전시;무료",
                "source_url": "https://www.bok.or.kr/museum/",
                "status": "상설전시",
            },
        ],
    },
    {
        "name": "농업박물관",
        "tier": "C",
        "collection_strategy": "공식 박물관 전시 안내 기준. 농업 역사와 농경문화 상설전시로 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "농업박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "농업박물관",
                "price": "무료",
                "description": "농업 역사, 농경문화, 쌀과 식생활 문화를 다루는 상설전시.",
                "keywords": "역사;생활사;농업;어린이;가족;상설전시;무료",
                "source_url": "https://www.agrimuseum.or.kr/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "모란미술관",
        "tier": "C",
        "collection_strategy": "공식 홈페이지 현재전시 기준. 2026년 여름 진행 전시를 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "상, 상 이상: 모란조각대상의 작가들",
                "start_date": "2026-04-28",
                "end_date": "2026-07-26",
                "location": "모란미술관",
                "price": None,
                "description": "모란조각대상 작가들을 조명하는 조각/현대미술 전시.",
                "keywords": "현대미술;조각;기획전시",
                "source_url": "https://www.moranmuseum.org/",
            }
        ],
    },
    {
        "name": "CICA 미술관",
        "tier": "C",
        "collection_strategy": "CICA 공식 Exhibitions 페이지 기준. 짧은 회차 전시가 많아 현재 날짜와 겹치는 회차를 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "Changhee Chun Solo Exhibition",
                "start_date": "2026-06-24",
                "end_date": "2026-06-28",
                "location": "CICA Museum 3-A Gallery",
                "price": None,
                "description": "CICA 미술관의 단기 개인전.",
                "keywords": "현대미술;미디어아트;해외문화;기획전시",
                "source_url": "https://cicamuseum.com/exhibitions/",
            },
            {
                "content_type": "전시",
                "title": "CICA New Media Art Conference 2026",
                "start_date": "2026-06-27",
                "end_date": "2026-06-29",
                "location": "CICA Museum",
                "price": None,
                "description": "뉴미디어아트 콘퍼런스와 연계 전시. Group B 전시는 2026-06-24 ~ 2026-06-28 진행.",
                "keywords": "미디어아트;현대미술;국제;강연;기획전시",
                "source_url": "https://cicamuseum.com/cica-new-media-art-conference-2026/",
            },
        ],
    },
    {
        "name": "아트센터 화이트블럭",
        "tier": "C",
        "collection_strategy": "공식/전시 안내 검색 기준. 2026년 5~6월 진행 전시를 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "Frame of Poem 보이는 시",
                "start_date": "2026-05-16",
                "end_date": "2026-06-28",
                "location": "아트센터 화이트블럭",
                "price": None,
                "description": "시와 이미지의 관계를 다루는 현대미술 전시.",
                "keywords": "현대미술;문학;기획전시",
                "source_url": "https://whiteblock.org/",
            }
        ],
    },
    {
        "name": "남양주시립박물관",
        "tier": "C",
        "collection_strategy": "남양주시청 시립박물관 현재전시 페이지 기준. 장기 실감영상 전시를 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "남양주 미학, 곡운구곡을 품다",
                "start_date": "2023-03-13",
                "end_date": "2026-12-31",
                "location": "남양주시립박물관 실감영상실",
                "price": "무료",
                "description": "곡운구곡첩을 주제로 남양주 고전 미학과 자연관을 실감 콘텐츠로 소개하는 특별기획전.",
                "keywords": "역사;한국미술;미디어아트;무료;장기전시",
                "source_url": "https://www.nyj.go.kr/museum/viewTnResrceU.do?key=726&resrceNo=729&sc10=INGW&si1=23&si2=34",
            }
        ],
    },
    {
        "name": "용인시박물관",
        "tier": "C",
        "collection_strategy": "용인시박물관 공식 기획전시 공지와 상설전시 안내 기준.",
        "events": [
            {
                "content_type": "전시",
                "title": "함께 킥오프 : 우리들의 축구 도시 용인",
                "start_date": "2026-03-20",
                "end_date": "2026-12-06",
                "location": "용인시박물관 기획전시실",
                "price": None,
                "description": "축구와 용인 지역 문화를 연결해 소개하는 2026년 기획전.",
                "keywords": "역사;스포츠;지역사;어린이;가족;장기전시",
                "source_url": "https://www.yongin.go.kr/museum/index.do",
            },
            {
                "content_type": "전시",
                "title": "용인시박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "용인시박물관",
                "price": "무료",
                "description": "선사시대부터 근현대까지 용인의 역사와 문화를 소개하는 상설전시.",
                "keywords": "역사;지역사;상설전시;무료",
                "source_url": "https://www.yongin.go.kr/museum/museumDisplay/museumPermanent.jsp",
                "status": "상설전시",
            },
        ],
    },
    {
        "name": "안산산업역사박물관",
        "tier": "C",
        "collection_strategy": "안산산업역사박물관 공식 상설전시 페이지 기준. 종료된 기획전은 제외하고 상설전시를 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "안산산업역사박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "안산산업역사박물관",
                "price": None,
                "description": "산업과 도시, 산업과 기술, 산업과 일상을 주제로 안산의 현대 산업사를 소개하는 상설전시.",
                "keywords": "근현대사;산업;지역사;상설전시",
                "source_url": "https://ansan.go.kr/aim/page/d2d01.do",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "안양박물관",
        "tier": "C",
        "collection_strategy": "안양문화예술재단 공식 전시일정 기준. 상설전시를 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "돌아온 역사, 안양",
                "start_date": "2021-11-30",
                "end_date": None,
                "location": "안양박물관 2층 상설전시실",
                "price": "무료",
                "description": "선사시대부터 근현대까지 안양의 역사와 문화를 보여주는 상설전시.",
                "keywords": "역사;지역사;상설전시;무료",
                "source_url": "https://ayac.or.kr/museum/ayac/performance/read?currentDate=1&menuLevel=&menuNo=55&month=11&museumType=&performanceNo=2610&performanceType=&year=2021",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "안양파빌리온",
        "tier": "C",
        "collection_strategy": "안양문화예술재단 공식 공연/전시 페이지 기준. APAP 아카이브 상설전시와 투어를 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "APAP 아카이브 상설전시",
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "location": "안양파빌리온",
                "price": "무료",
                "description": "안양공공예술프로젝트(APAP)의 역사와 기록, 공공예술 자료를 보여주는 상설전시.",
                "keywords": "현대미술;공공예술;건축;무료;장기전시",
                "source_url": "https://ayac.or.kr/base/ayac/performance/read?menuLevel=2&menuNo=1&performanceNo=2871",
            },
            {
                "content_type": "교육",
                "title": "2026 APAP 작품투어 - 안양예술공원",
                "start_date": "2026-03-10",
                "end_date": "2026-11-30",
                "location": "안양파빌리온",
                "price": "성인 3,000원 / 청소년 1,000원",
                "description": "3~11월 매주 화~일요일 10:30, 14:00에 운영되는 APAP 작품 해설 투어.",
                "keywords": "현대미술;공공예술;교육;해설;가족",
                "source_url": "https://ayac.or.kr/base/ayac/performance/imageList?menuLevel=3&menuNo=90&museumType=AP",
            },
        ],
    },
    {
        "name": "오산시립미술관",
        "tier": "C",
        "collection_strategy": "오산문화재단 공식 메인 현재전시 목록 기준. 진행 중인 기획전시를 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "동행",
                "start_date": "2026-04-21",
                "end_date": "2026-07-19",
                "location": "오산시립미술관 4층 소담홀",
                "price": "무료",
                "description": "오산문화재단 공식 현재전시 목록의 기획전시.",
                "keywords": "현대미술;기획전시;무료",
                "source_url": "https://www.osan.go.kr/arts/main.do",
            },
            {
                "content_type": "전시",
                "title": "오산시립미술관 특별기획 [구스타프 클림트 레플리카]展",
                "start_date": "2026-05-19",
                "end_date": "2026-08-23",
                "location": "오산시립미술관 제1전시실, 제2전시실, 제3전시실",
                "price": "무료",
                "description": "오산시립미술관의 구스타프 클림트 레플리카 특별기획전.",
                "keywords": "해외문화;현대미술;가족;무료;기획전시",
                "source_url": "https://www.osan.go.kr/arts/main.do",
            },
        ],
    },
    {
        "name": "김포아트빌리지 아트센터",
        "tier": "C",
        "collection_strategy": "김포문화재단 공식 메인 이달의 일정 기준. 김포아트빌리지 전시를 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "모두모두 어린이",
                "start_date": "2026-03-26",
                "end_date": "2026-06-28",
                "location": "김포아트빌리지",
                "price": None,
                "description": "김포문화재단 이달의 일정에 올라온 김포아트빌리지 기획전시.",
                "keywords": "어린이;가족;현대미술;기획전시",
                "source_url": "https://www.gcf.or.kr/main/main.do",
            }
        ],
    },
    {
        "name": "여주박물관",
        "tier": "C",
        "collection_strategy": "공식 박물관 전시 안내 기준. 대표 상설전시로 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "여주박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "여주박물관",
                "price": "무료",
                "description": "여주의 역사와 문화, 지역 유물을 소개하는 상설전시.",
                "keywords": "역사;지역사;상설전시;무료",
                "source_url": "https://www.yeoju.go.kr/museum/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "이천시립박물관",
        "tier": "C",
        "collection_strategy": "이천문화재단 공식 이천시립박물관 특별기획전시 목록 기준. 현재 전시를 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "2026 이천시립박물관 특별교류전 '이천+툰 유니버스'",
                "start_date": "2026-06-23",
                "end_date": "2026-07-26",
                "location": "이천시립박물관 2층 틈새전시실",
                "price": None,
                "description": "이천문화재단 공식 특별기획전시 목록의 현재 전시.",
                "keywords": "지역사;만화;어린이;가족;기획전시",
                "source_url": "https://www.artic.or.kr/icmus/board/list?boardManagementNo=29&menuLevel=2&menuNo=48",
            }
        ],
    },
    {
        "name": "이천시립월전미술관",
        "tier": "C",
        "collection_strategy": "월전미술관 공식 현재전시 페이지 기준. 진행 중인 상설전시를 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "[2026 상설전1] 화가의 공감: 월전이 그린 풍자화",
                "start_date": "2026-02-12",
                "end_date": "2026-07-26",
                "location": "이천시립월전미술관 5전시실",
                "price": None,
                "description": "월전 장우성의 풍자화를 다루는 2026년 상설전.",
                "keywords": "한국미술;회화;상설전시",
                "source_url": "https://www.iwoljeon.org/display/display.php",
            },
            {
                "content_type": "전시",
                "title": "몽유이천도: 한국화에 담은 아름다운 이천",
                "start_date": "2026-04-23",
                "end_date": "2026-07-26",
                "location": "이천시립월전미술관",
                "price": None,
                "description": "이천시 승격 30주년을 기념해 한국화 작가들이 이천의 풍경과 정체성을 풀어낸 특별기획전.",
                "keywords": "한국미술;지역사;기획전시",
                "source_url": "https://www.iwoljeon.org/display/display.php",
            },
        ],
    },
    {
        "name": "짜장면박물관",
        "tier": "C",
        "collection_strategy": "인천 중구 문화시설 공식 안내 기준. 짜장면 문화사 상설전시로 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "짜장면박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "짜장면박물관",
                "price": None,
                "description": "개항장과 차이나타운, 짜장면의 역사와 생활문화를 소개하는 상설전시.",
                "keywords": "생활사;음식문화;근현대사;상설전시",
                "source_url": "https://www.icjg.go.kr/museum/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "강화자연사박물관",
        "tier": "C",
        "collection_strategy": "강화군 시설관리공단/박물관 공식 안내 기준. 자연사 상설전시로 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "강화자연사박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "강화자연사박물관",
                "price": None,
                "description": "강화의 자연환경, 생물, 지질과 자연사를 소개하는 상설전시.",
                "keywords": "자연사;생태;과학;어린이;가족;상설전시",
                "source_url": "https://www.ghss.or.kr/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "소래역사관",
        "tier": "C",
        "collection_strategy": "남동문화재단 소래역사관 공식 시설 안내 기준. 네 개 상설전시 테마를 반영.",
        "events": [
            {
                "content_type": "전시",
                "title": "소래역사관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "소래역사관",
                "price": "일반 500원 / 청소년·군인 300원 / 어린이 200원",
                "description": "소래갯벌, 수인선, 소래염전, 소래포구를 테마로 소래 지역의 역사와 문화를 소개하는 상설전시.",
                "keywords": "생활사;지역사;근현대사;어린이;가족;상설전시",
                "source_url": "https://www.namdongcf.or.kr/user/contents.php?sq=73",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "부평역사박물관",
        "tier": "C",
        "collection_strategy": "부평역사박물관 공식 상설전시와 교육 일정 기준.",
        "events": [
            {
                "content_type": "전시",
                "title": "부평역사실",
                "start_date": None,
                "end_date": None,
                "location": "부평역사박물관",
                "price": None,
                "description": "부평의 역사와 지역 생활문화를 소개하는 상설전시.",
                "keywords": "역사;지역사;생활사;상설전시",
                "source_url": "https://portal.icbp.go.kr/bphm/exhibition/permanent_bp2021.asp",
                "status": "상설전시",
            },
            {
                "content_type": "교육",
                "title": "2026 상반기 어린이교육프로그램",
                "start_date": "2026-06-13",
                "end_date": "2026-06-20",
                "location": "부평역사박물관",
                "price": None,
                "description": "6월 13일 1~2학년, 6월 20일 3~4학년 대상 어린이교육프로그램.",
                "keywords": "교육;어린이;가족;주말;역사",
                "source_url": "https://portal.icbp.go.kr/bphm/",
                "occurrences": [
                    {"date": "2026-06-13", "label": "1~2학년 대상"},
                    {"date": "2026-06-20", "label": "3~4학년 대상"},
                ],
            },
        ],
    },
]


def load_metadata():
    metadata = {}
    with INSTITUTION_CSV.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            metadata[row["institution_name"]] = row
    return metadata


def get_institution_id(conn, source, metadata):
    name = source["name"]
    row = conn.execute("SELECT id FROM institutions WHERE name = ?", (name,)).fetchone()
    region = metadata.get("region") or source.get("region") or "확인필요"
    city = metadata.get("city") or source.get("city")
    category = metadata.get("category") or ("미술관" if "미술관" in name else "박물관")
    official_url = metadata.get("official_url")
    notes = metadata.get("notes")
    phase = "phase2-c-backfill" if source.get("tier") == "C" else "phase1-a-backfill"
    priority = 3 if source.get("tier") == "C" else 1
    if row:
        conn.execute(
            """
            UPDATE institutions
            SET region = COALESCE(?, region),
                city = COALESCE(?, city),
                category = COALESCE(?, category),
                priority = MIN(priority, ?),
                collection_phase = ?,
                exhibition_url = COALESCE(exhibition_url, ?),
                notes = COALESCE(notes, ?),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (region, city, category, priority, phase, official_url, notes, row[0]),
        )
        return row[0]
    cursor = conn.execute(
        """
        INSERT INTO institutions (
          name, region, city, category, priority, collection_phase,
          exhibition_url, notes, active
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (name, region, city, category, priority, phase, official_url, notes),
    )
    return cursor.lastrowid


def upsert_event(conn, institution_id, source, event):
    source_url = event["source_url"]
    image_url = event.get("image_url") or discover_image(source_url)
    status = infer_status(event.get("start_date"), event.get("end_date"), event.get("status"))
    nature = event_nature({**event, "status": status})
    tier = source.get("tier", "C")
    raw_text = (
        f"{tier}등급 보강 수집. 기관={source['name']}; 전략={source.get('collection_strategy', '')}; "
        f"원천={source_url}; 설명={event.get('description', '')}"
    )
    exists = conn.execute(
        """
        SELECT id FROM cultural_events
        WHERE institution_id = ? AND title = ? AND start_date IS ? AND source_url = ?
        """,
        (institution_id, event["title"], event.get("start_date"), source_url),
    ).fetchone()
    values = (
        event.get("content_type") or "전시",
        clean_text(event["title"]),
        event.get("start_date"),
        event.get("end_date"),
        event.get("location"),
        source.get("region"),
        event.get("price"),
        clean_text(event.get("description")),
        event.get("keywords"),
        source_url,
        status,
        raw_text,
        image_url,
        nature,
    )
    if exists:
        event_id = exists[0]
        conn.execute(
            """
            UPDATE cultural_events
            SET content_type = ?,
                title = ?,
                start_date = ?,
                end_date = ?,
                location = ?,
                region = ?,
                price = ?,
                description = ?,
                keywords = ?,
                source_url = ?,
                status = ?,
                raw_text = ?,
                image_url = ?,
                event_nature = ?,
                last_checked_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            values + (event_id,),
        )
        result = "updated"
    else:
        cursor = conn.execute(
            """
            INSERT INTO cultural_events (
              institution_id, content_type, title, start_date, end_date, location, region,
              price, description, keywords, source_url, status, raw_text, image_url, event_nature
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (institution_id,) + values,
        )
        event_id = cursor.lastrowid
        result = "inserted"
    conn.execute("DELETE FROM event_occurrences WHERE event_id = ?", (event_id,))
    for occurrence in event.get("occurrences", []):
        conn.execute(
            """
            INSERT INTO event_occurrences (
              event_id, occurrence_date, start_time, end_time, label, note, source_url, confidence
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                occurrence["date"],
                occurrence.get("start_time"),
                occurrence.get("end_time"),
                occurrence.get("label"),
                occurrence.get("note"),
                occurrence.get("source_url") or source_url,
                occurrence.get("confidence", 5),
            ),
        )
    return {
        "institution": source["name"],
        "title": event["title"],
        "result": result,
        "status": status,
        "source_url": source_url,
        "image_url": image_url,
        "tier": tier,
    }


def build_report(results, missing):
    by_result = {}
    by_tier = {}
    for item in results:
        by_result[item["result"]] = by_result.get(item["result"], 0) + 1
        by_tier[item["tier"]] = by_tier.get(item["tier"], 0) + 1
    lines = [
        "# C등급 및 대림미술관 보강 리포트",
        "",
        f"- 확인 기관: {len(C_GRADE_SOURCES)}개",
        f"- 반영 일정: {len(results)}건",
        f"- 신규: {by_result.get('inserted', 0)}건",
        f"- 갱신: {by_result.get('updated', 0)}건",
        f"- A등급 보강 일정: {by_tier.get('A', 0)}건",
        f"- C등급 보강 일정: {by_tier.get('C', 0)}건",
        f"- 아직 빈 기관: {len(missing)}개",
        "",
        "## 반영 일정",
        "",
    ]
    for item in results:
        lines.append(
            f"- [{item['tier']}] {item['institution']} - {item['title']} ({item['status']})"
        )
        lines.append(f"  - 출처: {item['source_url']}")
    if missing:
        lines.extend(["", "## 아직 빈 기관", ""])
        for item in missing:
            lines.append(f"- {item}")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def remaining_missing(conn):
    rows = []
    with INSTITUTION_CSV.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            if row["tier"] not in {"A", "C"}:
                continue
            count = conn.execute(
                """
                SELECT COUNT(*)
                FROM cultural_events e
                JOIN institutions i ON i.id = e.institution_id
                WHERE i.name = ?
                """,
                (row["institution_name"],),
            ).fetchone()[0]
            if count == 0:
                rows.append(f"{row['tier']} {row['institution_name']}")
    return rows


def main():
    metadata = load_metadata()
    missing_source_meta = [item["name"] for item in C_GRADE_SOURCES if item["name"] not in metadata]
    if missing_source_meta:
        raise RuntimeError(f"후보 목록에 없는 기관: {', '.join(missing_source_meta)}")
    results = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_tables(conn)
        for source in C_GRADE_SOURCES:
            row_meta = metadata[source["name"]]
            source["region"] = row_meta.get("region")
            institution_id = get_institution_id(conn, source, row_meta)
            for event in source["events"]:
                results.append(upsert_event(conn, institution_id, source, event))
        conn.commit()
        missing = remaining_missing(conn)
    build_report(results, missing)
    print(f"checked={len(C_GRADE_SOURCES)}")
    print(f"events={len(results)}")
    print(f"inserted={sum(1 for item in results if item['result'] == 'inserted')}")
    print(f"updated={sum(1 for item in results if item['result'] == 'updated')}")
    print(f"missing={len(missing)}")
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
