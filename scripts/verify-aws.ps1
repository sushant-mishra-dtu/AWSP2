<#
.SYNOPSIS
  Collect real AWS evidence after deploy.ps1: invoke the scheduled-assessment Lambda twice
  (second run must create 0 duplicate alerts), count DynamoDB records by type, list SNS
  subscription states (pending vs confirmed), show recent CloudWatch log lines and the
  EventBridge Scheduler schedule. Prints no secrets.
#>
param([string]$StackName = "airwindow", [string]$Region = "ap-south-1")
$ErrorActionPreference = "Stop"
$outputs = aws cloudformation describe-stacks --stack-name $StackName --region $Region --query "Stacks[0].Outputs" --output json | ConvertFrom-Json
$out = @{}; foreach ($o in $outputs) { $out[$o.OutputKey] = $o.OutputValue }
$tmp = Join-Path ([IO.Path]::GetTempPath()) "airwindow-verify"
New-Item -ItemType Directory -Force $tmp | Out-Null

foreach ($n in 1, 2) {
  Write-Host "== Invoke $($out.AssessmentFunctionName) (run $n, same path as the schedule)" -ForegroundColor Cyan
  $f = Join-Path $tmp "assess-$n.json"
  aws lambda invoke --function-name $out.AssessmentFunctionName --region $Region --cli-binary-format raw-in-base64-out `
    --payload '{"source":"verify-aws.ps1"}' $f | Out-Null
  $r = Get-Content $f -Raw | ConvertFrom-Json
  foreach ($x in $r.results) {
    Write-Host ("  org {0}: assessed={1} alerts_created={2} duplicates_skipped={3} notifications={4}" -f $x.org_id, $x.assessed, $x.alerts_created, $x.duplicates_skipped, ($x.notifications | ConvertTo-Json -Compress))
  }
}

Write-Host "== DynamoDB records by type ($($out.TableName))" -ForegroundColor Cyan
$items = aws dynamodb scan --table-name $out.TableName --region $Region --projection-expression "#t" --expression-attribute-names '{\"#t\":\"type\"}' --output json | ConvertFrom-Json
$items.Items | ForEach-Object { $_.type.S } | Group-Object | ForEach-Object { Write-Host ("  {0,-18} {1}" -f $_.Name, $_.Count) }

Write-Host "== SNS subscriptions on $($out.TopicArn)" -ForegroundColor Cyan
$subs = aws sns list-subscriptions-by-topic --topic-arn $out.TopicArn --region $Region --output json | ConvertFrom-Json
foreach ($s in $subs.Subscriptions) {
  $state = if ($s.SubscriptionArn -like "PendingConfirmation*") { "pending confirmation" } else { "confirmed" }
  $masked = ($s.Endpoint -replace '^(.{2}).*@', '$1***@')
  Write-Host "  $($s.Protocol) $masked : $state"
}

Write-Host "== EventBridge Scheduler" -ForegroundColor Cyan
aws scheduler list-schedules --region $Region --query "Schedules[?contains(Name, '$StackName')].[Name,State]" --output text

Write-Host "== Recent assessment log lines" -ForegroundColor Cyan
aws logs tail "/aws/lambda/$($out.AssessmentFunctionName)" --region $Region --since 15m --format short | Select-String "scheduled_assessment|AlertsCreated" | Select-Object -Last 6
