param(
  [string]$SourceOutputs = "..\culture-alert\outputs",
  [string]$DestinationOutputs = "automation\culture-alert\outputs"
)

$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Path $DestinationOutputs -Force | Out-Null

Get-ChildItem -Path $SourceOutputs -Filter "*.py" | ForEach-Object {
  Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $DestinationOutputs $_.Name) -Force
}

$safeDataFiles = @(
  "culture-alert-schema.sql",
  "institutions-seed.csv",
  "interests-seed.csv",
  "expanded-institution-candidates.csv"
)

foreach ($name in $safeDataFiles) {
  Copy-Item -LiteralPath (Join-Path $SourceOutputs $name) -Destination (Join-Path $DestinationOutputs $name) -Force
}

Write-Host "Staged cloud source files in $DestinationOutputs"
