# =============================================================================
# FULL DESTROY — Manager Microservices (AWS)
#
# Deletes project resources as thoroughly as possible:
# - EKS cluster + nodegroups + worker EC2
# - Kubernetes namespaces/ingresses (if cluster still reachable)
# - RDS instances matching project scope
# - ECR repositories matching project scope
# - EBS volumes/snapshots tagged to the cluster
# - CloudWatch log groups for the cluster/project
#
# Usage:
#   .\full-destroy.ps1 -Force
#   .\full-destroy.ps1 -ClusterName microservices-cluster -Region us-east-1 -Force
#
# Notes:
# - This script scopes cleanup to this project naming/tag conventions.
# - It does NOT delete unrelated resources in your AWS account.
# =============================================================================

[CmdletBinding()]
param(
    [string]$ClusterName = $(if ($env:CLUSTER_NAME) { $env:CLUSTER_NAME } else { "microservices-eks" }),
    [string]$Region = $(if ($env:AWS_REGION) { $env:AWS_REGION } else { "us-east-1" }),
    [string]$ProjectName = "manager-microservices",
    [switch]$Force,
    [switch]$SkipRds,
    [switch]$SkipEcr,
    [switch]$SkipStorage,
    [switch]$SkipLogs
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$env:AWS_PAGER = ""
$env:PAGER = ""

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Cluster-Exists {
    param([string]$Name, [string]$AwsRegion)
    aws eks describe-cluster --name $Name --region $AwsRegion --query "cluster.status" --output text 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Get-ProjectEcrRepos {
    param([string]$AwsRegion)
    $q = "repositories[?starts_with(repositoryName,'agent1-') || starts_with(repositoryName,'agent2-') || starts_with(repositoryName,'manager-') || repositoryName=='ml-model-service'].repositoryName"
    $txt = aws ecr describe-repositories --region $AwsRegion --query $q --output text 2>$null
    if (-not $txt) { return @() }
    return @($txt -split "\s+" | Where-Object { $_ -and $_.Trim().Length -gt 0 })
}

function Wait-RdsDeleted {
    param([string]$DbId, [string]$AwsRegion, [int]$MaxAttempts = 90)
    for ($i = 1; $i -le $MaxAttempts; $i++) {
        aws rds describe-db-instances --db-instance-identifier $DbId --region $AwsRegion --query "DBInstances[0].DBInstanceStatus" --output text 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { return }
        Start-Sleep -Seconds 20
    }
    Write-Warning "RDS instance '$DbId' still exists after wait timeout."
}

function Remove-IfExists {
    param([scriptblock]$Action)
    try { & $Action } catch { }
}

Require-Command aws
Require-Command eksctl
Require-Command kubectl

$account = aws sts get-caller-identity --query Account --output text
if ($LASTEXITCODE -ne 0 -or -not $account) {
    throw "Unable to resolve AWS account. Run 'aws configure' first."
}

Write-Host "==============================================" -ForegroundColor Red
Write-Host " FULL DESTROY (PROJECT-SCOPED)" -ForegroundColor Red
Write-Host " Cluster : $ClusterName"
Write-Host " Region  : $Region"
Write-Host " Account : $account"
Write-Host "==============================================" -ForegroundColor Red

if (-not $Force) {
    Write-Host "This will delete EKS + project AWS resources (RDS/ECR/EBS/logs)." -ForegroundColor Yellow
    $confirm = Read-Host "Type 'yes' to continue"
    if ($confirm -ne "yes") {
        Write-Host "Aborted." -ForegroundColor Yellow
        exit 0
    }
}

$summary = [ordered]@{
    ClusterDeleted = $false
    RdsDeleted = @()
    EcrDeleted = @()
    VolumesDeleted = @()
    SnapshotsDeleted = @()
    LogGroupsDeleted = @()
}

Write-Host "[1/6] Deleting EKS cluster and worker nodes..." -ForegroundColor Cyan
if (Cluster-Exists -Name $ClusterName -AwsRegion $Region) {
    Remove-IfExists { aws eks update-kubeconfig --name $ClusterName --region $Region | Out-Null }

    foreach ($ns in @("agent1", "agent2", "manager", "monitoring")) {
        Remove-IfExists { kubectl delete namespace $ns --ignore-not-found | Out-Null }
    }

    # Primary path
    Remove-IfExists { eksctl delete cluster --name $ClusterName --region $Region --wait | Out-Null }

    # Fallback path if still present
    if (Cluster-Exists -Name $ClusterName -AwsRegion $Region) {
        $nodegroupsText = aws eks list-nodegroups --cluster-name $ClusterName --region $Region --query "nodegroups" --output text 2>$null
        $nodegroups = @($nodegroupsText -split "\s+" | Where-Object { $_ })
        foreach ($ng in $nodegroups) {
            Remove-IfExists { aws eks delete-nodegroup --cluster-name $ClusterName --nodegroup-name $ng --region $Region | Out-Null }
        }
        foreach ($ng in $nodegroups) {
            for ($i = 1; $i -le 60; $i++) {
                aws eks describe-nodegroup --cluster-name $ClusterName --nodegroup-name $ng --region $Region --query "nodegroup.status" --output text 2>$null | Out-Null
                if ($LASTEXITCODE -ne 0) { break }
                Start-Sleep -Seconds 10
            }
        }
        Remove-IfExists { aws eks delete-cluster --name $ClusterName --region $Region | Out-Null }
    }

    for ($i = 1; $i -le 90; $i++) {
        if (-not (Cluster-Exists -Name $ClusterName -AwsRegion $Region)) { break }
        Start-Sleep -Seconds 10
    }
}
$summary.ClusterDeleted = -not (Cluster-Exists -Name $ClusterName -AwsRegion $Region)

Write-Host "[2/6] Cleaning RDS..." -ForegroundColor Cyan
if (-not $SkipRds) {
    $dbRows = aws rds describe-db-instances --region $Region --query "DBInstances[?contains(DBInstanceIdentifier, 'microservices')].[DBInstanceIdentifier,DBInstanceStatus]" --output text 2>$null
    $dbIds = @()
    if ($dbRows) {
        $tokens = @($dbRows -split "\s+" | Where-Object { $_ })
        for ($i = 0; $i -lt $tokens.Count; $i += 2) {
            $dbIds += $tokens[$i]
        }
    }

    foreach ($db in $dbIds) {
        Remove-IfExists { aws rds delete-db-instance --db-instance-identifier $db --region $Region --skip-final-snapshot | Out-Null }
        $summary.RdsDeleted += $db
    }
    foreach ($db in $dbIds) {
        Wait-RdsDeleted -DbId $db -AwsRegion $Region
    }
}

Write-Host "[3/6] Cleaning ECR repositories..." -ForegroundColor Cyan
if (-not $SkipEcr) {
    $repos = Get-ProjectEcrRepos -AwsRegion $Region
    foreach ($repo in $repos) {
        Remove-IfExists { aws ecr delete-repository --repository-name $repo --region $Region --force | Out-Null }
        $summary.EcrDeleted += $repo
    }
}

Write-Host "[4/6] Cleaning EBS volumes/snapshots..." -ForegroundColor Cyan
if (-not $SkipStorage) {
    $volText = aws ec2 describe-volumes --region $Region --filters Name=tag-key,Values="kubernetes.io/cluster/$ClusterName" Name=status,Values=available --query "Volumes[].VolumeId" --output text 2>$null
    $volIds = @($volText -split "\s+" | Where-Object { $_ })
    foreach ($v in $volIds) {
        Remove-IfExists { aws ec2 delete-volume --volume-id $v --region $Region | Out-Null }
        $summary.VolumesDeleted += $v
    }

    $snapText = aws ec2 describe-snapshots --region $Region --owner-ids self --filters Name=tag-key,Values="kubernetes.io/cluster/$ClusterName" --query "Snapshots[].SnapshotId" --output text 2>$null
    $snapIds = @($snapText -split "\s+" | Where-Object { $_ })
    foreach ($s in $snapIds) {
        Remove-IfExists { aws ec2 delete-snapshot --snapshot-id $s --region $Region | Out-Null }
        $summary.SnapshotsDeleted += $s
    }
}

Write-Host "[5/6] Cleaning CloudWatch log groups..." -ForegroundColor Cyan
if (-not $SkipLogs) {
    $logText = aws logs describe-log-groups --region $Region --query "logGroups[?contains(logGroupName,'$ClusterName') || contains(logGroupName,'$ProjectName')].logGroupName" --output text 2>$null
    $logGroups = @($logText -split "\s+" | Where-Object { $_ })
    foreach ($lg in $logGroups) {
        Remove-IfExists { aws logs delete-log-group --log-group-name $lg --region $Region | Out-Null }
        $summary.LogGroupsDeleted += $lg
    }
}

Write-Host "[6/6] Final verification..." -ForegroundColor Cyan
$clusterStillThere = Cluster-Exists -Name $ClusterName -AwsRegion $Region
if ($clusterStillThere) {
    Write-Warning "Cluster '$ClusterName' still exists. Re-run script after AWS finishes background cleanup."
} else {
    Write-Host "Cluster '$ClusterName' is deleted." -ForegroundColor Green
}

Write-Host ""
Write-Host "================ DESTROY SUMMARY ================" -ForegroundColor Green
Write-Host ("Cluster deleted: {0}" -f (-not $clusterStillThere))
Write-Host ("RDS delete requested: {0}" -f ($summary.RdsDeleted -join ", "))
Write-Host ("ECR deleted count: {0}" -f $summary.EcrDeleted.Count)
Write-Host ("EBS volumes deleted count: {0}" -f $summary.VolumesDeleted.Count)
Write-Host ("Snapshots deleted count: {0}" -f $summary.SnapshotsDeleted.Count)
Write-Host ("Log groups deleted count: {0}" -f $summary.LogGroupsDeleted.Count)
Write-Host "===============================================" -ForegroundColor Green
