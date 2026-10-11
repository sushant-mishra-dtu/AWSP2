<#
.SYNOPSIS
  Build and deploy AirWindow to AWS: Lambda (API + scheduled assessment), API Gateway HTTP API
  with Cognito JWT authorizer, DynamoDB, SNS, EventBridge Scheduler, private S3 (site + evidence),
  CloudFront, CloudWatch, optional AWS Budgets.

.EXAMPLE
  $env:AWS_PROFILE = "myprofile"
  .\scripts\deploy.ps1                                  # live data, ap-south-1, stack "airwindow"
  .\scripts\deploy.ps1 -DataMode replay -Replay synthetic   # labelled SYNTHETIC demo scenario
  .\scripts\deploy.ps1 -BudgetEmail me@example.org      # also create a monthly cost budget alert

  Optional secrets are read from the environment (never printed):
    NVIDIA_API_KEY (or backend/.env), OPENAQ_API_KEY
  Requires: AWS CLI v2 + credentials, SAM CLI (.tools-venv or PATH), Python 3.13, Node 22.12+.
#>
param(
  [string]$StackName = "airwindow",
  [string]$Region = "ap-south-1",
  [ValidateSet("live", "replay")][string]$DataMode = "live",
  [ValidateSet("real", "synthetic")][string]$Replay = "real",
  [string]$BudgetEmail = "",
  [string]$BedrockModelId = "",
  [string]$Sam = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $Sam) {
  $local = Join-Path $root ".tools-venv\Scripts\sam.exe"
  $Sam = if (Test-Path $local) { $local } else { "sam" }
}
$env:SAM_CLI_TELEMETRY = "0"

function Read-DotEnvValue([string]$name) {
  $f = Join-Path $root "backend\.env"
  if (Test-Path $f) {
    foreach ($line in Get-Content $f) { if ($line -match "^\s*$name\s*=\s*(.+)\s*$") { return $Matches[1].Trim('"', "'") } }
  }
  return ""
}

Write-Host "== Checking AWS identity" -ForegroundColor Cyan
aws sts get-caller-identity --query "Arn" --output text
if ($LASTEXITCODE -ne 0) { throw "AWS credentials are not configured. Run 'aws configure' or 'aws login' first." }
aws dynamodb list-tables --region $Region --max-items 1 --output text | Out-Null
if ($LASTEXITCODE -ne 0) { throw "This AWS account cannot use DynamoDB in $Region (not signed up / not activated?). Finish account activation first." }

Write-Host "== Staging clean Lambda source (no .env, no local data)" -ForegroundColor Cyan
$src = Join-Path $root "infra\.lambda-src"
if (Test-Path $src) { Remove-Item -Recurse -Force $src }
New-Item -ItemType Directory -Force $src | Out-Null
Copy-Item -Recurse (Join-Path $root "backend\app") $src
Copy-Item -Recurse (Join-Path $root "backend\fixtures") $src
Copy-Item (Join-Path $root "backend\requirements.txt") $src
Get-ChildItem -Recurse -Directory -Filter "__pycache__" $src | Remove-Item -Recurse -Force

$replayFile = if ($Replay -eq "synthetic") { "fixtures/scenario_delhi_synthetic.json" } else { "fixtures/replay_delhi.json" }
$nvidia = if ($env:NVIDIA_API_KEY) { $env:NVIDIA_API_KEY } else { Read-DotEnvValue "NVIDIA_API_KEY" }
$overrides = @("DataMode=$DataMode", "ReplayFile=$replayFile")
if ($nvidia) { $overrides += "NvidiaApiKey=$nvidia" }
if ($env:OPENAQ_API_KEY) { $overrides += "OpenAqApiKey=$($env:OPENAQ_API_KEY)" }
if ($BudgetEmail) { $overrides += "BudgetEmail=$BudgetEmail" }
if ($BedrockModelId) { $overrides += "BedrockModelId=$BedrockModelId" }

Push-Location (Join-Path $root "infra")
try {
  Write-Host "== sam build" -ForegroundColor Cyan
  & $Sam build --template template.yaml
  if ($LASTEXITCODE -ne 0) { throw "sam build failed" }
  Write-Host "== sam deploy ($StackName, $Region, DataMode=$DataMode)" -ForegroundColor Cyan
  & $Sam deploy --stack-name $StackName --region $Region --resolve-s3 --capabilities CAPABILITY_IAM `
      --no-confirm-changeset --no-fail-on-empty-changeset --parameter-overrides $overrides
  if ($LASTEXITCODE -ne 0) { throw "sam deploy failed" }

  $outputs = aws cloudformation describe-stacks --stack-name $StackName --region $Region --query "Stacks[0].Outputs" --output json | ConvertFrom-Json
  $out = @{}; foreach ($o in $outputs) { $out[$o.OutputKey] = $o.OutputValue }

  # Second pass only to put the public URL into warning emails (avoids a CloudFormation cycle).
  $current = aws lambda get-function-configuration --function-name $out.FunctionName --region $Region --query "Environment.Variables.APP_URL" --output text
  if ($current -ne $out.SiteUrl) {
    Write-Host "== sam deploy (set AppUrl)" -ForegroundColor Cyan
    & $Sam deploy --stack-name $StackName --region $Region --resolve-s3 --capabilities CAPABILITY_IAM `
        --no-confirm-changeset --no-fail-on-empty-changeset --parameter-overrides ($overrides + "AppUrl=$($out.SiteUrl)")
    if ($LASTEXITCODE -ne 0) { throw "sam deploy (AppUrl) failed" }
  }
} finally { Pop-Location }

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
aws s3 sync "$dist\assets" "s3://$($out.SiteBucketName)/assets" --region $Region --delete --cache-control "public,max-age=31536000,immutable"
aws s3 sync $dist "s3://$($out.SiteBucketName)" --region $Region --delete --exclude "assets/*" --cache-control "no-cache"
aws cloudfront create-invalidation --distribution-id $out.DistributionId --paths "/" "/index.html" | Out-Null

Write-Host "== Smoke test through CloudFront" -ForegroundColor Cyan
$rt = $null
for ($i = 0; $i -lt 30 -and -not $rt; $i++) {
  try { $rt = Invoke-RestMethod -Uri "$($out.SiteUrl)/api/runtime" -TimeoutSec 20 } catch { Start-Sleep -Seconds 10 }
}
if ($rt) {
  Write-Host ("runtime: mode={0} store={1} auth={2} notifier={3} evidence={4}" -f $rt.data_mode, $rt.store, $rt.auth, $rt.notifier, $rt.evidence) -ForegroundColor Green
  try { Invoke-RestMethod -Uri "$($out.SiteUrl)/api/orgs" -TimeoutSec 20 | Out-Null; Write-Warning "/api/orgs answered without a token!" }
  catch { Write-Host "unauthenticated /api/orgs -> $($_.Exception.Response.StatusCode.value__) (expected 401 from the Cognito JWT authorizer)" -ForegroundColor Green }
} else { Write-Warning "CloudFront may still be propagating; retry $($out.SiteUrl)/api/runtime in a few minutes." }

Write-Host ""
Write-Host "App URL:        $($out.SiteUrl)" -ForegroundColor Green
Write-Host "API endpoint:   $($out.ApiEndpoint)"
Write-Host "Functions:      $($out.FunctionName), $($out.AssessmentFunctionName)"
Write-Host "Table / Topic:  $($out.TableName) / $($out.TopicArn)"
Write-Host "Next: .\scripts\verify-aws.ps1 -StackName $StackName -Region $Region"
