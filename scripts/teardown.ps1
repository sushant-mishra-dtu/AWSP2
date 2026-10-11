<#
.SYNOPSIS
  Remove every AirWindow AWS resource created by deploy.ps1.

  WARNING: deletes the DynamoDB table (organisations, activities, actions, alerts, reports),
  the Cognito user pool (all coordinator accounts), the SNS topic (and its subscriptions),
  the report-evidence bucket and the site bucket. Export anything you need first.

  Buckets are emptied first because CloudFormation cannot delete non-empty buckets.
  SAM's shared artifact bucket (aws-sam-cli-managed-default) is left in place.
#>
param(
  [string]$StackName = "airwindow",
  [string]$Region = "ap-south-1",
  [string]$Sam = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $Sam) {
  $local = Join-Path $root ".tools-venv\Scripts\sam.exe"
  $Sam = if (Test-Path $local) { $local } else { "sam" }
}
$env:SAM_CLI_TELEMETRY = "0"

foreach ($key in "SiteBucketName", "EvidenceBucketName") {
  $bucket = aws cloudformation describe-stacks --stack-name $StackName --region $Region `
    --query "Stacks[0].Outputs[?OutputKey=='$key'].OutputValue" --output text 2>$null
  if ($LASTEXITCODE -eq 0 -and $bucket -and $bucket -ne "None") {
    Write-Host "Emptying s3://$bucket" -ForegroundColor Cyan
    aws s3 rm "s3://$bucket" --recursive --region $Region
  }
}
Write-Host "Deleting stack $StackName (CloudFront deletion can take several minutes)" -ForegroundColor Cyan
& $Sam delete --stack-name $StackName --region $Region --no-prompts
