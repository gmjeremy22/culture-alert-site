import html
import re
import sqlite3
import ssl
import urllib.request
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

from culture_image_utils import clean_image_url, is_bad_image_url


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "culture-alert.sqlite"
REPORT_PATH = BASE_DIR / "a-grade-backfill-report.md"
TODAY = date.today()


A_GRADE_SOURCES = [
    {
        "name": "국립인천해양박물관",
        "region": "인천",
        "city": "중구",
        "collection_strategy": "전시: doc/ko/selectDocList.do 특별전시 목록. 교육: /ko/place/education/list.do 목록과 placeSeq 상세를 순회.",
        "events": [
            {
                "content_type": "전시",
                "title": "오디세이 - 그리스 신화 속 오디세우스의 대모험",
                "start_date": "2026-05-22",
                "end_date": "2026-10-11",
                "location": "국립인천해양박물관 4층 로비",
                "price": "무료",
                "description": "바다의 날 31주년 기념 테마전. 그리스 신화와 오디세우스의 바다 모험을 어린이 체험형 전시로 구성.",
                "keywords": "해양;그리스;신화;어린이;가족;체험;무료",
                "source_url": "https://www.inmm.or.kr/doc/ko/selectDoc.do?bbsSeq=143&docSeq=7221&menuSeq=3355",
            },
            {
                "content_type": "교육",
                "title": "I'M 바다예술가: 조기야 놀자!",
                "start_date": "2026-07-04",
                "end_date": "2026-08-08",
                "location": "국립인천해양박물관 교육 공간",
                "price": "무료",
                "description": "6, 7세 어린이 동반 가족 대상 해양 예술 교육. 신청 기간은 2026-06-04 ~ 2026-08-06.",
                "keywords": "해양;어린이;가족;교육;무료",
                "source_url": "https://www.inmm.or.kr/ko/place/education/view.do?menuSeq=3579&placeSeq=138",
                "occurrences": [
                    {"date": "2026-07-04", "label": "교육 시작"},
                    {"date": "2026-08-08", "label": "교육 종료"},
                ],
            },
            {
                "content_type": "교육",
                "title": "I'M 바다예술가: 본 적 없는 바다(두 번째 시간)",
                "start_date": "2026-07-11",
                "end_date": "2026-07-11",
                "location": "국립인천해양박물관 교육 공간",
                "price": "무료",
                "description": "초등 1-3학년 어린이 대상 해양 예술 교육. 신청 기간은 2026-06-04 ~ 2026-07-09.",
                "keywords": "해양;어린이;교육;무료;주말",
                "source_url": "https://www.inmm.or.kr/ko/place/education/view.do?menuSeq=3579&placeSeq=131",
                "occurrences": [{"date": "2026-07-11", "label": "교육일"}],
            },
            {
                "content_type": "교육",
                "title": "I'M 바다예술가: 본 적 없는 바다(세 번째 시간)",
                "start_date": "2026-07-18",
                "end_date": "2026-07-18",
                "location": "국립인천해양박물관 교육 공간",
                "price": "무료",
                "description": "초등 1-3학년 어린이 대상 해양 예술 교육. 신청 기간은 2026-06-04 ~ 2026-07-16.",
                "keywords": "해양;어린이;교육;무료;주말",
                "source_url": "https://www.inmm.or.kr/ko/place/education/view.do?menuSeq=3579&placeSeq=132",
                "occurrences": [{"date": "2026-07-18", "label": "교육일"}],
            },
        ],
    },
    {
        "name": "국립항공박물관",
        "region": "서울",
        "city": "강서구",
        "collection_strategy": "전시/교육 목록이 분리되어 있으면 목록 URL을 추가 조사. 현재는 공식 메인과 상설 전시관 정보를 기준으로 상설 항목 유지.",
        "events": [
            {
                "content_type": "전시",
                "title": "상설전시: 항공역사관·항공산업관·항공생활관",
                "start_date": None,
                "end_date": None,
                "location": "국립항공박물관",
                "price": None,
                "description": "항공역사관, 항공산업관, 항공생활관 등 상설 전시 중심. 2026-06-26 기준 별도 기간 한정 특별전은 확인되지 않음.",
                "keywords": "항공;과학;교통;상설전시;가족",
                "source_url": "https://www.aviation.or.kr/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "국립현대미술관 덕수궁관",
        "region": "서울",
        "city": "중구",
        "collection_strategy": "MMCA AjaxExhibitionList.do에서 exhPlaNm=덕수궁 필터. 방문안내 휴관/예정전시 문구도 보조 확인.",
        "events": [
            {
                "content_type": "전시",
                "title": "이대원",
                "start_date": "2026-08-06",
                "end_date": None,
                "location": "국립현대미술관 덕수궁관",
                "price": None,
                "description": "덕수궁관은 외벽 보존 공사와 다음 전시 준비로 2026-08-05까지 휴관하며, 다음 예정 전시 《이대원》은 2026-08-06 개막 예정.",
                "keywords": "한국근현대미술;회화;예정전시;덕수궁",
                "source_url": "https://www.mmca.go.kr/visitingInfo/deoksugungInfo.do",
                "status": "예정",
            }
        ],
    },
    {
        "name": "대림미술관",
        "region": "서울",
        "city": "종로구",
        "collection_strategy": "대림/디뮤지엄 통합 JS 사이트. detail URL 또는 내부 API를 찾아 수집기로 분리 필요.",
        "events": [],
        "note": "공식 메인 기준 대림미술관은 2026-06-26 현재 전시 준비 중으로 확인되어 카드용 이벤트는 넣지 않음.",
    },
    {
        "name": "디뮤지엄",
        "region": "서울",
        "city": "성동구",
        "collection_strategy": "대림/디뮤지엄 통합 JS 사이트. 검색 색인에 잡히는 current detail URL과 교육 목록을 우선 사용.",
        "events": [
            {
                "content_type": "전시",
                "title": "취향가옥 2: Art in Life, Life in Art 2",
                "start_date": "2025-06-28",
                "end_date": "2026-09-20",
                "location": "디뮤지엄",
                "price": None,
                "description": "작품과 컬렉션을 일상의 공간에서 만나는 아트 앤 라이프 전시.",
                "keywords": "현대미술;디자인;생활;공간;인테리어;가족",
                "source_url": "https://daelimmuseum.org/exhibition/current/PRG202506050001",
            },
            {
                "content_type": "교육",
                "title": "키즈워크룸: 시크릿 컬러 랩(개인)",
                "start_date": "2026-03-14",
                "end_date": "2026-09-20",
                "location": "디뮤지엄",
                "price": None,
                "description": "디뮤지엄 현재 전시와 연계되는 어린이 대상 교육 프로그램.",
                "keywords": "어린이;교육;체험;현대미술;색채",
                "source_url": "https://www.daelimmuseum.org/",
            },
        ],
    },
    {
        "name": "수원시립미술관",
        "region": "경기",
        "city": "수원시",
        "collection_strategy": "current_list.do에서 ge_idx를 수집하고 current_view.do 상세를 파싱. 미술관 지점명도 location으로 저장.",
        "events": [
            {
                "content_type": "전시",
                "title": "2026 소장품전《블랑 블랙 파노라마》",
                "start_date": "2026-02-12",
                "end_date": "2027-03-01",
                "location": "수원시립미술관 행궁 본관",
                "price": "관람안내 참조",
                "description": "흑과 백을 출발점으로 소장품을 통해 관계와 성찰의 태도를 새롭게 비추는 전시.",
                "keywords": "현대미술;소장품;회화;한국미술;장기전시",
                "source_url": "https://suma.suwon.go.kr/exhi/current_view.do?ge_idx=1258&lang=ko",
            },
            {
                "content_type": "전시",
                "title": "2026 기획전《입는 존재》",
                "start_date": "2026-03-19",
                "end_date": "2026-06-28",
                "location": "수원시립미술관 행궁 본관",
                "price": "관람안내 참조",
                "description": "옷을 통해 몸, 정체성, 산업, 사회적 시선을 살피는 수원시립미술관 기획전.",
                "keywords": "현대미술;정체성;패션;사회;여성;마감임박",
                "source_url": "https://suma.suwon.go.kr/exhi/current_view.do?ge_idx=1260&lang=ko",
            },
        ],
    },
    {
        "name": "아르코미술관",
        "region": "서울",
        "city": "종로구",
        "collection_strategy": "artcenter/board/list/507 현재전시 목록과 board/view 상세를 파싱. 부대행사 문장을 occurrence로 확장 가능.",
        "events": [
            {
                "content_type": "전시",
                "title": "어긋난 파동, 흔들리는 시간: 오민, 카밀 노먼트",
                "start_date": "2026-05-22",
                "end_date": "2026-07-19",
                "location": "아르코미술관 제1, 2전시실",
                "price": "무료",
                "description": "오민, 카밀 노먼트 참여. 소리, 시간, 파동, 퍼포먼스적 감각을 다루는 창작주체 연계 기획전.",
                "keywords": "현대미술;사운드;퍼포먼스;강연;무료",
                "source_url": "https://www.arko.or.kr/artcenter/board/view/506?bid=266&cid=717239",
                "occurrences": [
                    {"date": "2026-05-21", "start_time": "17:00", "label": "오프닝"},
                    {"date": "2026-05-21", "start_time": "18:00", "label": "카밀 노먼트 퍼포먼스"},
                    {"date": "2026-05-23", "start_time": "14:00", "label": "아티스트 토크, 오민 퍼포먼스"},
                    {"date": "2026-06-06", "start_time": "14:00", "label": "강연 및 대담"},
                ],
            }
        ],
    },
    {
        "name": "아모레퍼시픽미술관",
        "region": "서울",
        "city": "용산구",
        "collection_strategy": "APMA exhibition index에서 view.do 상세 링크를 수집. 상세의 제목/기간/본문/이미지를 파싱.",
        "events": [
            {
                "content_type": "전시",
                "title": "APMA, CHAPTER FIVE - FROM THE APMA COLLECTION",
                "start_date": "2026-04-01",
                "end_date": "2026-08-02",
                "location": "아모레퍼시픽미술관 1F 로비, B1 1-7전시실",
                "price": "성인 13,000원 등",
                "description": "아모레퍼시픽미술관 현대미술 소장품 특별전. 국내외 작가 40여 명, 회화·사진·조각·설치 등 약 80여 점을 선보임.",
                "keywords": "현대미술;소장품;사진;조각;설치;백남준",
                "source_url": "https://apma.amorepacific.com/contents/exhibition/3858007/view.do",
            }
        ],
    },
    {
        "name": "예술의전당 한가람디자인미술관",
        "region": "서울",
        "city": "서초구",
        "collection_strategy": "SAC schedule?tab=3 또는 show_view 상세에서 장소가 한가람디자인미술관인 전시만 필터링.",
        "events": [
            {
                "content_type": "전시",
                "title": "페르난도 보테로: 형태의 미학",
                "start_date": "2026-04-24",
                "end_date": "2026-08-30",
                "location": "한가람디자인미술관 제1전시실, 제2전시실, 제3전시실",
                "price": "일반 23,000원 등",
                "description": "콜롬비아 거장 페르난도 보테로의 조형 언어와 형태감을 조명하는 대규모 전시.",
                "keywords": "해외미술;회화;조각;라틴아메리카;가족",
                "source_url": "https://www.sac.or.kr/site/main/show/show_view?SN=76470",
            }
        ],
    },
    {
        "name": "예술의전당 한가람미술관",
        "region": "서울",
        "city": "서초구",
        "collection_strategy": "SAC schedule?tab=3 또는 show_view 상세에서 장소가 한가람미술관인 전시만 필터링.",
        "events": [
            {
                "content_type": "전시",
                "title": "스페인의 거장 고야: 이성이 잠들 때, 괴물이 깨어난다",
                "start_date": "2026-06-26",
                "end_date": "2026-09-30",
                "location": "한가람미술관 제7전시실",
                "price": "성인 20,000원 등",
                "description": "스페인 거장 고야를 중심으로 이성과 상상력, 사회비판적 이미지의 힘을 살피는 전시.",
                "keywords": "해외미술;판화;고야;스페인;주말;전시연계교육",
                "source_url": "https://www.sac.or.kr/site/main/show/show_view?SN=78392",
            }
        ],
    },
    {
        "name": "인천광역시립박물관",
        "region": "인천",
        "city": "연수구",
        "collection_strategy": "incheon.go.kr/museum 공지사항 전시 게시판에서 분류가 시립박물관 본관인 글만 선택.",
        "events": [
            {
                "content_type": "전시",
                "title": "창운 이열모 기증특별전: 어지러이 푸르른... 필묵의 귀환",
                "start_date": "2026-06-16",
                "end_date": "2026-07-12",
                "location": "인천시립박물관 2층 기획전시실",
                "price": "무료",
                "description": "한국화가 창운 이열모의 작고 10주기를 맞아 기증 회화작품과 유품을 소개하는 특별전.",
                "keywords": "한국화;회화;기증;인천;무료;마감임박",
                "source_url": "https://www.incheon.go.kr/museum/MU060103/3076017",
            }
        ],
    },
    {
        "name": "일민미술관",
        "region": "서울",
        "city": "종로구",
        "collection_strategy": "WordPress current exhibition 카드와 exhibition 상세 페이지를 파싱. venue가 해외인 협력전시는 수도권 추천에서 제외.",
        "events": [
            {
                "content_type": "전시",
                "title": "오프 더 화이트: 주름과 망루",
                "start_date": "2026-05-01",
                "end_date": "2026-07-12",
                "location": "일민미술관 1전시실",
                "price": None,
                "description": "건축 100주년을 맞은 일민미술관이 미술관이라는 장소의 조건과 감각을 탐색하는 릴레이 전시.",
                "keywords": "현대미술;건축;장소성;서울;마감임박",
                "source_url": "https://ilmin.org/exhibition/2026_off-the-white-1/",
            }
        ],
    },
    {
        "name": "전쟁기념관",
        "region": "서울",
        "city": "용산구",
        "collection_strategy": "공식 메인의 전시·행사 카드와 상세 링크를 추출. 프로그램/특강은 날짜가 지나면 자동 종료 처리 필요.",
        "events": [
            {
                "content_type": "행사",
                "title": "몰입형 VR 탐험",
                "start_date": "2026-03-17",
                "end_date": None,
                "location": "전쟁기념관",
                "price": None,
                "description": "전쟁기념관 공식 메인 전시·행사 영역에 2026-03-17 OPEN으로 게시된 몰입형 VR 체험.",
                "keywords": "역사;전쟁;VR;체험;가족",
                "source_url": "https://www.warmemo.or.kr/",
            }
        ],
    },
    {
        "name": "한성백제박물관",
        "region": "서울",
        "city": "송파구",
        "collection_strategy": "현재전시 모듈과 교육 ED 목록을 별도 파싱. 교육은 운영기간과 실제 회차를 event_occurrences로 확장.",
        "events": [
            {
                "content_type": "전시",
                "title": "2026 한성백제박물관 기증자료 특별전시회: 기록 & 역사 I - 백제 역사의 실마리, 한원",
                "start_date": "2026-06-02",
                "end_date": "2026-08-30",
                "location": "한성백제박물관 기획전시실",
                "price": "무료",
                "description": "7세기 동양의 백과사전적 문헌이자 고대 외교 지형의 핵심 사료인 『한원』을 중심으로 백제의 역사와 생활상을 조명.",
                "keywords": "역사;백제;고대사;문헌;무료",
                "source_url": "https://baekjemuseum.seoul.go.kr/m/module/index.jsp?boardid=a&code=DP&cpage=1&d_s_que=&mmode=content&mpid=SMM0203000000&pid=23315&strsearch=",
            },
            {
                "content_type": "교육",
                "title": "뮤지엄 휴휴프로그램7: 세계와 만나는 문화 살롱",
                "start_date": "2026-06-26",
                "end_date": "2026-06-26",
                "location": "서울백제어린이박물관",
                "price": None,
                "description": "한-프랑스 수교 140주년 연계. 안느 라발 작가와 함께하는 초등 1-2학년 대상 예술 체험 프로그램.",
                "keywords": "어린이;교육;프랑스;예술체험;주말",
                "source_url": "https://baekjemuseum.seoul.go.kr/dreamvillage/board/notice/index.jsp?boardid=SDM0401000000&cpage=1&mmode=content&mpid=SDM0401000000&pid=23340&skin=notice",
                "occurrences": [
                    {"date": "2026-06-26", "start_time": "17:00", "label": "교육 진행"}
                ],
            },
        ],
    },
    {
        "name": "호암미술관",
        "region": "경기",
        "city": "용인시",
        "collection_strategy": "leeumhoam.org/hoam/exhibition 현재/예정 목록. 상세 /hoam/exhibition/{id}를 파싱.",
        "events": [
            {
                "content_type": "전시",
                "title": "김윤신: 합이합일 분이분일",
                "start_date": "2026-03-17",
                "end_date": "2026-06-28",
                "location": "호암미술관 전시실 1, 2",
                "price": "전시예약, 멤버 무료 관람",
                "description": "한국 현대조각 1세대 여성 조각가 김윤신의 대규모 회고전.",
                "keywords": "한국현대미술;조각;여성작가;자연;마감임박",
                "source_url": "https://www.leeumhoam.org/hoam/exhibition/95",
            },
            {
                "content_type": "전시",
                "title": "아트스펙트럼 2026(가제)",
                "start_date": "2026-09-01",
                "end_date": "2026-12-27",
                "location": "호암미술관 전시실 1, 2",
                "price": None,
                "description": "호암미술관 예정 전시. 상세 정보는 공식 예정전시 페이지에서 추가 확인 필요.",
                "keywords": "현대미술;예정전시;청년작가",
                "source_url": "https://www.leeumhoam.org/hoam/exhibition?state=2",
                "status": "예정",
            },
        ],
    },
]


def parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def infer_status(start_date, end_date, explicit=None):
    if explicit:
        return explicit
    start = parse_date(start_date)
    end = parse_date(end_date)
    if end and end < TODAY:
        return "종료"
    if start and start > TODAY:
        return "예정"
    return "진행중"


def event_nature(event):
    if event.get("content_type") != "전시":
        return "program"
    if event.get("status") == "상설전시" or (not event.get("start_date") and not event.get("end_date")):
        return "permanent"
    start = parse_date(event.get("start_date"))
    end = parse_date(event.get("end_date"))
    if start and end and (end - start).days >= 180:
        return "long_term"
    if start or end:
        return "limited"
    return "unknown"


def clean_text(value):
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()


def ensure_tables(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS event_occurrences (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          event_id INTEGER NOT NULL REFERENCES cultural_events(id) ON DELETE CASCADE,
          occurrence_date TEXT NOT NULL,
          start_time TEXT,
          end_time TEXT,
          label TEXT,
          note TEXT,
          source_url TEXT,
          confidence INTEGER NOT NULL DEFAULT 5,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(event_id, occurrence_date, COALESCE(start_time, ''), COALESCE(label, ''))
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(cultural_events)").fetchall()}
    if "image_url" not in columns:
        conn.execute("ALTER TABLE cultural_events ADD COLUMN image_url TEXT")
    if "event_nature" not in columns:
        conn.execute("ALTER TABLE cultural_events ADD COLUMN event_nature TEXT NOT NULL DEFAULT 'unknown'")
    conn.commit()


def fetch_html(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 culture-alert-backfill/1.0",
            "Accept-Language": "ko,en;q=0.8",
        },
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=15, context=context) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def is_generic_image(image):
    return is_bad_image_url(image)


def discover_image(url):
    try:
        page = fetch_html(url)
    except Exception:
        return None
    meta_patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
    ]
    for pattern in meta_patterns:
        match = re.search(pattern, page, flags=re.I)
        if match:
            image = clean_image_url(match.group(1), base_url=url)
            if image:
                return image
    for match in re.finditer(r'<img[^>]+(?:src|data-src)=["\']([^"\']+)["\']', page, flags=re.I):
        image = clean_image_url(match.group(1), base_url=url)
        if image:
            return image
    return None


def get_institution_id(conn, source):
    row = conn.execute("SELECT id FROM institutions WHERE name = ?", (source["name"],)).fetchone()
    if row:
        conn.execute(
            """
            UPDATE institutions
            SET region = COALESCE(?, region),
                city = COALESCE(?, city),
                collection_phase = CASE
                  WHEN collection_phase IS NULL OR collection_phase = '' THEN 'phase1-a'
                  ELSE collection_phase
                END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (source.get("region"), source.get("city"), row[0]),
        )
        return row[0]
    cursor = conn.execute(
        """
        INSERT INTO institutions (name, region, city, category, priority, collection_phase, active)
        VALUES (?, ?, ?, ?, 1, 'phase1-a', 1)
        """,
        (
            source["name"],
            source.get("region") or "확인필요",
            source.get("city"),
            "미술관" if "미술관" in source["name"] else "박물관",
        ),
    )
    return cursor.lastrowid


def upsert_event(conn, institution_id, source, event):
    source_url = event["source_url"]
    image_url = event.get("image_url") or discover_image(source_url)
    status = infer_status(event.get("start_date"), event.get("end_date"), event.get("status"))
    nature = event_nature({**event, "status": status})
    raw_text = (
        f"A등급 보강 수집. 기관={source['name']}; 전략={source.get('collection_strategy', '')}; "
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
    conn.execute("DELETE FROM event_occurrences WHERE event_id = ?", (event_id,))
    for occurrence in event.get("occurrences", []):
        conn.execute(
            """
            INSERT OR REPLACE INTO event_occurrences (
              event_id, occurrence_date, start_time, end_time, label, note, source_url, confidence, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                event_id,
                occurrence["date"],
                occurrence.get("start_time"),
                occurrence.get("end_time"),
                occurrence.get("label"),
                occurrence.get("note"),
                source_url,
                occurrence.get("confidence", 8),
            ),
        )
    return "updated" if exists else "inserted", event_id, image_url


def build_report(results):
    inserted = sum(1 for item in results if item["result"] == "inserted")
    updated = sum(1 for item in results if item["result"] == "updated")
    checked = len(A_GRADE_SOURCES)
    with_events = len({item["institution"] for item in results})
    lines = [
        "# A등급 15개 기관 보강 수집 리포트",
        "",
        f"- 확인일: {TODAY.isoformat()}",
        f"- 확인 기관: {checked}개",
        f"- 카드용 일정이 들어간 기관: {with_events}개",
        f"- 신규 추가: {inserted}건",
        f"- 기존 갱신: {updated}건",
        "",
        "## 기관별 결과",
        "",
    ]
    by_institution = {}
    for item in results:
        by_institution.setdefault(item["institution"], []).append(item)
    for source in A_GRADE_SOURCES:
        name = source["name"]
        items = by_institution.get(name, [])
        lines.append(f"### {name}")
        lines.append("")
        lines.append(f"- 수집기화 메모: {source['collection_strategy']}")
        if source.get("note"):
            lines.append(f"- 확인 메모: {source['note']}")
        if not items:
            lines.append("- DB 반영: 현재 카드로 띄울 일정 없음")
        for item in items:
            period = f"{item['start_date'] or '상설/미정'} ~ {item['end_date'] or '미정'}"
            image_note = "이미지 있음" if item.get("image_url") else "이미지 미확인"
            lines.append(
                f"- {item['title']} ({item['content_type']}, {period}, {item['status']}, {image_note})"
            )
            lines.append(f"  - 링크: {item['source_url']}")
        lines.append("")
    lines.extend(
        [
            "## 다음 수집기 전환 우선순위",
            "",
            "1. SAC, 수원시립미술관, 한성백제박물관, 인천시립박물관: HTML 상세 구조가 비교적 일정해서 바로 기관별 수집기로 만들기 좋음.",
            "2. 호암/리움, MMCA: 기존 수집기와 비슷하게 JSON/API 기반으로 지점 분리 가능.",
            "3. 대림미술관/디뮤지엄: 사이트가 JS 앱이라 내부 API 또는 브라우저 기반 수집을 확인해야 함.",
            "4. 국립항공박물관, 전쟁기념관: 공식 메인에서는 요약만 안정적으로 보여서 상세 목록 URL 추가 탐색이 필요함.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main():
    results = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_tables(conn)
        for source in A_GRADE_SOURCES:
            institution_id = get_institution_id(conn, source)
            for event in source.get("events", []):
                result, event_id, image_url = upsert_event(conn, institution_id, source, event)
                results.append(
                    {
                        "institution": source["name"],
                        "event_id": event_id,
                        "result": result,
                        "content_type": event.get("content_type") or "전시",
                        "title": event["title"],
                        "start_date": event.get("start_date"),
                        "end_date": event.get("end_date"),
                        "status": infer_status(event.get("start_date"), event.get("end_date"), event.get("status")),
                        "source_url": event["source_url"],
                        "image_url": image_url,
                    }
                )
        conn.commit()
    build_report(results)
    print(f"checked={len(A_GRADE_SOURCES)}")
    print(f"events={len(results)}")
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
