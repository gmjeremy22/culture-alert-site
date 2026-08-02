# Culture Alert Project Handoff

이 문서는 `culture-alert-site` 프로젝트를 다른 Codex 작업 환경이나 새 채팅에서 그대로 이어가기 위한 인계 문서다. 새 작업자는 이 문서를 먼저 읽고, 이어서 `README.md`, 최근 Git 커밋, 최신 GitHub Actions 실행 로그를 확인한다.

## 1. 시작용 안내문

새 Codex 채팅에 아래 문장을 그대로 붙여 넣으면 된다.

```text
다음 프로젝트를 이전 Codex 작업의 연속으로 맡아줘.

프로젝트 루트:
C:\Users\이기민\Documents\이기민\culture-alert-site

먼저 HANDOFF.md와 README.md를 읽고, git status와 최근 GitHub Actions 실행 로그를 확인해 현재 상태를 파악해줘. 기존 사용자 요청과 구현 의도를 존중하며, 비밀번호 보호 구조(AES-GCM/PBKDF2)는 절대 약화하거나 비밀번호를 코드/커밋에 넣지 마. 현재 데이터 수집 상태와 미해결 과제까지 HANDOFF.md에 정리되어 있다. 그 뒤 내가 이어서 질문하는 내용을 이 프로젝트의 다음 작업으로 처리해줘.
```

## 2. 프로젝트 정체성과 주소

- GitHub 저장소: `gmjeremy22/culture-alert-site`
- GitHub Pages: <https://gmjeremy22.github.io/culture-alert-site/>
- 로컬 루트: `C:\Users\이기민\Documents\이기민\culture-alert-site`
- 기본 브랜치: `main`
- 사이트 목적: 수도권, 특히 서울의 박물관·미술관 전시와 선택된 강연·교육 일정을 수집하고, 가족/개인 취향에 맞춰 카드형으로 추천하는 비공개 문화 일정 리포트
- 배포 형태: GitHub Pages의 정적 사이트. 본문 데이터는 브라우저에서 비밀번호로 복호화한다.

## 3. 절대 보존할 보안 원칙

사이트 비밀번호는 GitHub repository secret `CULTURE_ALERT_SITE_PASSWORD`에만 있다. 코드나 Git 이력에 비밀번호를 넣지 않는다.

다음 구조는 유지해야 한다.

- `tools/build-protected-site.js`: 리포트 HTML을 암호화된 Pages 문서로 만든다.
- AES-GCM 암호화, PBKDF2 키 유도, payload 형식, 검증 marker, secret 취급을 바꾸거나 약화하지 않는다.
- `tools/verify-protected-site.js`가 암호화 사이트에 평문 카드 데이터가 새지 않는지 검사한다.
- `public/index.html`은 생성 산출물이며 GitHub Pages가 실제로 배포하는 파일이다.

## 4. 주요 파일 지도

