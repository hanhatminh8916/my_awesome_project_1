# =============================================================================
# FULL CREATE — Manager Microservices (AWS)
#
# End-to-end provisioning script:
# 1) Create EKS cluster + managed nodegroup (if missing)
# 2) Enable OIDC, EBS CSI add-on, AWS Load Balancer Controller
# 3) Create namespaces + IRSA service accounts
# 4) (Optional) Create RDS PostgreSQL and initialize databases
# 5) Build and push all app images to ECR
# 6) Deploy all Kubernetes manifests (agent1/agent2/manager/ml-model)
# 7) Optionally deploy monitoring stack
#
# Usage (example):
#   .\full-create.ps1 -DbUsername masteruser -DbPassword 'YourStrongPass123!' -ImageTag v1.0.0
#
# =============================================================================

[CmdletBinding()]
param(
    [string]$ClusterName = $(if ($env:CLUSTER_NAME) { $env:CLUSTER_NAME } else { "microservices-eks" }),
    [string]$Region = $(if ($env:AWS_REGION) { $env:AWS_REGION } else { "us-east-1" }),
    [string]$K8sVersion = "1.33",
    [string]$GeneralNodegroupName = "standard-workers",
    [string]$GeneralNodeType = "t3.micro",
    [int]$GeneralNodeMin = 4,
    [int]$GeneralNodeMax = 4,
    [int]$GeneralNodeDesired = 4,
    [string]$WorkloadNodegroupName = "m7i-flex-large",
    [string]$WorkloadNodeType = "m7i.large",
    [int]$WorkloadNodeMin = 2,
    [int]$WorkloadNodeMax = 2,
    [int]$WorkloadNodeDesired = 2,
    [string]$ImageTag = $(if ($env:IMAGE_TAG) { $env:IMAGE_TAG } else { "latest" }),
    [switch]$SkipMonitoring,
    [switch]$SkipBuildPush,
    [switch]$SkipRds,
    [switch]$UsePostgresImage,
    [string]$PostgresNamespace = "default",
    [string]$PostgresServiceName = "postgres",
    [string]$PostgresStorageClass = "gp3-encrypted",
    [string]$PostgresStorageSize = "20Gi",
    [string]$DbInstanceId = "microservices-db",
    [string]$DbUsername = $(if ($env:DB_USERNAME) { $env:DB_USERNAME } else { "masteruser" }),
    [string]$DbPassword = $(if ($env:DB_PASSWORD) { $env:DB_PASSWORD } else { "" }),
    [string]$DbInstanceClass = "db.t4g.micro",
    [int]$DbAllocatedStorage = 20,
    [switch]$Force
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

function Ensure-EbsCsiAddon {
    param([string]$ClusterName, [string]$AwsRegion)

    aws eks describe-addon --cluster-name $ClusterName --addon-name aws-ebs-csi-driver --region $AwsRegion --query "addon.status" --output text 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        aws eks create-addon --cluster-name $ClusterName --addon-name aws-ebs-csi-driver --region $AwsRegion | Out-Null
    } else {
        aws eks update-addon --cluster-name $ClusterName --addon-name aws-ebs-csi-driver --region $AwsRegion --resolve-conflicts OVERWRITE 2>$null | Out-Null
    }

    aws eks wait addon-active --cluster-name $ClusterName --addon-name aws-ebs-csi-driver --region $AwsRegion
}

function Cluster-Exists {
    param([string]$Name, [string]$AwsRegion)
    aws eks describe-cluster --name $Name --region $AwsRegion --query "cluster.status" --output text 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Ensure-ManagedNodegroup {
    param(
        [string]$ClusterName,
        [string]$AwsRegion,
        [string]$NodegroupName,
        [string]$NodeType,
        [int]$NodeMin,
        [int]$NodeMax,
        [int]$NodeDesired,
        [string]$K8sVersion
    )

    $existingNodegroupsText = aws eks list-nodegroups --cluster-name $ClusterName --region $AwsRegion --output text 2>$null
    $existingNodegroups = @($existingNodegroupsText -split "\s+" | Where-Object { $_ })
    if ($existingNodegroups -contains $NodegroupName) {
        $desc = aws eks describe-nodegroup --cluster-name $ClusterName --nodegroup-name $NodegroupName --region $AwsRegion --output json | ConvertFrom-Json
        $current = $desc.nodegroup.scalingConfig
        if (($current.desiredSize -ne $NodeDesired) -or ($current.minSize -ne $NodeMin) -or ($current.maxSize -ne $NodeMax)) {
            $scalingArg = "minSize=$NodeMin,maxSize=$NodeMax,desiredSize=$NodeDesired"
            aws eks update-nodegroup-config `
                --cluster-name $ClusterName `
                --nodegroup-name $NodegroupName `
                --region $AwsRegion `
                --scaling-config $scalingArg | Out-Null
            aws eks wait nodegroup-active --cluster-name $ClusterName --nodegroup-name $NodegroupName --region $AwsRegion
        }
        return
    }

    eksctl create nodegroup `
        --cluster $ClusterName `
        --name $NodegroupName `
        --region $AwsRegion `
        --node-type $NodeType `
        --nodes-min $NodeMin `
        --nodes-max $NodeMax `
        --nodes $NodeDesired `
        --managed `
        --asg-access `
        --full-ecr-access | Out-Null
}

function Ensure-EcrRepo {
    param([string]$RepositoryName, [string]$AwsRegion)
    aws ecr describe-repositories --repository-names $RepositoryName --region $AwsRegion 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        aws ecr create-repository --repository-name $RepositoryName --region $AwsRegion --image-scanning-configuration scanOnPush=true --encryption-configuration encryptionType=AES256 | Out-Null
    }
}

