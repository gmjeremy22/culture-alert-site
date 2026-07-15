# Culture Alert Site

수도권 문화 일정 카드 리포트를 GitHub Pages에 게시하는 저장소입니다. 공개 저장소에는 원본 DB와 원본 HTML을 올리지 않고, 비밀번호로 암호화된 `public/index.html`만 배포합니다.

## 사용자가 GitHub에서 할 일

1. 이 폴더의 로컬 커밋을 GitHub에 push합니다.
   - GitHub Desktop: `File` -> `Add local repository` -> 이 폴더 선택 -> `Publish branch`
   - 터미널: `git push -u origin main`
2. GitHub 저장소 `Settings` -> `Pages`로 이동합니다.
3. `Build and deployment`의 Source를 `GitHub Actions`로 설정합니다.
4. 저장소 `Settings` -> `Secrets and variables` -> `Actions`로 이동합니다.
5. `New repository secret`을 누르고 아래 Secret을 추가합니다.
   - Name: `CULTURE_ALERT_SITE_PASSWORD`
   - Secret: 리포트를 열 때 쓸 비밀번호
6. `Actions` 탭에서 `Daily protected report update`를 선택하고 `Run workflow`로 한 번 수동 실행합니다.

배포 주소는 보통 아래 형태입니다.

```text
https://gmjeremy22.github.io/culture-alert-site/
```

## 자동 업데이트

- `.github/workflows/daily-update.yml`은 매일 07:37 KST에 실행됩니다.
- GitHub Actions가 새 DB를 만들고, 공개 가능한 수집기 26개를 실행하고, 카드 HTML을 다시 만든 뒤 암호화해서 Pages에 배포합니다.
- 기본 실행에서는 느리고 실패 가능성이 큰 `official-page-monitor`를 제외합니다.
- 필요할 때만 workflow 환경변수 `CULTURE_ALERT_INCLUDE_OFFICIAL_MONITOR=1`로 켤 수 있습니다.

## 추천 순서와 기관 규모 지표

- `official-facility-directory.csv`는 문화체육관광부 `2025 전국 문화기반시설 총람`의 수도권 박물관·미술관 409곳을 전부 대조한 기관 원장입니다. 서울은 박물관 137곳과 미술관 43곳, 합계 180곳입니다.
- 서비스의 기본 추천 지역과 `기관 둘러보기` 기본 필터는 서울이며, 경기·인천은 `전체` 또는 지역 필터를 선택하면 함께 볼 수 있습니다.
- `institution-scale-metrics.csv`는 같은 원자료 409곳의 관람객 수·소장품 수·전시 면적을 추천 정렬용 지표로 정리한 자료입니다.
- 기관 규모 점수는 연 관람객 55%, 소장품 20%, 전시실 면적 10%, 설립·등록 성격 15%를 반영합니다. 관람객·소장품·면적은 로그 변환 후 수도권 내 백분위로 환산해 초대형 기관 하나가 전체 추천을 독점하지 않게 합니다.
- 기본 추천은 `취향 적합성 + 기관 규모 + 일정 품질 + 제한된 마감 가중치`로 정렬하고, 마감 임박은 별도 패널에서 다룹니다.
- `취향으로 찾은 숨은 전시`는 기관 규모 점수가 주요 기관 기준보다 낮지만 현재 프로필의 취향 점수가 충분히 높은 후보만 따로 보여줍니다.
- 총람 원본이 바뀐 경우 `official_facility_directory.py --workbook <원본.xlsx>`를 실행해 기관 DB, 공식 메타데이터, 대조표와 규모 지표를 함께 갱신합니다.

## 주간 반자동 후보 점검

- `.github/workflows/weekly-semi-auto.yml`은 매주 월요일 08:10 KST에 실행됩니다.
- 보류 기관과 위험도가 있는 기관은 바로 사이트 카드에 섞지 않고 `event_candidates` 후보로 먼저 저장합니다.
- 후보는 자동 병합 가능, 검토 필요, 폐기로 나뉘며 자동 병합 가능 후보만 임시 DB에 합쳐 카드와 감사 리포트를 다시 만듭니다.
- 기본 주간 실행은 Pages에 게시하지 않고 Actions artifact에 검토 결과를 남깁니다.
- 필요할 때만 `Actions` -> `Weekly semi-auto candidate review` -> `Run workflow`에서 `publish_to_pages`를 켜면 검증 통과 후보가 포함된 보호 페이지를 게시합니다.

## 로컬에서 수동 게시

로컬 원본 프로젝트의 최신 HTML을 암호화해서 `public/index.html`을 만들고 싶을 때 사용합니다.

```powershell
$env:CULTURE_ALERT_SITE_PASSWORD="<비밀번호>"
.\tools\publish-local.ps1
```

## 로컬 검증

아래 명령은 임시 비밀번호로 암호화/복호화가 되는지 확인합니다. 이 비밀번호를 커밋하지 않습니다.

```powershell
$env:CULTURE_ALERT_SITE_PASSWORD="<임시검증용비밀번호>"
python automation\run_daily_update.py --output "$env:TEMP\culture-alert-test.html"
Remove-Item "$env:TEMP\culture-alert-test.html"
```

## 로컬 원본 코드를 다시 반영

`C:\Users\이기민\Documents\이기민\culture-alert\outputs`의 수집 코드를 자동화용 폴더로 다시 복사하려면 아래 명령을 사용합니다.

```powershell
.\tools\stage-cloud-source.ps1
```

## 보안 원칙

- 비밀번호는 코드, README, 커밋 메시지에 쓰지 않습니다.
- `culture-alert.sqlite`, 원본 `keyword-recommendation-report.html`, 원본 `culture-card-gallery.html`은 커밋하지 않습니다.
- `automation/culture-alert/outputs`에는 공개 가능한 Python 수집 코드, 스키마, 시드 CSV만 둡니다.
- 이 방식은 정적 파일 암호화입니다. 링크를 아는 사람이 암호화된 HTML 파일 자체를 받을 수는 있지만, 비밀번호 없이는 리포트 내용을 복호화할 수 없게 만드는 구조입니다.

## 다음 확장

- 카카오톡 전송은 Pages 주소가 안정화된 뒤 `오늘 요약 + 링크`를 보내는 방식으로 붙이는 것이 좋습니다.
- 더 강한 접근 제어가 필요하면 Cloudflare Access 같은 로그인 기반 보호를 별도로 붙입니다.
