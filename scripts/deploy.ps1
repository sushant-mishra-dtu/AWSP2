<#
.SYNOPSIS
  Build and deploy AirWindow to AWS (Lambda + API Gateway HTTP API + private S3 + CloudFront).

.EXAMPLE
  .\scripts\deploy.ps1                      # live mode, ap-south-1, stack "airwindow"
  .\scripts\deploy.ps1 -DataMode replay     # serve the labelled captured Delhi fixture
  $env:OPENAQ_API_KEY = "<key>"; .\scripts\deploy.ps1   # enable observed-station layer

  Requires: AWS CLI v2 with credentials, SAM CLI, Python 3.13, Node 20.19+/22.12+.
  No Docker needed: SAM downloads Linux wheels for the Lambda runtime.
#>
param(
  [string]$StackName = "airwindow",
  [string]$Region = "ap-south-1",
  [ValidateSet("live", "replay")][string]$DataMode = "live",
  [string]$Sam = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $Sam) {
  $local = Join-Path $root ".tools-venv\Scripts\sam.exe"
  $Sam = if (Test-Path $local) { $local } else { "sam" }
}
$env:SAM_CLI_TELEMETRY = "0"

Write-Host "== Checking AWS identity" -ForegroundColor Cyan
aws sts get-caller-identity --query "Arn" --output text
if ($LASTEXITCODE -ne 0) { throw "AWS credentials are not configured. Run 'aws configure' or 'aws login' first." }

Write-Host "== Building Lambda package (sam build)" -ForegroundColor Cyan
Push-Location (Join-Path $root "infra")
try {
  & $Sam build --template template.yaml
  if ($LASTEXITCODE -ne 0) { throw "sam build failed" }

  Write-Host "== Deploying stack $StackName to $Region" -ForegroundColor Cyan
  $overrides = @("DataMode=$DataMode")
  if ($env:OPENAQ_API_KEY) { $overrides += "OpenAqApiKey=$($env:OPENAQ_API_KEY)" }
  & $Sam deploy --stack-name $StackName --region $Region --resolve-s3 `
      --capabilities CAPABILITY_IAM --no-confirm-changeset --no-fail-on-empty-changeset `
      --parameter-overrides $overrides
  if ($LASTEXITCODE -ne 0) { throw "sam deploy failed" }
} finally { Pop-Location }

$outputs = aws cloudformation describe-stacks --stack-name $StackName --region $Region `
  --query "Stacks[0].Outputs" --output json | ConvertFrom-Json
$out = @{}; foreach ($o in $outputs) { $out[$o.OutputKey] = $o.OutputValue }

Write-Host "== Building frontend" -ForegroundColor Cyan
Push-Location (Join-Path $root "frontend")
try {
  if (-not (Test-Path node_modules)) { npm ci --no-audit --no-fund }
  $env:VITE_API_BASE = ""   # same origin: CloudFront routes /api/* to the HTTP API
  npm run build
  if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
} finally { Pop-Location }

Write-Host "== Uploading frontend to private bucket $($out.SiteBucketName)" -ForegroundColor Cyan
$dist = Join-Path $root "frontend\dist"
aws s3 sync "$dist\assets" "s3://$($out.SiteBucketName)/assets" --region $Region --delete `
  --cache-control "public,max-age=31536000,immutable"
aws s3 sync $dist "s3://$($out.SiteBucketName)" --region $Region --delete --exclude "assets/*" `
  --cache-control "no-cache"
aws cloudfront create-invalidation --distribution-id $out.DistributionId --paths "/" "/index.html" | Out-Null

Write-Host "== Smoke test" -ForegroundColor Cyan
$health = $null
for ($i = 0; $i -lt 30 -and -not $health; $i++) {
  try { $health = Invoke-RestMethod -Uri "$($out.SiteUrl)/api/health" -TimeoutSec 20 }
  catch { Start-Sleep -Seconds 10 }
}
if ($health) { Write-Host "API via CloudFront: status=$($health.status) mode=$($health.mode)" -ForegroundColor Green }
else { Write-Warning "CloudFront may still be propagating; retry $($out.SiteUrl)/api/health in a few minutes." }

Write-Host ""
Write-Host "App URL:      $($out.SiteUrl)" -ForegroundColor Green
Write-Host "API endpoint: $($out.ApiEndpoint)"
Write-Host "Function:     $($out.FunctionName)"