function Apply-SubstitutedManifest {
    param(
        [string]$SourceFile,
        [string]$TempDir,
        [string]$EcrRegistry,
        [string]$ImgTag,
        [string]$RdsEndpoint,
        [string]$AwsAccount,
        [string]$EksClusterName
    )

    $content = Get-Content $SourceFile -Raw
    $content = $content `
        -replace '<ECR_REGISTRY>', $EcrRegistry `
        -replace '<IMAGE_TAG>', $ImgTag `
        -replace '<RDS_ENDPOINT>', $RdsEndpoint `
        -replace '<AWS_ACCOUNT_ID>', $AwsAccount `
        -replace '<EKS_CLUSTER_NAME>', $EksClusterName

    # Force requested image tag where manifests still use latest.
    $content = $content -replace ':latest(\b)', ":$ImgTag`$1"

    $tmpFile = Join-Path $TempDir (Split-Path $SourceFile -Leaf)
    $content | Set-Content -Path $tmpFile -Encoding UTF8
    kubectl apply --validate=false -f $tmpFile | Out-Null
}

function Wait-Deployment {
    param([string]$Name, [string]$Namespace)
    kubectl rollout status "deployment/$Name" -n $Namespace --timeout=240s | Out-Null
}

function Ensure-LbController {
    param([string]$EksCluster, [string]$AwsRegion, [string]$AwsAccount)

    $policyName = "AWSLoadBalancerControllerIAMPolicy"
    $policyArn = aws iam list-policies --scope Local --query "Policies[?PolicyName=='$policyName'] | [0].Arn" --output text 2>$null
    if (-not $policyArn -or $policyArn -eq "None") {
        $policyDoc = (Invoke-WebRequest -Uri "https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/v2.7.2/docs/install/iam_policy.json" -UseBasicParsing).Content
        $tmp = Join-Path $env:TEMP ("alb-policy-" + [Guid]::NewGuid().ToString() + ".json")
        $policyDoc | Set-Content -Path $tmp -Encoding UTF8
        aws iam create-policy --policy-name $policyName --policy-document "file://$tmp" 2>$null | Out-Null
        $policyArn = aws iam list-policies --scope Local --query "Policies[?PolicyName=='$policyName'] | [0].Arn" --output text
        Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    }
    if (-not $policyArn -or $policyArn -eq "None") {
        throw "Unable to resolve IAM policy ARN for $policyName"
    }

    helm repo add eks https://aws.github.io/eks-charts | Out-Null
    helm repo update | Out-Null

    $helmStatusRaw = helm status aws-load-balancer-controller -n kube-system -o json 2>$null
    if ($LASTEXITCODE -eq 0 -and $helmStatusRaw) {
        $helmStatus = ($helmStatusRaw | ConvertFrom-Json).info.status
        if ($helmStatus -like "pending*") {
            helm uninstall aws-load-balancer-controller -n kube-system | Out-Null
        }
    }

    kubectl delete mutatingwebhookconfiguration aws-load-balancer-webhook --ignore-not-found | Out-Null
    kubectl delete validatingwebhookconfiguration aws-load-balancer-webhook --ignore-not-found | Out-Null
    kubectl delete secret aws-load-balancer-webhook-tls -n kube-system --ignore-not-found | Out-Null
    kubectl delete secret aws-load-balancer-tls -n kube-system --ignore-not-found | Out-Null

    helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller `
        --namespace kube-system `
        --set clusterName=$EksCluster `
        --set serviceAccount.create=true `
        --set serviceAccount.name=aws-load-balancer-controller `
        --set region=$AwsRegion `
        --timeout 10m `
        --wait | Out-Null

    kubectl rollout status deployment/aws-load-balancer-controller -n kube-system --timeout=600s | Out-Null
}

function Ensure-NodeRolePolicy {
    param(
        [string]$RoleArn,
        [string]$PolicyArn
    )

    if (-not $RoleArn -or $RoleArn -eq "None") {
        throw "Node role ARN is not available."
    }
    $roleName = ($RoleArn -split "/")[-1]
    $attached = aws iam list-attached-role-policies --role-name $roleName --query "AttachedPolicies[?PolicyArn=='$PolicyArn'] | [0].PolicyArn" --output text 2>$null
    if (-not $attached -or $attached -eq "None") {
        aws iam attach-role-policy --role-name $roleName --policy-arn $PolicyArn | Out-Null
    }
}

function Get-PolicyArnByName {
    param([string]$PolicyName)

    $arn = aws iam list-policies --scope Local --query "Policies[?PolicyName=='$PolicyName'] | [0].Arn" --output text 2>$null
    if (-not $arn -or $arn -eq "None") {
        $arn = aws iam list-policies --scope AWS --query "Policies[?PolicyName=='$PolicyName'] | [0].Arn" --output text 2>$null
    }
    if (-not $arn -or $arn -eq "None") {
        return $null
    }
    return [string]$arn
}

function Ensure-ClusterNodegroupPolicies {
    param(
        [string]$ClusterName,
        [string]$AwsRegion,
        [string[]]$PolicyArns
    )

    $nodegroupsText = aws eks list-nodegroups --cluster-name $ClusterName --region $AwsRegion --output text 2>$null
    $nodegroups = @($nodegroupsText -split "\s+" | Where-Object { $_ })

    foreach ($ng in $nodegroups) {
        $roleArn = aws eks describe-nodegroup --cluster-name $ClusterName --nodegroup-name $ng --region $AwsRegion --query "nodegroup.nodeRole" --output text 2>$null
        if ($roleArn -and $roleArn -ne "None") {
            foreach ($policyArn in $PolicyArns) {
                Ensure-NodeRolePolicy -RoleArn $roleArn -PolicyArn $policyArn
            }
        }
    }
}

function Ensure-RdsAndInitDatabases {
    param(
        [string]$EksCluster,
        [string]$AwsRegion,
        [string]$InstanceId,
        [string]$MasterUsername,
        [string]$MasterPassword,
        [string]$InstanceClass,
        [int]$StorageGb,
        [string]$K8sRoot
    )

    if (-not $MasterPassword) {
        throw "DbPassword is required when -SkipRds is not set."
    }

    $vpcId = aws eks describe-cluster --name $EksCluster --region $AwsRegion --query "cluster.resourcesVpcConfig.vpcId" --output text
    if (-not $vpcId) { throw "Unable to detect VPC from EKS cluster." }

    $subnetsText = aws ec2 describe-subnets --region $AwsRegion --filters "Name=vpc-id,Values=$vpcId" "Name=mapPublicIpOnLaunch,Values=false" --query "Subnets[*].SubnetId" --output text
    $subnets = @($subnetsText -split "\s+" | Where-Object { $_ })
    if ($subnets.Count -eq 0) { throw "No private subnets found for VPC $vpcId." }

    $subnetGroup = "microservices-db-subnet-group"
    aws rds describe-db-subnet-groups --db-subnet-group-name $subnetGroup --region $AwsRegion 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        aws rds create-db-subnet-group --db-subnet-group-name $subnetGroup --db-subnet-group-description "Subnet group for microservices DB" --subnet-ids $subnets --region $AwsRegion | Out-Null
    } else {
        aws rds modify-db-subnet-group --db-subnet-group-name $subnetGroup --subnet-ids $subnets --region $AwsRegion | Out-Null
    }

    $sgName = "microservices-rds-sg"
    $sgId = aws ec2 describe-security-groups --region $AwsRegion --filters "Name=group-name,Values=$sgName" "Name=vpc-id,Values=$vpcId" --query "SecurityGroups[0].GroupId" --output text 2>$null
    if (-not $sgId -or $sgId -eq "None") {
        $sgId = aws ec2 create-security-group --group-name $sgName --description "Allow PostgreSQL from VPC" --vpc-id $vpcId --region $AwsRegion --query "GroupId" --output text
        $vpcCidr = aws ec2 describe-vpcs --vpc-ids $vpcId --region $AwsRegion --query "Vpcs[0].CidrBlock" --output text
        aws ec2 authorize-security-group-ingress --group-id $sgId --protocol tcp --port 5432 --cidr $vpcCidr --region $AwsRegion | Out-Null
    }

    aws rds describe-db-instances --db-instance-identifier $InstanceId --region $AwsRegion 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        aws rds create-db-instance `
            --db-instance-identifier $InstanceId `
            --db-instance-class $InstanceClass `
            --engine postgres `
            --engine-version 16.3 `
            --master-username $MasterUsername `
            --master-user-password $MasterPassword `
            --db-name postgres `
            --allocated-storage $StorageGb `
            --storage-type gp3 `
            --no-publicly-accessible `
            --vpc-security-group-ids $sgId `
            --db-subnet-group-name $subnetGroup `
            --backup-retention-period 1 `
            --no-multi-az `
            --region $AwsRegion | Out-Null
    }

    aws rds wait db-instance-available --db-instance-identifier $InstanceId --region $AwsRegion
    $endpoint = aws rds describe-db-instances --db-instance-identifier $InstanceId --region $AwsRegion --query "DBInstances[0].Endpoint.Address" --output text

    $jobTemplate = Join-Path $K8sRoot "jobs\init-databases-job.yaml"
    $jobContent = Get-Content $jobTemplate -Raw
    $jobContent = $jobContent -replace '<RDS_ENDPOINT>', $endpoint -replace '<DB_USERNAME>', $MasterUsername -replace '<DB_PASSWORD>', $MasterPassword
    $tmpJob = Join-Path $env:TEMP ("init-databases-" + [Guid]::NewGuid().ToString() + ".yaml")
    $jobContent | Set-Content -Path $tmpJob -Encoding UTF8

    kubectl delete job init-databases -n default --ignore-not-found | Out-Null
    kubectl apply -f $tmpJob | Out-Null
    kubectl wait job/init-databases -n default --for=condition=complete --timeout=240s | Out-Null
    Remove-Item $tmpJob -Force -ErrorAction SilentlyContinue

    return $endpoint
}