| 영역 | 파일 | 역할 |
| --- | --- | --- |
| DB 초기화 | `automation/init_culture_db.py` | SQLite 스키마와 기관/관심사/공식 총람 seed를 DB에 반영한다. |
| 매일 업데이트 | `automation/run_daily_update.py` | 수집, 상태 갱신, 태깅, 추천, 카드 생성, 암호화 사이트 생성의 중심 실행 파일이다. |
| 주간 반자동 후보 | `automation/run_weekly_semi_auto.py` | 수집기 없는 기관 대상의 후보 수집·검토·고신뢰 병합 pipeline이다. |
| 통합 수집기 등록 | `automation/culture-alert/outputs/culture_alert_scraper.py` | `SCRAPERS` 등록표, 일반 수집기, 낮은 등급/공식 페이지 모니터 관련 로직이 있다. |
| 우선 기관 수집기 | `automation/culture-alert/outputs/priority_seoul_scrapers.py` | 아모레퍼시픽, 디뮤지엄, 금호, 퐁피두 한화 등 주요 서울 기관 전용 수집기다. |
| 적응형 수집기 | `automation/culture-alert/outputs/adaptive_official_collector.py` | 전용 파서가 없는 몇몇 주요 기관의 공식 페이지를 공통 방식으로 수집한다. |
| 카드 사이트 생성 | `automation/culture-alert/outputs/culture_card_gallery.py` | 실제 추천/검색/기관 둘러보기/상세 drawer/모바일 UI가 들어 있는 큰 HTML 생성기다. |
| 추천 점수 | `automation/culture-alert/outputs/culture_keyword_tagger.py` | 관심 키워드 태깅과 추천 점수 계산을 담당한다. |
| 규모 지표 | `automation/culture-alert/outputs/institution-scale-metrics.csv` | 문화기반시설 총람을 바탕으로 한 기관 규모 점수다. |
| 총람 처리 | `automation/culture-alert/outputs/official_facility_directory.py` | 공식 문화시설 총람 CSV를 기관 DB와 규모 지표에 반영한다. |
| 기관 수집 범위 점검 | `automation/culture-alert/outputs/institution_coverage_audit.py` | 카드 0건, 수집 이력 없음 등의 기관 현황을 분석한다. |
| 데이터 점검 | `automation/culture-alert/outputs/culture_data_audit.py` | 날짜, URL, 기관 연결, 중복 등 데이터 품질을 검사한다. |
| UI 점검 | `automation/culture-alert/outputs/culture_ui_audit.py` | 카드 데이터/뷰/모바일 위험 요소/수동 점검 목록을 검사한다. |
| 이미지 점검 | `automation/culture-alert/outputs/culture_image_audit.py` | 표시 이미지의 손상 여부를 검사한다. |
| 매일 workflow | `.github/workflows/daily-update.yml` | 매일 cloud update와 Pages 배포 workflow다. |
| 코드 배포 workflow | `.github/workflows/deploy.yml` | `main` push 시 cloud update 및 Pages 배포를 수행한다. |
| 반자동 workflow | `.github/workflows/weekly-semi-auto.yml` | 주간 반자동 후보 검토 workflow다. |
| 검색 테스트 | `tools/test-search-relevance.js` | 기관/전시 유사 검색이 무관한 결과를 내지 않는지 검사한다. |
| 주요 기관 우선 테스트 | `tools/test-recommendation-priority.js` | 임박한 소규모 일정이 주요 기관 추천을 앞지르지 않는지 검사한다. |
| 현재/예정 분리 테스트 | `tools/test-schedule-separation.js` | 현재 일정과 미래 시작 일정을 엄격히 분리하는지 검사한다. |

생성 산출물은 대부분 `.gitignore` 대상이다. 특히 `automation/culture-alert/outputs/culture-alert.sqlite`, 생성 HTML, 점검 리포트는 로컬/Actions 산출물이며 보통 Git에 커밋하지 않는다.

## 5. 현재 구현된 사용자 기능

### 리포트 및 개인화

- 비밀번호 입력 뒤에만 본문을 열 수 있다.
- 로그인 서버 없이 브라우저 `localStorage`에 프로필 이름, 관심 분야, 강연·교육 포함 여부를 저장한다.
- 프로필별로 관심 분야를 고르고, 전시 중심 또는 강연·교육 포함을 선택한다.
- 가족/취향 기반 추천, 주요 기관 우선 추천, 덜 알려진 발견 후보를 구분해 보여 준다.
- 추천 이유는 숫자 점수 대신 `취향 적합`, `곧 종료`, `주요 기관`, `이번 주 추천`, `상설로 여유롭게` 같은 editorial badge로 표현한다.

### 일정 분류

- `추천 보기`: 이미 시작한 추천 대상만 표시한다.
- `현재 전시`: 이미 시작한 기간 전시만 표시한다.
- `강연·교육`: 이미 시작한 프로그램만 표시한다. 프로필에서 프로그램 수신을 켠 경우에만 사용한다.
- `예정 일정`: 미래 시작일을 가진 전시·강연·교육·행사를 독립적으로 표시한다. 시작일 가까운 순이며 `내일 시작`, `N일 뒤 시작` 배지가 있다.
- `상설전`: 별도 탭이다.
- 분류 규칙: `startsInDays > 0`이면 예정, 시작일이 되면 상태 문자열이 `예정`으로 남아 있어도 현재 일정으로 이동한다.
- 같은 장소 추천은 현재 일정과 예정 일정을 섞지 않는다.

### 탐색과 동선

