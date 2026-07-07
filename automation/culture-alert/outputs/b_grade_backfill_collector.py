import csv
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

from a_grade_backfill_collector import (
    DB_PATH,
    clean_text,
    discover_image,
    ensure_tables,
    event_nature,
    infer_status,
    parse_date,
)


BASE_DIR = Path(__file__).resolve().parent
REPORT_PATH = BASE_DIR / "b-grade-backfill-report.md"
INSTITUTION_CSV = BASE_DIR / "expanded-institution-candidates.csv"
TODAY = date.today()


B_GRADE_SOURCES = [
    {
        "name": "SeMA 백남준기념관",
        "collection_strategy": "SeMA 전시 상세에서 분관명이 백남준기념관/백남준을 기억하는 집인 항목만 필터링. 전체 SeMA 현재전시 목록은 다른 분관 노이즈가 많아 장소 필터가 필수.",
        "events": [
            {
                "content_type": "전시",
                "title": "메가트론 랩소디",
                "start_date": "2025-06-17",
                "end_date": None,
                "location": "서울시립 백남준을 기억하는 집",
                "price": "무료",
                "description": "백남준의 대표작과 미디어아트 맥락을 소개하는 백남준기념관 상설 성격 전시.",
                "keywords": "백남준;미디어아트;현대미술;상설전시;무료",
                "source_url": "https://sema.seoul.go.kr/kr/whatson/exhibition/detail?exNo=1417927",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "서울생활사박물관",
        "collection_strategy": "서울역사박물관 계열 전시목록에서 venue=서울생활사박물관으로 필터. 상세 URL의 exhNo 파라미터를 저장.",
        "events": [
            {
                "content_type": "전시",
                "title": "대학에서 우리는: 서울학생 생활의 재발견",
                "start_date": "2026-05-15",
                "end_date": "2026-09-27",
                "location": "서울생활사박물관 기획전시실",
                "price": "무료",
                "description": "서울의 대학생활과 학생 문화, 생활사를 다루는 서울생활사박물관 기획전.",
                "keywords": "생활사;서울;대학;청년;역사;무료",
                "source_url": "https://museum.seoul.go.kr/www/board/NR_boardView.do?bbsCd=1012&seq=20260429110658721",
            }
        ],
    },
    {
        "name": "청계천박물관",
        "collection_strategy": "서울역사박물관 계열 current/special 목록에서 venue=청계천박물관을 필터. 교육은 museum.seoul.go.kr/education 계열 별도 확인.",
        "events": [
            {
                "content_type": "전시",
                "title": "청계천의 별이 된 노무라 모토유키",
                "start_date": "2026-06-13",
                "end_date": "2026-10-11",
                "location": "청계천박물관 기획전시실",
                "price": "무료",
                "description": "일제강점기 청계천 변 가옥을 기록한 노무라 모토유키 자료를 중심으로 청계천의 도시 생활사를 조명.",
                "keywords": "서울;청계천;도시사;근현대사;사진;무료",
                "source_url": "https://museum.seoul.go.kr/cgcm/board/NR_boardView.do?bbsCd=1020&seq=20260609152407475",
            }
        ],
    },
    {
        "name": "한양도성박물관",
        "collection_strategy": "서울역사박물관 계열 전시 목록에서 venue=한양도성박물관 필터. 시작 전 예정전시도 추천 후보로 유지.",
        "events": [
            {
                "content_type": "전시",
                "title": "여민공수與民共守",
                "start_date": "2026-07-14",
                "end_date": "2027-03-07",
                "location": "한양도성박물관 기획전시실",
                "price": "무료",
                "description": "백성과 함께 지킨 한양도성의 의미를 조명하는 한양도성박물관 예정 전시.",
                "keywords": "한양도성;조선;서울;역사;예정전시;무료",
                "source_url": "https://museum.seoul.go.kr/scwm/board/NR_boardView.do?bbsCd=1080&seq=20260623174312968",
            }
        ],
    },
    {
        "name": "몽촌역사관",
        "collection_strategy": "몽촌역사관/서울백제어린이박물관 계열은 baekjemuseum 도메인의 dreamvillage 게시판과 교육 목록을 별도 파싱. 실제 장소는 location에 명시.",
        "events": [
            {
                "content_type": "교육",
                "title": "2026 백제왕도 달빛기행",
                "start_date": "2026-06-12",
                "end_date": "2026-11-27",
                "location": "서울백제어린이박물관 및 몽촌토성 일대",
                "price": None,
                "description": "야간 백제왕도 답사형 프로그램. 회차별 운영일이 있으므로 자동화 시 세부 회차를 event_occurrences로 분리.",
                "keywords": "백제;역사;어린이;가족;답사;야간프로그램",
                "source_url": "https://baekjemuseum.seoul.go.kr/dreamvillage/board/notice/index.jsp?boardid=SDM0401000000&mmode=content&mpid=SDM0401000000",
            },
            {
                "content_type": "교육",
                "title": "상설체험프로그램 백제랑 나랑",
                "start_date": "2026-02-19",
                "end_date": "2026-12-31",
                "location": "서울백제어린이박물관",
                "price": None,
                "description": "유아·어린이 가족 대상 상설 체험 프로그램.",
                "keywords": "백제;어린이;가족;체험;상설교육",
                "source_url": "https://baekjemuseum.seoul.go.kr/dreamvillage/contents.jsp?mpid=SDM0201000000",
            },
        ],
    },
    {
        "name": "국립기상박물관",
        "collection_strategy": "science.kma.go.kr 하위 국립기상박물관 전시 안내를 정적 페이지로 수집. 특별전은 공지/전시 메뉴 추가 탐색 필요.",
        "events": [
            {
                "content_type": "전시",
                "title": "국립기상박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "국립기상박물관",
                "price": "무료",
                "description": "기상 관측 역사와 기상과학 자료를 다루는 상설 전시.",
                "keywords": "기상;과학;역사;상설전시;무료;가족",
                "source_url": "https://science.kma.go.kr/museum/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "서울우리소리박물관",
        "collection_strategy": "gomuseum.seoul.go.kr 전시 목록에서 현재전시 항목을 파싱. 서울시 사이트라 날짜/제목 구조가 비교적 안정적.",
        "events": [
            {
                "content_type": "전시",
                "title": "다시, 아리랑",
                "start_date": "2026-06-18",
                "end_date": "2027-05-30",
                "location": "서울우리소리박물관",
                "price": "무료",
                "description": "서울우리소리박물관의 아리랑 관련 현재 전시.",
                "keywords": "소리;민요;아리랑;음악;민속;무료",
                "source_url": "https://gomuseum.seoul.go.kr/",
            }
        ],
    },
    {
        "name": "돈의문박물관마을",
        "collection_strategy": "dmvillage.info는 접근이 불안정할 수 있어 메인/프로그램/전시 카드를 브라우저 기반 또는 RSS/공지형으로 수집하는 편이 좋음.",
        "events": [
            {
                "content_type": "전시",
                "title": "돈의문박물관마을 상설전시·마을 콘텐츠",
                "start_date": None,
                "end_date": None,
                "location": "돈의문박물관마을",
                "price": None,
                "description": "돈의문 일대 도시 기억과 생활문화 공간을 상설 전시·체험형으로 운영.",
                "keywords": "서울;도시사;생활문화;건축;상설전시;가족",
                "source_url": "https://dmvillage.info/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "금호미술관",
        "collection_strategy": "kumhomuseum.com 전시 페이지가 정적 HTML에 가깝지만 접속 실패가 있어 주기 수집 시 재시도와 타임아웃 필요.",
        "events": [
            {
                "content_type": "전시",
                "title": "2026 KUMHO MUSEUM OF ART",
                "start_date": "2026-06-25",
                "end_date": "2026-07-05",
                "location": "금호미술관 B1-3F",
                "price": None,
                "description": "금호미술관 전시 페이지에 게시된 2026년 현재 전시.",
                "keywords": "현대미술;기획전시;서울;마감임박",
                "source_url": "https://www.kumhomuseum.com/designer/skin/02/01.html",
            }
        ],
    },
    {
        "name": "성곡미술관",
        "collection_strategy": "공식 사이트와 공식 SNS를 함께 확인. 사이트가 수집기에 응답하지 않을 때 공식 SNS의 전시 공지로 보조 검증.",
        "events": [
            {
                "content_type": "전시",
                "title": "Paris Unseen 보이지 않는 파리",
                "start_date": "2026-04-02",
                "end_date": "2026-07-26",
                "location": "성곡미술관",
                "price": None,
                "description": "성곡미술관 현재 전시. 공식 SNS/전시 공지에서 확인한 일정.",
                "keywords": "사진;도시;파리;해외문화;현대미술",
                "source_url": "https://www.sungkokmuseum.org/",
            }
        ],
    },
    {
        "name": "환기미술관",
        "collection_strategy": "whankimuseum.org 전시 목록은 접속 실패가 있을 수 있어 메인과 current 카테고리를 재시도 수집. 휴관 공지도 함께 확인.",
        "events": [
            {
                "content_type": "전시",
                "title": "Collector Kim HyangAn",
                "start_date": "2026-04-02",
                "end_date": None,
                "location": "환기미술관",
                "price": None,
                "description": "환기재단 소장품과 김향안의 컬렉터적 시선을 다루는 현재 전시로 확인.",
                "keywords": "한국근현대미술;김환기;소장품;회화;아카이브",
                "source_url": "https://whankimuseum.org/now/",
            }
        ],
    },
    {
        "name": "사비나미술관",
        "collection_strategy": "savinamuseum.com 메인/전시 상세에서 현재전시 카드와 기간을 수집. 기획전과 온라인 프로젝트가 섞일 수 있어 장소 확인 필요.",
        "events": [
            {
                "content_type": "전시",
                "title": "고상우 개인전: Breathing with You, 너와 함께 쉬는 숨",
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "location": "사비나미술관",
                "price": None,
                "description": "사비나미술관 현재 전시/프로젝트로 확인되는 고상우 개인전.",
                "keywords": "현대미술;사진;생태;동물;색채;장기전시",
                "source_url": "https://www.savinamuseum.com/",
            }
        ],
    },
    {
        "name": "코리아나미술관 스페이스씨",
        "collection_strategy": "spacec.co.kr/gallery 현재전시 페이지는 전시 준비중 상태가 있을 수 있음. 미술관 전시와 화장박물관 상설전시를 분리 저장.",
        "events": [
            {
                "content_type": "전시",
                "title": "코리아나 화장박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "스페이스씨 코리아나 화장박물관",
                "price": None,
                "description": "화장 문화와 공예, 생활문화 자료를 다루는 코리아나 화장박물관 상설전.",
                "keywords": "공예;생활문화;화장문화;상설전시;강남",
                "source_url": "https://www.spacec.co.kr/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "호림박물관 신사분관",
        "collection_strategy": "horimmuseum.org/ko/exhibition?display=current에서 현재전시 카드 목록을 파싱. 장소가 신사분관인 항목만 사용.",
        "events": [
            {
                "content_type": "전시",
                "title": "미묘지색微妙之色: 고려백자와 조선청자",
                "start_date": "2026-03-05",
                "end_date": "2026-07-31",
                "location": "호림박물관 신사분관 제1, 2전시실",
                "price": None,
                "description": "고려백자와 조선청자를 중심으로 미묘한 색과 질감을 조명하는 전시.",
                "keywords": "고미술;도자;고려;조선;공예",
                "source_url": "https://www.horimmuseum.org/ko/exhibition/698e7393f164572d0ed47aea",
            },
            {
                "content_type": "전시",
                "title": "금상첨화錦上添花: 비단 위에 더해진 봄꽃",
                "start_date": "2026-03-05",
                "end_date": "2026-07-31",
                "location": "호림박물관 신사분관",
                "price": None,
                "description": "비단과 꽃 문양, 장식미를 중심으로 보는 호림박물관 신사분관 현재 전시.",
                "keywords": "고미술;공예;섬유;문양;봄꽃",
                "source_url": "https://www.horimmuseum.org/ko/exhibition/698e7456f164572d0ed47af3",
            },
        ],
    },
    {
        "name": "뮤지엄한미 삼청",
        "collection_strategy": "museumhanmi.or.kr/exhibition과 program 목록을 파싱. 삼청/삼청별관/김포가 섞이므로 item venue 필터 필요.",
        "events": [
            {
                "content_type": "전시",
                "title": "모든 순간이 꽃봉오리인 것을: 육명심·홍순태·한정식·박영숙",
                "start_date": "2026-03-27",
                "end_date": "2026-07-19",
                "location": "뮤지엄한미 삼청",
                "price": None,
                "description": "한국 사진사의 주요 작가들을 조명하는 뮤지엄한미 삼청 현재 전시.",
                "keywords": "사진;한국사진;근현대;아카이브;마감임박",
                "source_url": "https://museumhanmi.or.kr/exhibition/",
            },
            {
                "content_type": "강연",
                "title": "나를 찍기 위한 방",
                "start_date": "2026-06-27",
                "end_date": "2026-06-27",
                "location": "뮤지엄한미 삼청별관",
                "price": None,
                "description": "뮤지엄한미 프로그램 목록에 게시된 사진 관련 프로그램.",
                "keywords": "사진;강연;체험;주말",
                "source_url": "https://museumhanmi.or.kr/program/",
                "occurrences": [{"date": "2026-06-27", "label": "프로그램 진행"}],
            },
        ],
    },
    {
        "name": "서울대학교미술관",
        "collection_strategy": "snumoa.org 전시 상세는 접속이 불안정해 검색 색인/공식 페이지를 병행. 현재전시와 휴관 공지를 함께 확인.",
        "events": [
            {
                "content_type": "전시",
                "title": "안과 밖: 물질과 개념의 길항",
                "start_date": "2026-04-17",
                "end_date": "2026-06-28",
                "location": "서울대학교미술관",
                "price": None,
                "description": "서울대학교미술관 개관 20주년 기념전.",
                "keywords": "현대미술;개념미술;물질;대학미술관;마감임박",
                "source_url": "https://www.snumoa.org/",
            }
        ],
    },
    {
        "name": "실학박물관",
        "collection_strategy": "GGCF 계열 exhibitions/edus JSON형 HTML 목록. 기관명/태그가 안정적이라 기존 수집기를 확장하기 좋음.",
        "events": [
            {
                "content_type": "전시",
                "title": "이십사二十四: 하늘을 읽어 땅을 살리다",
                "start_date": "2026-05-12",
                "end_date": "2026-10-18",
                "location": "실학박물관 1층 기획전시실",
                "price": None,
                "description": "24절기와 과학문화재를 실학의 관점에서 조명하는 기획전.",
                "keywords": "실학;과학;절기;역사;경기",
                "source_url": "https://silhak.ggcf.kr/exhibitions",
            },
            {
                "content_type": "전시",
                "title": "실감콘텐츠 체험전: 조선의 하늘과 땅",
                "start_date": "2023-09-12",
                "end_date": None,
                "location": "실학박물관",
                "price": None,
                "description": "과학문화재를 소재로 한 실감콘텐츠 체험 전시.",
                "keywords": "실학;과학;실감콘텐츠;가족;상설전시",
                "source_url": "https://silhak.ggcf.kr/exhibitions",
            },
        ],
    },
    {
        "name": "전곡선사박물관",
        "collection_strategy": "GGCF 계열 exhibitions/edus/events 목록 파싱. 온라인전시와 현장전시를 event_nature로 구분.",
        "events": [
            {
                "content_type": "전시",
                "title": "전곡선사박물관 개관15주년 기념전: 땅속의 땅, 전곡",
                "start_date": "2026-05-02",
                "end_date": "2026-11-01",
                "location": "전곡선사박물관 B1 기획전시실",
                "price": None,
                "description": "전곡리 유적과 출토 석기를 중심으로 한 개관 15주년 기념전.",
                "keywords": "선사;고고학;구석기;경기;가족",
                "source_url": "https://jgpm.ggcf.kr/exhibitions/112",
            },
            {
                "content_type": "교육",
                "title": "석기에 담긴 기후 이야기",
                "start_date": "2026-06-23",
                "end_date": "2026-07-25",
                "location": "전곡선사박물관",
                "price": None,
                "description": "6-7월 주말교육으로 확인되는 선사·기후 주제 교육.",
                "keywords": "선사;고고학;기후;어린이;주말;교육",
                "source_url": "https://jgpm.ggcf.kr/edus",
            },
        ],
    },
    {
        "name": "경기도어린이박물관",
        "collection_strategy": "gcm.ggcf.kr의 exhibitions와 edus를 분리 수집. 어린이 프로그램은 실제 회차와 운영기간을 구분해야 함.",
        "events": [
            {
                "content_type": "교육",
                "title": "전시연계 교육: 모두의 식탁",
                "start_date": "2026-05-27",
                "end_date": "2026-12-31",
                "location": "경기도어린이박물관 3층 우리는 지구별 친구들 전시실 내 모두의 식탁",
                "price": "무료",
                "description": "5세 이상 어린이와 보호자 대상 전시 연계 상설 자율 체험.",
                "keywords": "어린이;가족;교육;체험;무료;환경",
                "source_url": "https://gcm.ggcf.kr/edus",
            },
            {
                "content_type": "교육",
                "title": "주말·공휴일 상설: 모두의 식탁",
                "start_date": "2026-05-24",
                "end_date": "2026-07-26",
                "location": "경기도어린이박물관 3층 우리는 지구별 친구들 전시실 내 모두의 식탁",
                "price": "무료",
                "description": "주말·공휴일에 운영되는 전시 연계 체험 프로그램.",
                "keywords": "어린이;가족;주말;교육;체험;무료",
                "source_url": "https://gcm.ggcf.kr/edus",
            },
        ],
    },
    {
        "name": "수원박물관",
        "collection_strategy": "swmuseum과 통합 museum.suwon.go.kr 교육 예약 페이지를 함께 수집. 수원박물관/화성박물관/광교박물관이 섞이므로 museumCd 필터 필수.",
        "events": [
            {
                "content_type": "교육",
                "title": "수원박물관 어린이 주말교육: 도란도란 민화교실",
                "start_date": "2026-07-11",
                "end_date": "2026-07-25",
                "location": "수원박물관",
                "price": None,
                "description": "수원박물관 어린이 주말교육. 7월 11일, 25일 회차 운영.",
                "keywords": "어린이;민화;교육;주말;수원",
                "source_url": "https://swmuseum.suwon.go.kr/",
                "occurrences": [
                    {"date": "2026-07-11", "start_time": "13:00", "end_time": "15:00", "label": "1회차"},
                    {"date": "2026-07-25", "start_time": "13:00", "end_time": "15:00", "label": "2회차"},
                ],
            }
        ],
    },
    {
        "name": "수원화성박물관",
        "collection_strategy": "hsmuseum 메인 교육신청 카드와 통합 예약 상세를 수집. 같은 교육이 시간대별로 나뉘므로 occurrence로 분리.",
        "events": [
            {
                "content_type": "교육",
                "title": "원리로 이해하는 수원화성 축성(7/11)",
                "start_date": "2026-07-11",
                "end_date": "2026-07-11",
                "location": "수원화성박물관",
                "price": None,
                "description": "어린이 대상 수원화성 축성 원리 이해 교육.",
                "keywords": "수원화성;역사;어린이;교육;주말",
                "source_url": "https://hsmuseum.suwon.go.kr/",
                "occurrences": [
                    {"date": "2026-07-11", "start_time": "14:00", "end_time": "14:40", "label": "1회차"},
                    {"date": "2026-07-11", "start_time": "15:00", "end_time": "15:40", "label": "2회차"},
                ],
            }
        ],
    },
    {
        "name": "성남큐브미술관",
        "collection_strategy": "snart.or.kr 전시 목록에서 venue=성남큐브미술관인 전시만 필터. 공연/음악 노이즈가 매우 많아 전시 메뉴만 사용.",
        "events": [
            {
                "content_type": "전시",
                "title": "2026 성남큐브미술관 소장품주제기획전2: 디지털소장품전 0과 1사이",
                "start_date": "2026-05-08",
                "end_date": "2026-07-05",
                "location": "성남큐브미술관 상설전시실",
                "price": None,
                "description": "성남큐브미술관 소장품을 디지털 방식으로 조명하는 주제 기획전.",
                "keywords": "현대미술;소장품;디지털;성남;마감임박",
                "source_url": "https://www.snart.or.kr/main/prex/exhibit/list.do",
            },
            {
                "content_type": "전시",
                "title": "2026 성남작가조명전Ⅱ: 김홍년, 꿈의 대화",
                "start_date": "2026-05-15",
                "end_date": "2026-07-12",
                "location": "성남큐브미술관 반달갤러리",
                "price": None,
                "description": "성남작가조명전 두 번째 전시로 김홍년 작가의 작품세계를 조명.",
                "keywords": "현대미술;지역작가;회화;성남;마감임박",
                "source_url": "https://www.snart.or.kr/main/prex/exhibit/list.do",
            },
            {
                "content_type": "전시",
                "title": "캐서린 번하드 특별전",
                "start_date": "2026-07-03",
                "end_date": "2026-09-06",
                "location": "성남큐브미술관 기획전시실",
                "price": None,
                "description": "성남큐브미술관 특별전.",
                "keywords": "해외미술;현대미술;회화;성남",
                "source_url": "https://www.snart.or.kr/main/prex/exhibit/list.do",
            },
        ],
    },
    {
        "name": "고양아람누리 아람미술관",
        "collection_strategy": "artgy.or.kr 전시 상세/고양문화재단 공지에서 venue=아람미술관 또는 갤러리누리 필터. 공연 노이즈 제외.",
        "events": [
            {
                "content_type": "전시",
                "title": "고양미술축제 2026: 어반 시놉시스",
                "start_date": "2026-05-13",
                "end_date": "2026-08-02",
                "location": "고양아람누리 아람미술관",
                "price": None,
                "description": "도시를 주제로 한 고양미술축제 2026 전시.",
                "keywords": "현대미술;도시;지역미술;고양",
                "source_url": "https://www.artgy.or.kr/",
            },
            {
                "content_type": "전시",
                "title": "달콤한 상상 Sweet Wonderland",
                "start_date": "2026-06-02",
                "end_date": "2026-09-19",
                "location": "고양아람누리 갤러리누리",
                "price": None,
                "description": "고양아람누리 계열 전시공간에서 운영되는 가족 친화 전시.",
                "keywords": "현대미술;가족;어린이;고양",
                "source_url": "https://www.artgy.or.kr/",
            },
        ],
    },
    {
        "name": "부천시립박물관",
        "collection_strategy": "bcmuseum.or.kr/ko/exhibition 목록에서 부천시립박물관 및 부천시박물관 산하 장소를 필터. 산하관은 location으로 구분.",
        "events": [
            {
                "content_type": "전시",
                "title": "태胎, 왕실의 영원을 기리다",
                "start_date": "2026-07-14",
                "end_date": "2026-09-06",
                "location": "부천시립박물관",
                "price": None,
                "description": "부천시립박물관 예정 전시.",
                "keywords": "역사;왕실;조선;예정전시;부천",
                "source_url": "https://www.bcmuseum.or.kr/ko/exhibition/",
            },
            {
                "content_type": "전시",
                "title": "부천시립박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "부천시립박물관",
                "price": None,
                "description": "부천의 역사와 생활문화를 다루는 상설 전시.",
                "keywords": "부천;생활사;역사;상설전시",
                "source_url": "https://www.bcmuseum.or.kr/ko/pages/exhi_permanent",
                "status": "상설전시",
            },
        ],
    },
    {
        "name": "부천아트벙커B39",
        "collection_strategy": "artbunkerb39.org는 메인 동적 구성이라 브라우저/사이트맵 기반 수집 필요. 전시 없음일 때 공간 투어/상설 정보를 유지.",
        "events": [
            {
                "content_type": "전시",
                "title": "부천아트벙커B39 공간 상설 관람",
                "start_date": None,
                "end_date": None,
                "location": "부천아트벙커B39",
                "price": None,
                "description": "옛 소각장을 재생한 복합문화공간의 공간 관람 및 상설 콘텐츠.",
                "keywords": "건축;도시재생;복합문화공간;상설전시;부천",
                "source_url": "https://artbunkerb39.org/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "양평군립미술관",
        "collection_strategy": "ymuseum.org 전시 목록이 접속 불안정할 수 있어 공식 사이트와 검색 색인을 병행. 시작 예정 전시는 사전 카드로 유지.",
        "events": [
            {
                "content_type": "전시",
                "title": "UNBOXING",
                "start_date": "2026-03-14",
                "end_date": "2026-07-19",
                "location": "양평군립미술관",
                "price": None,
                "description": "양평군립미술관 현재 전시.",
                "keywords": "현대미술;양평;기획전시;마감임박",
                "source_url": "https://www.ymuseum.org/",
            },
            {
                "content_type": "전시",
                "title": "순간의 지층",
                "start_date": "2026-06-28",
                "end_date": "2026-11-29",
                "location": "양평군립미술관",
                "price": None,
                "description": "양평군립미술관 예정/현재 전시로 확인되는 장기 전시.",
                "keywords": "현대미술;양평;장기전시;예정전시",
                "source_url": "https://www.ymuseum.org/",
            },
        ],
    },
    {
        "name": "영은미술관",
        "collection_strategy": "youngeunmuseum.org current.php 목록은 정적이라 수집 안정적. 작가별 현재전시를 개별 카드로 저장.",
        "events": [
            {
                "content_type": "전시",
                "title": "박현주: 빛의 현존",
                "start_date": "2026-06-20",
                "end_date": "2026-09-06",
                "location": "영은미술관",
                "price": None,
                "description": "영은미술관 특별기획전 II.",
                "keywords": "현대미술;빛;설치;경기",
                "source_url": "https://www.youngeunmuseum.org/sub_exhibition/current.php",
            },
            {
                "content_type": "전시",
                "title": "Timberline",
                "start_date": "2026-05-30",
                "end_date": "2026-06-28",
                "location": "영은미술관",
                "price": None,
                "description": "영은미술관 현재 전시.",
                "keywords": "현대미술;자연;경기;마감임박",
                "source_url": "https://www.youngeunmuseum.org/sub_exhibition/current.php",
            },
            {
                "content_type": "전시",
                "title": "산로 山路",
                "start_date": "2026-05-30",
                "end_date": "2026-06-28",
                "location": "영은미술관",
                "price": None,
                "description": "진희란 작가의 영은미술관 현재 전시.",
                "keywords": "현대미술;자연;회화;경기;마감임박",
                "source_url": "https://www.youngeunmuseum.org/sub_exhibition/current.php",
            },
        ],
    },
    {
        "name": "미메시스 아트 뮤지엄",
        "collection_strategy": "mimesisartmuseum.co.kr 전시/소식 메뉴가 단순하지만 검색 노출이 약함. 전시 없음 시 공간 상설 관람 정보를 유지.",
        "events": [
            {
                "content_type": "전시",
                "title": "미메시스 아트 뮤지엄 상설 공간 관람",
                "start_date": None,
                "end_date": None,
                "location": "미메시스 아트 뮤지엄",
                "price": None,
                "description": "알바루 시자 건축의 미술관 공간과 상설 서가/전시 공간 관람.",
                "keywords": "건축;미술관;파주;상설전시;책",
                "source_url": "https://www.mimesisartmuseum.co.kr/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "송암미술관",
        "collection_strategy": "인천시립박물관 통합 사이트의 송암미술관 메뉴를 별도 URL로 추적. 통합 메인 노이즈가 많아 메뉴 코드 필터 필요.",
        "events": [
            {
                "content_type": "전시",
                "title": "송암미술관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "송암미술관",
                "price": "무료",
                "description": "동양 고미술과 인천 지역 미술 자료를 다루는 상설 전시.",
                "keywords": "고미술;한국미술;인천;상설전시;무료",
                "source_url": "https://www.incheon.go.kr/museum/MU020201",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "검단선사박물관",
        "collection_strategy": "인천시립박물관 통합 사이트의 검단선사박물관 메뉴/공지에서 특별전시실 제한과 전시 정보를 분리. 통합 여성복지관 예약 노이즈 제외.",
        "events": [
            {
                "content_type": "전시",
                "title": "검단선사박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "검단선사박물관",
                "price": "무료",
                "description": "검단 지역 선사 문화와 고고자료를 다루는 상설 전시.",
                "keywords": "선사;고고학;인천;상설전시;무료",
                "source_url": "https://www.incheon.go.kr/museum/MU030201",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "한국이민사박물관",
        "collection_strategy": "인천시립박물관 통합 사이트에서 한국이민사박물관 메뉴 코드만 필터. 특별전은 별도 공지/전시 목록 확인 필요.",
        "events": [
            {
                "content_type": "전시",
                "title": "한국이민사박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "한국이민사박물관",
                "price": "무료",
                "description": "한인 이민의 역사와 디아스포라 자료를 다루는 상설 전시.",
                "keywords": "이민사;근현대사;인천;디아스포라;상설전시;무료",
                "source_url": "https://www.incheon.go.kr/museum/MU040201",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "인천도시역사관",
        "collection_strategy": "인천도시역사관 자체 메뉴와 교육/강좌 공지를 별도 파싱. 어린이박물관/본관 위치를 location으로 구분.",
        "events": [
            {
                "content_type": "전시",
                "title": "갯벌도시, 인천",
                "start_date": "2025-12-09",
                "end_date": "2026-12-31",
                "location": "인천도시역사관 어린이박물관 2층 기획전시실",
                "price": "무료",
                "description": "갯벌과 도시 인천의 관계를 어린이 눈높이로 보여주는 기획전.",
                "keywords": "인천;도시사;갯벌;어린이;환경;무료",
                "source_url": "https://www.incheon.go.kr/museum/MU050201",
            },
            {
                "content_type": "강연",
                "title": "제11회 도시를 보는 작가: 이근택, 도시산수",
                "start_date": "2026-07-18",
                "end_date": "2026-07-18",
                "location": "인천도시역사관",
                "price": "무료",
                "description": "인천도시역사관 토요강좌.",
                "keywords": "강연;도시;미술;인천;무료;주말",
                "source_url": "https://www.incheon.go.kr/museum/MU050401",
                "occurrences": [{"date": "2026-07-18", "label": "강좌 진행"}],
            },
        ],
    },
    {
        "name": "인천상륙작전기념관",
        "collection_strategy": "landing915.com은 접속 불안정 가능. 전시안내/공지 메뉴를 재시도 수집하고 특별전 없을 때 상설전 유지.",
        "events": [
            {
                "content_type": "전시",
                "title": "인천상륙작전기념관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "인천상륙작전기념관",
                "price": None,
                "description": "인천상륙작전과 한국전쟁 관련 자료를 다루는 상설 전시.",
                "keywords": "근현대사;전쟁;인천;상설전시",
                "source_url": "https://www.landing915.com/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "수도국산달동네박물관",
        "collection_strategy": "icdonggu.go.kr/open_content/museum 하위 전시/교육 페이지 수집. 지방자치단체 사이트라 URL 안정성은 높음.",
        "events": [
            {
                "content_type": "전시",
                "title": "수도국산달동네박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "수도국산달동네박물관",
                "price": None,
                "description": "달동네 생활사와 인천 동구의 도시 기억을 다루는 상설 전시.",
                "keywords": "생활사;도시사;인천;상설전시;가족",
                "source_url": "https://www.icdonggu.go.kr/open_content/museum/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "강화역사박물관",
        "collection_strategy": "ghss.or.kr 메인은 시설관리공단 통합 노이즈가 많음. 강화역사박물관 전시/공지 전용 메뉴를 추가 탐색해야 함.",
        "events": [
            {
                "content_type": "전시",
                "title": "강화역사박물관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "강화역사박물관",
                "price": None,
                "description": "강화의 선사·고대·고려·근현대 역사를 다루는 상설 전시.",
                "keywords": "강화;역사;고려;인천;상설전시",
                "source_url": "https://www.ghss.or.kr/",
                "status": "상설전시",
            }
        ],
    },
    {
        "name": "한국근대문학관",
        "collection_strategy": "lit.ifac.or.kr 또는 ifac.or.kr 통합 도메인에서 전시/프로그램 페이지를 추적. 현재 특별전 없을 때 상설전 유지.",
        "events": [
            {
                "content_type": "전시",
                "title": "한국근대문학관 상설전시",
                "start_date": None,
                "end_date": None,
                "location": "한국근대문학관",
                "price": None,
                "description": "한국 근대문학의 형성과 작가·작품을 다루는 상설 전시.",
                "keywords": "문학;근대문학;인천;상설전시",
                "source_url": "https://lit.ifac.or.kr/",
                "status": "상설전시",
            }
        ],
    },
]


def load_b_metadata():
    metadata = {}
    with INSTITUTION_CSV.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("tier") == "B":
                metadata[row["institution_name"]] = row
    return metadata


def get_institution_id(conn, name, metadata):
    row = conn.execute("SELECT id FROM institutions WHERE name = ?", (name,)).fetchone()
    if row:
        conn.execute(
            """
            UPDATE institutions
            SET region = COALESCE(?, region),
                city = COALESCE(?, city),
                category = COALESCE(?, category),
                collection_phase = 'phase2',
                exhibition_url = COALESCE(exhibition_url, ?),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                metadata.get("region"),
                metadata.get("city"),
                metadata.get("category"),
                metadata.get("official_url"),
                row[0],
            ),
        )
        return row[0]
    cursor = conn.execute(
        """
        INSERT INTO institutions (name, region, city, category, priority, collection_phase, exhibition_url, active)
        VALUES (?, ?, ?, ?, 2, 'phase2', ?, 1)
        """,
        (
            name,
            metadata.get("region") or "확인필요",
            metadata.get("city"),
            metadata.get("category") or "박물관",
            metadata.get("official_url"),
        ),
    )
    return cursor.lastrowid


def upsert_event(conn, institution_id, source, metadata, event):
    source_url = event["source_url"]
    image_url = event.get("image_url") or discover_image(source_url)
    status = infer_status(event.get("start_date"), event.get("end_date"), event.get("status"))
    nature = event_nature({**event, "status": status})
    raw_text = (
        f"B등급 보강 수집. 기관={source['name']}; 전략={source.get('collection_strategy', '')}; "
        f"원천={source_url}; 설명={event.get('description', '')}"
    )
    exists = conn.execute(
        """
        SELECT id FROM cultural_events
        WHERE institution_id = ? AND title = ? AND start_date IS ? AND source_url = ?
        ORDER BY id
        """,
        (institution_id, event["title"], event.get("start_date"), source_url),
    ).fetchone()
    values = (
        event.get("content_type") or "전시",
        clean_text(event["title"]),
        event.get("start_date"),
        event.get("end_date"),
        event.get("location"),
        metadata.get("region"),
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
    return {
        "institution": source["name"],
        "event_id": event_id,
        "result": result,
        "title": event["title"],
        "content_type": event.get("content_type") or "전시",
        "start_date": event.get("start_date"),
        "end_date": event.get("end_date"),
        "status": status,
        "source_url": source_url,
        "image_url": image_url,
    }


def dedupe_managed_events(conn, managed):
    removed = []
    for source in B_GRADE_SOURCES:
        metadata = managed[source["name"]]
        institution_id = get_institution_id(conn, source["name"], metadata)
        for event in source.get("events", []):
            rows = conn.execute(
                """
                SELECT id FROM cultural_events
                WHERE institution_id = ? AND title = ? AND start_date IS ? AND source_url = ?
                ORDER BY id
                """,
                (institution_id, event["title"], event.get("start_date"), event["source_url"]),
            ).fetchall()
            if len(rows) <= 1:
                continue
            keep = rows[0][0]
            for row in rows[1:]:
                conn.execute("DELETE FROM cultural_events WHERE id = ?", (row[0],))
                removed.append((source["name"], event["title"], keep, row[0]))
    return removed


def build_report(results, removed, metadata_by_name):
    by_institution = defaultdict(list)
    for item in results:
        by_institution[item["institution"]].append(item)
    inserted = sum(1 for item in results if item["result"] == "inserted")
    updated = sum(1 for item in results if item["result"] == "updated")
    lines = [
        "# B등급 36개 기관 보강 수집 리포트",
        "",
        f"- 확인일: {TODAY.isoformat()}",
        f"- 확인 기관: {len(B_GRADE_SOURCES)}개",
        f"- DB 반영 일정: {len(results)}건",
        f"- 신규 추가: {inserted}건",
        f"- 기존 갱신: {updated}건",
        f"- 중복 정리: {len(removed)}건",
        "",
        "## 기관별 결과",
        "",
    ]
    for source in B_GRADE_SOURCES:
        name = source["name"]
        metadata = metadata_by_name.get(name, {})
        lines.append(f"### {name}")
        lines.append("")
        lines.append(f"- 지역: {metadata.get('region', '')} {metadata.get('city', '')}".rstrip())
        lines.append(f"- 공식 사이트: {metadata.get('official_url', '')}")
        lines.append(f"- 수집기화 메모: {source['collection_strategy']}")
        items = by_institution.get(name, [])
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
    if removed:
        lines.extend(["## 중복 정리", ""])
        for institution, title, keep, drop in removed:
            lines.append(f"- {institution}: {title} / keep={keep}, drop={drop}")
        lines.append("")
    lines.extend(
        [
            "## 자동 수집기 전환 우선순위",
            "",
            "1. GGCF 계열(실학·전곡·경기도어린이): 목록 구조가 비슷해서 공통 수집기로 확장 가능.",
            "2. 서울역사박물관 계열(서울생활사·청계천·한양도성): venue 필터만 안정화하면 자동화 난이도 낮음.",
            "3. 수원박물관/수원화성박물관: 통합 예약 페이지에서 museumCd 필터가 핵심.",
            "4. 인천 통합 박물관 계열: 같은 도메인이라 가능하지만 여성복지관 예약 노이즈를 반드시 제외해야 함.",
            "5. 사립 미술관/소규모 공간: 사이트 접속 실패와 SNS 의존이 있어 재시도/브라우저 기반 수집을 검토.",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main():
    metadata_by_name = load_b_metadata()
    missing = [source["name"] for source in B_GRADE_SOURCES if source["name"] not in metadata_by_name]
    if missing:
        raise RuntimeError(f"B등급 후보 목록에 없는 기관: {', '.join(missing)}")
    results = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        ensure_tables(conn)
        for source in B_GRADE_SOURCES:
            metadata = metadata_by_name[source["name"]]
            institution_id = get_institution_id(conn, source["name"], metadata)
            for event in source.get("events", []):
                results.append(upsert_event(conn, institution_id, source, metadata, event))
        removed = dedupe_managed_events(conn, metadata_by_name)
        conn.commit()
    build_report(results, removed, metadata_by_name)
    print(f"checked={len(B_GRADE_SOURCES)}")
    print(f"events={len(results)}")
    print(f"inserted={sum(1 for item in results if item['result'] == 'inserted')}")
    print(f"updated={sum(1 for item in results if item['result'] == 'updated')}")
    print(f"removed_duplicates={len(removed)}")
    print(f"report={REPORT_PATH}")


if __name__ == "__main__":
    main()