function Ensure-InClusterPostgresAndInitDatabases {
        param(
                [string]$Namespace,
                [string]$ServiceName,
                [string]$StorageClass,
                [string]$StorageSize,
                [string]$MasterUsername,
                [string]$MasterPassword,
                [string]$K8sRoot
        )

        if (-not $MasterPassword) {
                throw "DbPassword is required when using -UsePostgresImage."
        }

        kubectl create namespace $Namespace --dry-run=client -o yaml | kubectl apply -f - | Out-Null

        kubectl delete deployment postgres -n $Namespace --ignore-not-found | Out-Null
        kubectl delete service $ServiceName -n $Namespace --ignore-not-found | Out-Null
        kubectl delete pvc postgres-pvc -n $Namespace --ignore-not-found | Out-Null

        kubectl get storageclass $StorageClass 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
                $StorageClass = "ebs-gp3"
        }

        $postgresManifestLines = @(
            "apiVersion: v1",
            "kind: PersistentVolumeClaim",
            "metadata:",
            "  name: postgres-pvc",
            "  namespace: $Namespace",
            "spec:",
            "  accessModes:",
            "    - ReadWriteOnce",
            "  storageClassName: $StorageClass",
            "  resources:",
            "    requests:",
            "      storage: $StorageSize",
            "---",
            "apiVersion: apps/v1",
            "kind: Deployment",
            "metadata:",
            "  name: postgres",
            "  namespace: $Namespace",
            "spec:",
            "  replicas: 1",
            "  selector:",
            "    matchLabels:",
            "      app: postgres",
            "  template:",
            "    metadata:",
            "      labels:",
            "        app: postgres",
            "    spec:",
            "      containers:",
            "        - name: postgres",
            "          image: postgres:16",
            "          ports:",
            "            - containerPort: 5432",
            "          env:",
            "            - name: POSTGRES_USER",
            "              value: `"$MasterUsername`"",
            "            - name: POSTGRES_PASSWORD",
            "              value: `"$MasterPassword`"",
            "            - name: POSTGRES_DB",
            "              value: `"postgres`"",
            "            - name: PGDATA",
            "              value: `"/var/lib/postgresql/data/pgdata`"",
            "          volumeMounts:",
            "            - name: postgres-data",
            "              mountPath: /var/lib/postgresql/data",
            "          readinessProbe:",
            "            tcpSocket:",
            "              port: 5432",
            "            initialDelaySeconds: 10",
            "            periodSeconds: 5",
            "          livenessProbe:",
            "            tcpSocket:",
            "              port: 5432",
            "            initialDelaySeconds: 20",
            "            periodSeconds: 10",
            "      volumes:",
            "        - name: postgres-data",
            "          persistentVolumeClaim:",
            "            claimName: postgres-pvc",
            "---",
            "apiVersion: v1",
            "kind: Service",
            "metadata:",
            "  name: $ServiceName",
            "  namespace: $Namespace",
            "spec:",
            "  selector:",
            "    app: postgres",
            "  ports:",
            "    - name: postgres",
            "      protocol: TCP",
            "      port: 5432",
            "      targetPort: 5432"
        )
        $postgresManifest = [string]::Join("`n", $postgresManifestLines)

        $tmpManifest = Join-Path $env:TEMP ("postgres-incluster-" + [Guid]::NewGuid().ToString() + ".yaml")
        $postgresManifest | Set-Content -Path $tmpManifest -Encoding UTF8
        kubectl apply -f $tmpManifest | Out-Null
        Remove-Item $tmpManifest -Force -ErrorAction SilentlyContinue

        kubectl rollout status deployment/postgres -n $Namespace --timeout=300s | Out-Null

        $endpoint = "$ServiceName.$Namespace.svc.cluster.local"
        $jobTemplate = Join-Path $K8sRoot "jobs\init-databases-job.yaml"
        $jobContent = Get-Content $jobTemplate -Raw
        $jobContent = $jobContent -replace '<RDS_ENDPOINT>', $endpoint -replace '<DB_USERNAME>', $MasterUsername -replace '<DB_PASSWORD>', $MasterPassword
        $tmpJob = Join-Path $env:TEMP ("init-databases-" + [Guid]::NewGuid().ToString() + ".yaml")
        $jobContent | Set-Content -Path $tmpJob -Encoding UTF8

        kubectl delete job init-databases -n default --ignore-not-found | Out-Null
        kubectl apply -f $tmpJob | Out-Null
        kubectl wait job/init-databases -n default --for=condition=complete --timeout=600s | Out-Null
        Remove-Item $tmpJob -Force -ErrorAction SilentlyContinue

        return $endpoint
}