- 카드 클릭 시 상세 drawer, 원문 보기, 지도 보기, 세부 회차, 같은 장소에서 함께 볼 것 기능을 제공한다.
- 모바일 하드웨어/브라우저 뒤로가기는 열린 drawer를 먼저 닫고, 바로 사이트를 닫지 않도록 history 처리했다.
- `기관 둘러보기`는 기관 종류(미술관/박물관/기타), 지역, 현재 일정 여부 등을 필터링한다.
- 기관 상세에서는 현재 일정과 예정 일정을 따로 표시한다.
- 통합 검색은 기관명/전시명/별칭/유사어/띄어쓰기 차이/초성/가벼운 오타를 대상으로 한다. 완전한 키워드 일치만 요구하지 않되 무관한 결과는 낮춘다.

### 추천 우선순위

- 문화기반시설 총람의 기관 규모 지표를 활용한다.
- 주요 기관 점수가 마감 임박 가중치보다 우선한다.
- 추천과 기관 둘러보기 모두 주요 박물관·미술관을 먼저 배치한다.
- 작은 기관이나 덜 알려진 취향 적합 일정은 별도의 발견 후보 성격으로 유지한다.

### 디자인과 품질

- 어두운 editorial 문화 큐레이션 UI, 카드 등장 애니메이션, 모바일 반응형 drawer를 구현했다.
- 관심 분야 선택에 원형 이미지가 들어간 onboarding을 사용한다.
- 전시 원본 이미지를 배경 장식으로 잘못 쓰는 방식은 되돌린 상태다.
- 카드, 상세 drawer, 필터, 검색, 모바일 레이아웃에 대한 자동 UI 점검과 수동 점검 checklist가 있다.

## 6. 데이터와 수집 구조

### 자동 수집 범위

`culture_alert_scraper.SCRAPERS`에는 현재 49개 항목이 등록되어 있다.

- 매일/코드 배포 시 48개를 실행한다.
- `official-page-monitor` 1개는 낮은 신뢰도의 모니터링 후보 성격이라 기본 추천/자동 배포에서 의도적으로 제외한다.
- 전용 수집기, 주요 기관 전용 수집기, 적응형 공식 페이지 수집기, 승격된 낮은 등급 수집기, 일부 지역 소규모 기관 묶음 수집기가 함께 들어 있다.

기관 디렉터리에 있는 모든 서울 기관이 전용 수집기를 가진 것은 아니다. 일정 카드가 0건인 기관은 다음 중 하나일 수 있다.

- 실제 공개 일정이 없거나 휴관 상태
- 웹 구조가 바뀌어 수집기가 새 정보를 못 읽음
- 전용 수집기/적응형 수집기 대상이 아직 아님
- 공식 페이지가 자바스크립트/예약 서비스 중심이라 일반 추출이 어려움
- 기존 일정이 모두 종료됨

따라서 `기관 둘러보기`는 일정이 없어도 기관 자체를 남겨 두는 의도된 기능이다.

### DB 보존 정책

2026-08-01에 중요한 수정이 완료됐다. 이전에는 코드 push 배포가 빈 DB에서 시작할 수 있어, 한 수집기 실패가 기존 정상 카드를 빠뜨릴 위험이 있었다.

현재 `daily-update.yml`과 `deploy.yml`은 모두 아래를 수행한다.

1. GitHub Actions cache에서 마지막 성공 `culture-alert.sqlite`을 복원한다.
2. DB 파일을 실제로 복원하지 못했으면 빈 DB로 배포하지 않고 workflow를 실패시킨다.
3. 48개 수집기를 실행한다.
4. 각 수집기는 일시적인 timeout/네트워크 오류에 대해 2회까지 시도한다.
5. 실패 기관의 기존 DB 일정은 남기고, 성공 기관의 신규/변경 일정만 반영한다.
6. 상태·태그·추천·카드를 갱신하고 품질 검사를 한다.
7. 성공한 DB를 다음 실행용 cache로 저장하고 Pages에 배포한다.

`automation/run_daily_update.py`는 수집기별 결과를 Actions 로그에 다음 형태로 출력한다.

```text
sources=48
failed_sources=N
cards=N
source=<name> status=ok ...
source=<name> status=failed error=...
```

## 7. 최신 사실: 2026-08-02 KST 기준

### Git 상태

