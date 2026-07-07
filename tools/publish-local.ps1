param(
  [string]$SourceHtml = "..\culture-alert\outputs\keyword-recommendation-report.html",
  [string]$OutputHtml = "public\index.html"
)

$ErrorActionPreference = "Stop"

if (-not $env:CULTURE_ALERT_SITE_PASSWORD) {
  throw "CULTURE_ALERT_SITE_PASSWORD 환경변수에 게시 비밀번호를 넣어주세요."
}

$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCommand) {
  $node = $nodeCommand.Source
} else {
  $codexNode = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
  if (-not (Test-Path $codexNode)) {
    throw "Node.js를 찾지 못했습니다. Codex 런타임 또는 Node.js 설치를 확인해주세요."
  }
  $node = $codexNode
}

& $node ".\tools\build-protected-site.js" --input $SourceHtml --output $OutputHtml
& $node ".\tools\verify-protected-site.js" --html $OutputHtml --leak "국립중앙박물관" --leak "feature-card"