Require-Command aws
Require-Command eksctl
Require-Command kubectl
Require-Command helm
if (-not $SkipBuildPush) {
    Require-Command docker
}

$workspaceRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$k8sRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$dockerfileSpring = Join-Path $workspaceRoot "infra\docker\Dockerfile.spring-boot"
$dockerfileMl = Join-Path $workspaceRoot "infra\ml-model\Dockerfile"

$awsAccountId = aws sts get-caller-identity --query Account --output text
if (-not $awsAccountId) { throw "Unable to resolve AWS account." }
$ecrRegistry = "$awsAccountId.dkr.ecr.$Region.amazonaws.com"

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host " FULL CREATE (END-TO-END)" -ForegroundColor Cyan
Write-Host " Cluster : $ClusterName"
Write-Host " Region  : $Region"
Write-Host " Account : $awsAccountId"
Write-Host " Tag     : $ImageTag"
Write-Host "==============================================" -ForegroundColor Cyan

if (-not $Force) {
    Write-Host "This will provision AWS + deploy all services." -ForegroundColor Yellow
    $confirm = Read-Host "Type 'yes' to continue"
    if ($confirm -ne "yes") {
        Write-Host "Aborted." -ForegroundColor Yellow
        exit 0
    }
}

Write-Host "[1/9] Create EKS cluster (if missing)..." -ForegroundColor Cyan
if (-not (Cluster-Exists -Name $ClusterName -AwsRegion $Region)) {
    eksctl create cluster `
        --name $ClusterName `
        --region $Region `
        --version $K8sVersion `
        --nodegroup-name $GeneralNodegroupName `
        --node-type $GeneralNodeType `
        --nodes-min $GeneralNodeMin `
        --nodes-max $GeneralNodeMax `
        --nodes $GeneralNodeDesired `
        --managed `
        --with-oidc `
        --asg-access `
        --full-ecr-access | Out-Null
}
aws eks update-kubeconfig --name $ClusterName --region $Region | Out-Null

    Write-Host "[1b/9] Ensure managed nodegroups exist..." -ForegroundColor Cyan
    Ensure-ManagedNodegroup -ClusterName $ClusterName -AwsRegion $Region -NodegroupName $GeneralNodegroupName -NodeType $GeneralNodeType -NodeMin $GeneralNodeMin -NodeMax $GeneralNodeMax -NodeDesired $GeneralNodeDesired -K8sVersion $K8sVersion
    Ensure-ManagedNodegroup -ClusterName $ClusterName -AwsRegion $Region -NodegroupName $WorkloadNodegroupName -NodeType $WorkloadNodeType -NodeMin $WorkloadNodeMin -NodeMax $WorkloadNodeMax -NodeDesired $WorkloadNodeDesired -K8sVersion $K8sVersion

    Write-Host "Waiting for nodegroups and nodes to become ready..." -ForegroundColor Cyan
    aws eks wait nodegroup-active --cluster-name $ClusterName --nodegroup-name $GeneralNodegroupName --region $Region
    aws eks wait nodegroup-active --cluster-name $ClusterName --nodegroup-name $WorkloadNodegroupName --region $Region
    kubectl wait --for=condition=Ready nodes --all --timeout=900s | Out-Null

    $ebsCsiPolicyArn = Get-PolicyArnByName -PolicyName "AmazonEBSCSIDriverPolicy"
    $albControllerPolicyArn = Get-PolicyArnByName -PolicyName "AWSLoadBalancerControllerIAMPolicy"
    $rolePolicyArns = @($ebsCsiPolicyArn, $albControllerPolicyArn | Where-Object { $_ })
    if ($rolePolicyArns.Count -gt 0) {
        Ensure-ClusterNodegroupPolicies -ClusterName $ClusterName -AwsRegion $Region -PolicyArns $rolePolicyArns
    }