- 브랜치: `main`
- 마지막 기능 커밋: `a3740b3 Retry transient culture source failures`
- 그 직전 중요 커밋:
  - `2d7e0cf Preserve culture data across deployments`
  - `31c371a Separate upcoming schedules from current listings`
  - `eed1176 Add search to the recommendation home screen`
  - `4c1c9a6 Prioritize major institutions in recommendations`
- 이 문서를 만들기 직전 작업 트리는 깨끗한 상태였다.

### 최신 성공한 자동 실행

- Daily update: 2026-08-02 07:40 KST 시작, 성공
- 실행 링크: <https://github.com/gmjeremy22/culture-alert-site/actions/runs/30721764360>
- 마지막 성공 DB cache를 정상 복원하고 새 cache로 저장했다.
- 48개 수집기 호출, 9개는 재시도 뒤에도 실패, 39개 성공
- 생성 카드 총수: 257건
- 현재 전시: 106건
- 현재 프로그램: 46건
- 예정 일정: 59건
- 상설전은 나머지 46건으로 추정된다.
- 데이터 품질 검사 통과, UI 검사 P1/P2/P3 모두 0건, 현재/예정 분리 검사 통과

최신 실패 수집기 9개는 아래와 같다. 기존 일정은 DB 보존 정책 때문에 남아 있지만, 해당 기관의 아주 최근 신규 변경분은 다음 성공 수집 전까지 늦을 수 있다.

| 수집기 | 문제 |
| --- | --- |
| `hangeul` | timeout |
| `mmca` | timeout |
| `much-programs` | timeout |
| `nfm` | timeout |
| `priority-apma` | HTTP 403 및 오래된 호스트 해석 실패 |
| `priority-incheon-city-museum` | timeout |
| `priority-pompidou-hanwha` | timeout 및 hostname 해석 실패 |
| `small-local-deep-seongbuk` | timeout |
| `suma` | timeout |

직전 코드 배포에서도 `priority-pompidou-hanwha` 문제가 확인됐다. 퐁피두 한화 관련 기관이 사이트에 없다는 인상을 줄 수 있으므로 전용 수집기 URL과 현재 공식 사이트 구조를 우선 점검할 가치가 높다.

### 카드 수가 예전보다 적어 보인 이유

로컬에 남아 있던 2026-07-14 DB는 카드 315건, 전시 198건이었다. 이 수치는 날짜가 지난 전시를 여전히 포함한 과거 스냅샷이라 2026-08-02 cloud 결과와 단순 비교하면 안 된다. 현재는 종료 일정을 상태 갱신에서 제외하고, 시작 전 일정도 별도 `예정 일정` 탭으로 분리한다.

## 8. 아직 해결하지 않은 중요한 일

### 우선순위 높음: 수집 안정성

1. 최신 실패 9개 수집기를 우선 보강한다.
   - `priority-apma`: HTTPS/현행 페이지 주소/403 대응 확인
   - `priority-pompidou-hanwha`: 실제 현행 도메인과 행사 목록 URL 확인
   - `mmca`, `hangeul`, `nfm`, `suma`, `much-programs`: timeout에 대한 shorter page/대체 endpoint/요청 방식 검토
   - 성북 지역 deep collector: 기관별로 쪼개거나 timeout을 줄이는 방안 검토
2. 수집기 실패율이 일정 기준을 넘으면 Actions 성공으로만 끝내지 않고 경고를 남기거나 별도 상태 리포트를 만드는 것이 좋다.
3. 기관 수집 범위 점검기를 GitHub artifact로 올려 매일 카드 0건/수집 이력 없음 변화를 확인하는 기능을 고려한다.

### 우선순위 높음: 주간 반자동 수집을 실제 지속 저장으로 연결

`weekly-semi-auto.yml`은 매주 월요일 08:10 KST에 실행된다. 하지만 현재 기본 동작은 review artifact를 만들고, 명시적으로 수동 실행하며 `publish_to_pages`를 켜지 않는 한 Pages에 배포하지 않는다. 또한 `run_weekly_semi_auto.py`는 기본적으로 DB를 reset한 뒤 후보를 만든다.

따라서 다음 개선이 적절하다.

1. 주간 workflow도 마지막 성공 DB cache를 복원한다.
2. DB reset 대신 안정적인 daily DB 위에서 반자동 후보를 찾는다.
3. `auto_merge` 후보만 자동 병합한다.
4. `needs_review` 후보는 artifact/리포트로 남긴다.
5. 데이터/UI/암호화 검사를 통과하면 DB cache를 저장하고 Pages도 자동 배포한다.

