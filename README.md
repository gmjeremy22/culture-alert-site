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

- `.github/workflows/daily-update.yml`은 매일 07:30 KST에 실행됩니다.
- GitHub Actions가 새 DB를 만들고, 공개 가능한 수집기 26개를 실행하고, 카드 HTML을 다시 만든 뒤 암호화해서 Pages에 배포합니다.
- 기본 실행에서는 느리고 실패 가능성이 큰 `official-page-monitor`를 제외합니다.
- 필요할 때만 workflow 환경변수 `CULTURE_ALERT_INCLUDE_OFFICIAL_MONITOR=1`로 켤 수 있습니다.

## 로컬에서 수동 게시

로컬 원본 프로젝트의 최신 HTML을 암호화해서 `public/index.html`을 만들고 싶을 때 사용합니다.

```powershell
$env:CULTURE_ALERT_SITE_PASSWORD="<비밀번호>"
.\tools\publish-local.ps1
```

## 로컬 검증

아래 명령은 임시 비밀번호로 암호화/복호화가 되는지 확인합니다. 이 비밀번호를 커밋하지 않습니다.

```powershell
$env:CULTURE_ALERT_SITE_PASSWORD="temporary-test-password"
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