Write-Host "[2/9] Enable core addons/controllers..." -ForegroundColor Cyan
eksctl utils associate-iam-oidc-provider --cluster $ClusterName --region $Region --approve | Out-Null
Ensure-EbsCsiAddon -ClusterName $ClusterName -AwsRegion $Region
Ensure-LbController -EksCluster $ClusterName -AwsRegion $Region -AwsAccount $awsAccountId

$albControllerPolicyArn = Get-PolicyArnByName -PolicyName "AWSLoadBalancerControllerIAMPolicy"
if ($albControllerPolicyArn) {
    Ensure-ClusterNodegroupPolicies -ClusterName $ClusterName -AwsRegion $Region -PolicyArns @($albControllerPolicyArn)
}

Write-Host "[3/9] Apply namespaces + storage class..." -ForegroundColor Cyan
kubectl apply -f (Join-Path $k8sRoot "namespaces\namespaces.yaml") | Out-Null
kubectl apply -f (Join-Path $k8sRoot "aws\storageclass.yaml") | Out-Null

Write-Host "[4/9] Create IRSA service accounts for app namespaces..." -ForegroundColor Cyan
foreach ($ns in @("agent1", "agent2", "manager")) {
    eksctl create iamserviceaccount `
        --cluster $ClusterName `
        --region $Region `
        --namespace $ns `
        --name "${ns}-service-account" `
        --attach-policy-arn arn:aws:iam::aws:policy/AmazonRDSReadOnlyAccess `
        --approve `
        --override-existing-serviceaccounts | Out-Null
}

$rdsEndpoint = ""
Write-Host "[5/9] Provision RDS + initialize databases..." -ForegroundColor Cyan
if ($UsePostgresImage) {
    $rdsEndpoint = Ensure-InClusterPostgresAndInitDatabases -Namespace $PostgresNamespace -ServiceName $PostgresServiceName -StorageClass $PostgresStorageClass -StorageSize $PostgresStorageSize -MasterUsername $DbUsername -MasterPassword $DbPassword -K8sRoot $k8sRoot
} elseif ($SkipRds) {
    if ($env:RDS_ENDPOINT) {
        $rdsEndpoint = [string]$env:RDS_ENDPOINT
    } else {
        throw "-SkipRds was set but RDS_ENDPOINT is not provided in environment."
    }
} else {
    $rdsEndpoint = Ensure-RdsAndInitDatabases -EksCluster $ClusterName -AwsRegion $Region -InstanceId $DbInstanceId -MasterUsername $DbUsername -MasterPassword $DbPassword -InstanceClass $DbInstanceClass -StorageGb $DbAllocatedStorage -K8sRoot $k8sRoot
}
Write-Host "RDS endpoint: $rdsEndpoint" -ForegroundColor Green

Write-Host "[6/9] Build and push images to ECR..." -ForegroundColor Cyan
$services = @(
    @{ Repo = "agent1-inventory-service"; Src = "agent1\inventoryService" },
    @{ Repo = "agent1-order-service"; Src = "agent1\orderService" },
    @{ Repo = "agent1-product-service"; Src = "agent1\productService" },
    @{ Repo = "agent1-revenue-service"; Src = "agent1\revenueService" },
    @{ Repo = "agent2-inventory-service"; Src = "agent2\inventoryService" },
    @{ Repo = "agent2-order-service"; Src = "agent2\orderService" },
    @{ Repo = "agent2-product-service"; Src = "agent2\productService" },
    @{ Repo = "agent2-revenue-service"; Src = "agent2\revenueService" },
    @{ Repo = "manager-central-api-gateway"; Src = "manager\centralAPIGateway" },
    @{ Repo = "manager-data-aggregation-service"; Src = "manager\dataAggregationService" },
    @{ Repo = "manager-central-analytics-service"; Src = "manager\centralAnalyticsService" },
    @{ Repo = "manager-alert-service"; Src = "manager\alertService" },
    @{ Repo = "manager-automation-action-service"; Src = "manager\automationActionService" },
    @{ Repo = "manager-report-service"; Src = "manager\reportService" },
    @{ Repo = "manager-master-data-service"; Src = "manager\masterDataService" },
    @{ Repo = "manager-ml-bridge-service"; Src = "manager\ML-BridgeService" },
    @{ Repo = "ml-model-service"; Src = "infra\ml-model" }
)

if (-not $SkipBuildPush) {
    $pw = aws ecr get-login-password --region $Region
    $pw | docker login --username AWS --password-stdin $ecrRegistry | Out-Null

    foreach ($svc in $services) {
        Ensure-EcrRepo -RepositoryName $svc.Repo -AwsRegion $Region
        $img = "$ecrRegistry/$($svc.Repo):$ImageTag"

        if ($svc.Repo -eq "ml-model-service") {
            docker build -f $dockerfileMl -t $img (Join-Path $workspaceRoot "infra\ml-model") | Out-Null
        } else {
            $srcPosix = ($svc.Src -replace "\\", "/")
            docker build -f $dockerfileSpring --build-arg SERVICE_DIR=$srcPosix -t $img $workspaceRoot | Out-Null
        }

        docker push $img | Out-Null
    }
} else {
    Write-Host "SkipBuildPush=true, assuming images already exist for tag '$ImageTag'." -ForegroundColor Yellow
}

Write-Host "[7/9] Deploy application manifests..." -ForegroundColor Cyan
$tempDir = Join-Path $env:TEMP ("full-create-" + [Guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $tempDir | Out-Null
try {
    $dbHost = $rdsEndpoint
    if ($dbHost -match '^https?://') {
        $dbHost = ([Uri]$dbHost).Host
    }
    $dbHost = ($dbHost -replace '^\[|\]$','')
    $dbHost = ($dbHost -split ':')[0]
    $alertEmailFrom = if ($env:ALERT_EMAIL_FROM) { [string]$env:ALERT_EMAIL_FROM } else { "alerts@example.com" }
    $alertEmailPassword = if ($env:ALERT_EMAIL_PASSWORD) { [string]$env:ALERT_EMAIL_PASSWORD } else { "changeme" }
    $alertEmailTo = if ($env:ALERT_EMAIL_TO) { [string]$env:ALERT_EMAIL_TO } else { "ops@example.com" }
    $alertEmailManagerFrom = if ($env:ALERT_EMAIL_MANAGER_FROM) { [string]$env:ALERT_EMAIL_MANAGER_FROM } else { $alertEmailFrom }
    $alertEmailManagerPassword = if ($env:ALERT_EMAIL_MANAGER_PASSWORD) { [string]$env:ALERT_EMAIL_MANAGER_PASSWORD } else { $alertEmailPassword }
    $alertEmailManagerTo = if ($env:ALERT_EMAIL_MANAGER_TO) { [string]$env:ALERT_EMAIL_MANAGER_TO } else { $alertEmailTo }
    $alertEmailInventoryFrom = if ($env:ALERT_EMAIL_INVENTORY_FROM) { [string]$env:ALERT_EMAIL_INVENTORY_FROM } else { $alertEmailFrom }
    $alertEmailInventoryPassword = if ($env:ALERT_EMAIL_INVENTORY_PASSWORD) { [string]$env:ALERT_EMAIL_INVENTORY_PASSWORD } else { $alertEmailPassword }
    $alertEmailInventoryTo = if ($env:ALERT_EMAIL_INVENTORY_TO) { [string]$env:ALERT_EMAIL_INVENTORY_TO } else { $alertEmailTo }
    $alertEmailOrderFrom = if ($env:ALERT_EMAIL_ORDER_FROM) { [string]$env:ALERT_EMAIL_ORDER_FROM } else { $alertEmailFrom }
    $alertEmailOrderPassword = if ($env:ALERT_EMAIL_ORDER_PASSWORD) { [string]$env:ALERT_EMAIL_ORDER_PASSWORD } else { $alertEmailPassword }
    $alertEmailOrderTo = if ($env:ALERT_EMAIL_ORDER_TO) { [string]$env:ALERT_EMAIL_ORDER_TO } else { $alertEmailTo }
    $alertEmailRevenueFrom = if ($env:ALERT_EMAIL_REVENUE_FROM) { [string]$env:ALERT_EMAIL_REVENUE_FROM } else { $alertEmailFrom }
    $alertEmailRevenuePassword = if ($env:ALERT_EMAIL_REVENUE_PASSWORD) { [string]$env:ALERT_EMAIL_REVENUE_PASSWORD } else { $alertEmailPassword }
    $alertEmailRevenueTo = if ($env:ALERT_EMAIL_REVENUE_TO) { [string]$env:ALERT_EMAIL_REVENUE_TO } else { $alertEmailTo }
    $alertEmailProductFrom = if ($env:ALERT_EMAIL_PRODUCT_FROM) { [string]$env:ALERT_EMAIL_PRODUCT_FROM } else { $alertEmailFrom }
    $alertEmailProductPassword = if ($env:ALERT_EMAIL_PRODUCT_PASSWORD) { [string]$env:ALERT_EMAIL_PRODUCT_PASSWORD } else { $alertEmailPassword }
    $alertEmailProductTo = if ($env:ALERT_EMAIL_PRODUCT_TO) { [string]$env:ALERT_EMAIL_PRODUCT_TO } else { $alertEmailTo }

    # Create DB secrets
    foreach ($ns in @("agent1", "agent2")) {
        $secretName = "$ns-db-secret"
        kubectl create secret generic $secretName `
            --namespace=$ns `
            "--from-literal=db-username=$DbUsername" `
            "--from-literal=db-password=$DbPassword" `
            "--from-literal=inventory-datasource-url=jdbc:postgresql://${dbHost}:5432/${ns}_inventory" `
            "--from-literal=sales-datasource-url=jdbc:postgresql://${dbHost}:5432/${ns}_sales" `
            "--from-literal=products-datasource-url=jdbc:postgresql://${dbHost}:5432/${ns}_products" `
            "--from-literal=revenue-datasource-url=jdbc:postgresql://${dbHost}:5432/${ns}_revenue" `
            --dry-run=client -o yaml | kubectl apply -f - | Out-Null
    }

    kubectl create secret generic manager-db-secret `
        --namespace=manager `
        "--from-literal=db-username=$DbUsername" `
        "--from-literal=db-password=$DbPassword" `
        "--from-literal=ALERT_EMAIL_FROM=$alertEmailFrom" `
        "--from-literal=ALERT_EMAIL_PASSWORD=$alertEmailPassword" `
        "--from-literal=ALERT_EMAIL_TO=$alertEmailTo" `
        "--from-literal=ALERT_EMAIL_MANAGER_FROM=$alertEmailManagerFrom" `
        "--from-literal=ALERT_EMAIL_MANAGER_PASSWORD=$alertEmailManagerPassword" `
        "--from-literal=ALERT_EMAIL_MANAGER_TO=$alertEmailManagerTo" `
        "--from-literal=ALERT_EMAIL_INVENTORY_FROM=$alertEmailInventoryFrom" `
        "--from-literal=ALERT_EMAIL_INVENTORY_PASSWORD=$alertEmailInventoryPassword" `
        "--from-literal=ALERT_EMAIL_INVENTORY_TO=$alertEmailInventoryTo" `
        "--from-literal=ALERT_EMAIL_ORDER_FROM=$alertEmailOrderFrom" `
        "--from-literal=ALERT_EMAIL_ORDER_PASSWORD=$alertEmailOrderPassword" `
        "--from-literal=ALERT_EMAIL_ORDER_TO=$alertEmailOrderTo" `
        "--from-literal=ALERT_EMAIL_REVENUE_FROM=$alertEmailRevenueFrom" `
        "--from-literal=ALERT_EMAIL_REVENUE_PASSWORD=$alertEmailRevenuePassword" `
        "--from-literal=ALERT_EMAIL_REVENUE_TO=$alertEmailRevenueTo" `
        "--from-literal=ALERT_EMAIL_PRODUCT_FROM=$alertEmailProductFrom" `
        "--from-literal=ALERT_EMAIL_PRODUCT_PASSWORD=$alertEmailProductPassword" `
        "--from-literal=ALERT_EMAIL_PRODUCT_TO=$alertEmailProductTo" `
        "--from-literal=gateway-datasource-url=jdbc:postgresql://${dbHost}:5432/manager_api_gateway" `
        "--from-literal=aggregation-datasource-url=jdbc:postgresql://${dbHost}:5432/manager_aggregation" `
        "--from-literal=analytics-datasource-url=jdbc:postgresql://${dbHost}:5432/manager_analytics" `
        "--from-literal=alert-datasource-url=jdbc:postgresql://${dbHost}:5432/manager_alert" `
        "--from-literal=automation-datasource-url=jdbc:postgresql://${dbHost}:5432/manager_automation" `
        "--from-literal=report-datasource-url=jdbc:postgresql://${dbHost}:5432/manager_report" `
        "--from-literal=master-data-datasource-url=jdbc:postgresql://${dbHost}:5432/manager_master_data" `
        "--from-literal=ml-bridge-datasource-url=jdbc:postgresql://${dbHost}:5432/manager_ml_bridge" `
        --dry-run=client -o yaml | kubectl apply -f - | Out-Null

    # Agent manifests
    foreach ($ns in @("agent1", "agent2")) {
        foreach ($svcName in @("inventory-service", "order-service", "product-service", "revenue-service")) {
            Apply-SubstitutedManifest -SourceFile (Join-Path $k8sRoot "$ns\$svcName.yaml") -TempDir $tempDir -EcrRegistry $ecrRegistry -ImgTag $ImageTag -RdsEndpoint $rdsEndpoint -AwsAccount $awsAccountId -EksClusterName $ClusterName
        }
    }

    # Manager + model manifests
    foreach ($f in @(
        "manager\central-api-gateway.yaml",
        "manager\data-aggregation-service.yaml",
        "manager\analytics-and-alert-services.yaml",
        "manager\automation-and-report-services.yaml",
        "manager\master-data-and-ml-bridge-services.yaml"
    )) {
        Apply-SubstitutedManifest -SourceFile (Join-Path $k8sRoot $f) -TempDir $tempDir -EcrRegistry $ecrRegistry -ImgTag $ImageTag -RdsEndpoint $rdsEndpoint -AwsAccount $awsAccountId -EksClusterName $ClusterName
    }

    Apply-SubstitutedManifest -SourceFile (Join-Path $workspaceRoot "infra\ml-model\k8s\deployment.yaml") -TempDir $tempDir -EcrRegistry $ecrRegistry -ImgTag $ImageTag -RdsEndpoint $rdsEndpoint -AwsAccount $awsAccountId -EksClusterName $ClusterName

} finally {
    Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue
}

Write-Host "[8/9] Deploy monitoring stack..." -ForegroundColor Cyan
if ($SkipMonitoring) {
    Write-Host "SkipMonitoring=true, monitoring deployment skipped." -ForegroundColor Yellow
} else {
    $promDir = Join-Path $k8sRoot "monitoring\prometheus"
    $elkDir = Join-Path $k8sRoot "monitoring\elk"
    $grafDir = Join-Path $k8sRoot "monitoring\grafana"

    kubectl apply -f (Join-Path $promDir "rbac.yaml") | Out-Null
    kubectl apply -f (Join-Path $promDir "configmap.yaml") | Out-Null
    kubectl apply -f (Join-Path $promDir "pvc.yaml") | Out-Null
    kubectl apply -f (Join-Path $promDir "statefulset.yaml") | Out-Null

    kubectl apply -f (Join-Path $elkDir "elasticsearch.yaml") | Out-Null
    kubectl apply -f (Join-Path $elkDir "logstash.yaml") | Out-Null
    kubectl apply -f (Join-Path $elkDir "kibana.yaml") | Out-Null
    kubectl apply -f (Join-Path $elkDir "filebeat.yaml") | Out-Null

    kubectl apply -f (Join-Path $grafDir "pvc.yaml") | Out-Null
    kubectl apply -f (Join-Path $grafDir "deployment.yaml") | Out-Null
}

Write-Host "[9/9] Waiting for critical deployments..." -ForegroundColor Cyan
foreach ($d in @("inventory-service", "order-service", "product-service", "revenue-service")) {
    Wait-Deployment -Name $d -Namespace agent1
    Wait-Deployment -Name $d -Namespace agent2
}
foreach ($d in @("central-api-gateway", "data-aggregation-service", "central-analytics-service", "alert-service", "automation-action-service", "report-service", "master-data-service", "ml-bridge-service", "ml-model-service")) {
    Wait-Deployment -Name $d -Namespace manager
}

Write-Host ""
Write-Host "================ CREATE SUMMARY ================" -ForegroundColor Green
Write-Host "Cluster: $ClusterName"
Write-Host "Region : $Region"
Write-Host "ECR    : $ecrRegistry"
Write-Host "Tag    : $ImageTag"
Write-Host "RDS    : $rdsEndpoint"
Write-Host ""
Write-Host "Deployment status:"
kubectl get deploy -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,READY:.status.readyReplicas,DESIRED:.spec.replicas | Sort-Object NS,NAME
Write-Host "===============================================" -ForegroundColor Green