이렇게 하면 사람은 애매한 후보만 확인하면 되고, 수집기 없는 기관까지 매주 일정 부분 자동 보완할 수 있다. 이 변경은 사이트 데이터 신뢰성에 큰 영향을 주므로 먼저 pipeline의 중복/오탐 검증 기준을 읽고 진행한다.

### 중간 우선순위: 기관 커버리지 확대

- 서울 기관을 중심으로 전용 수집기 또는 적응형 수집기 대상을 확대한다.
- 카드 0건 기관은 일정 부재와 수집 부재를 구분해 `기관 둘러보기`에 적절히 남긴다.
- 경기/인천은 서울 안정화 뒤에 확대한다.
- 문화기반시설 총람 원본 갱신 시 `official_facility_directory.py --workbook <원본.xlsx>` 흐름을 사용한다.

### 제품 기능 후보

- 카카오톡 자동 전송 구조 설계 및 구현
- 수집 실패/중요 새 일정 알림
- 검색 순위 세밀화
- 별도 "숨은 취향 발견" 추천 큐 개선
- 실제 브라우저 기반 UI 점검을 더 강화해 모든 클릭 동선을 자동 탐색

## 9. 로컬 검증 명령

아래는 일반적인 검증 순서다. 실행 전에 `git status`로 사용자 변경이 없는지 확인한다.

```powershell
cd C:\Users\이기민\Documents\이기민\culture-alert-site

python -m py_compile automation/run_daily_update.py `
  automation/culture-alert/outputs/culture_card_gallery.py `
  automation/culture-alert/outputs/culture_ui_audit.py

node tools/test-search-relevance.js
node tools/test-recommendation-priority.js
node tools/test-schedule-separation.js

python automation/culture-alert/outputs/culture_data_audit.py
python automation/culture-alert/outputs/culture_ui_audit.py `
  --html automation/culture-alert/outputs/keyword-recommendation-report.html
python automation/culture-alert/outputs/culture_image_audit.py
```

전체 cloud와 같은 로컬 갱신은 password 환경 변수가 필요하며 로컬 DB를 변경한다.

```powershell
$env:CULTURE_ALERT_SITE_PASSWORD = "<비밀번호는 직접 입력>"
python automation/run_daily_update.py
```

새 기능으로 `main`에 push하면 `.github/workflows/deploy.yml`이 실행된다. Actions가 약 10~30분 걸릴 수 있다. 배포 성공만 보지 말고 Build 단계 로그에서 `failed_sources`, `cards`, `schedule separation audit passed`를 함께 확인한다.

## 10. 새 작업자가 지켜야 할 방식

- 사용자가 요청한 범위 외의 디자인/DB/암호화 구조를 갑자기 바꾸지 않는다.
- 생성 HTML과 SQLite는 보통 산출물이므로 불필요하게 Git에 넣지 않는다.
- 수집기 하나의 실패로 기존 이벤트를 삭제하거나 DB를 reset한 뒤 즉시 Pages에 배포하지 않는다.
- 전시/강연/교육의 현재와 예정 분리 규칙을 유지한다.
- 추천 우선순위에서는 주요 기관 점수가 단순 마감 임박 가중치보다 앞서야 한다.
- 새 수집기를 추가하면 해당 기관의 현재 행사 목록, 종료 처리, 중복, 이미지, 원문 링크, 현재/예정 분류를 함께 확인한다.
- UI 변경 후에는 데스크톱과 모바일 drawer, 뒤로가기, 검색, 필터, 원문/지도 링크까지 검사한다.
- GitHub Pages 반영이 필요한 변경은 커밋·push 뒤 Actions 성공과 실제 URL 응답까지 확인한다.

## 11. 참고 링크

- 사이트: <https://gmjeremy22.github.io/culture-alert-site/>
- 최신 daily 실행: <https://github.com/gmjeremy22/culture-alert-site/actions/runs/30721764360>
- 마지막 코드 배포 실행: <https://github.com/gmjeremy22/culture-alert-site/actions/runs/30693197746>
- 저장소: <https://github.com/gmjeremy22/culture-alert-site>

