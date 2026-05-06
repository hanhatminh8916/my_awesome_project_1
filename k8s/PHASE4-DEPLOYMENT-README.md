# Phase 4 — Kubernetes on AWS EKS: Deployment Guide

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| AWS CLI | v2 | `brew install awscli` |
| eksctl | latest | `brew tap weaveworks/tap && brew install eksctl` |
| kubectl | 1.30+ | `brew install kubectl` |
| Helm | 3.x | `brew install helm` |
| Docker | latest | [docker.com](https://www.docker.com) |

---

## Step 0 — Configure AWS CLI (secure, no hardcoded credentials)

```bash
aws configure
# AWS Access Key ID     : <your-new-key>
# AWS Secret Access Key : <your-secret>
# Default region name  : us-east-1
# Default output format : json
```

Verify authentication:
```bash
aws sts get-caller-identity
```

---

## Step 1 — Set environment variables

```bash
export CLUSTER_NAME=microservices-cluster
export AWS_REGION=us-east-1
export IMAGE_TAG=$(git rev-parse --short HEAD 2>/dev/null || echo "v1.0.0")

# RDS Aurora MySQL (create before running Step 4)
export RDS_ENDPOINT=<your-rds-cluster-endpoint>
export DB_USERNAME=<rds-master-username>
export DB_PASSWORD=<rds-master-password>   # use AWS Secrets Manager in production

# ACM Certificate ARN (create before running Step 4)
export ACM_CERT_ARN=arn:aws:acm:us-east-1:<account-id>:certificate/<uuid>
```

---

## Step 2 — Create EKS cluster + install controllers

```bash
cd k8s/scripts
chmod +x eks-setup.sh ecr-build-push.sh deploy-apps.sh teardown.sh
bash eks-setup.sh
```

This script will:
1. Create an EKS cluster with managed node group
2. Enable OIDC provider (required for IRSA)
3. Install AWS EBS CSI Driver (for PVCs)
4. Install AWS Load Balancer Controller (for ALB Ingress)
5. Create IRSA service accounts for each namespace
6. Apply namespaces, StorageClass, monitoring stack

---

## Step 3 — Build and push Docker images to ECR

```bash
# From workspace root
bash k8s/scripts/ecr-build-push.sh
```

This script will:
- Create 16 ECR repositories (with scan-on-push enabled)
- Build each Spring Boot service (Maven → Docker)
- Push images to ECR with tag `${IMAGE_TAG}`

---

## Step 4 — Deploy all microservices

```bash
bash k8s/scripts/deploy-apps.sh
```

This script will:
- Substitute all `<ECR_REGISTRY>`, `<RDS_ENDPOINT>`, etc. in YAML files (in a temp dir)
- Create DB secrets via `kubectl create secret` — credentials are never stored in files
- Apply ConfigMaps, Deployments, Services, HPAs for all 16 services
- Wait for all rollouts to complete
- Print the ALB endpoint URL

---

## Directory Structure

```
k8s/
├── namespaces/
│   └── namespaces.yaml            # agent1, agent2, manager, monitoring
├── aws/
│   ├── storageclass.yaml          # EBS gp3, encrypted, Retain
│   └── service-accounts.yaml      # IRSA-annotated ServiceAccounts
├── agent1/
│   ├── secret.yaml                # template (replaced by deploy-apps.sh)
│   ├── inventory-service.yaml     # ConfigMap + Deployment + Service + HPA
│   ├── order-service.yaml
│   ├── product-service.yaml
│   └── revenue-service.yaml
├── agent2/                        # Same structure as agent1
├── manager/
│   ├── secret.yaml
│   ├── central-api-gateway.yaml   # Includes ALB Ingress
│   ├── data-aggregation-service.yaml
│   ├── analytics-and-alert-services.yaml
│   ├── automation-and-report-services.yaml
│   └── master-data-and-ml-bridge-services.yaml
├── monitoring/
│   ├── prometheus/
│   │   ├── rbac.yaml
│   │   ├── configmap.yaml
│   │   ├── pvc.yaml               # 20Gi EBS gp3
│   │   ├── statefulset.yaml
│   │   ├── servicemonitor.yaml
│   │   └── podmonitor.yaml
│   ├── grafana/
│   │   ├── pvc.yaml               # 5Gi EBS gp3
│   │   └── deployment.yaml
│   └── elk/
│       ├── elasticsearch.yaml     # StatefulSet, 30Gi EBS
│       ├── logstash.yaml
│       ├── kibana.yaml
│       └── filebeat.yaml          # DaemonSet
└── scripts/
    ├── eks-setup.sh               # Cluster creation + controller installation
    ├── ecr-build-push.sh          # Build all 16 images → ECR
    ├── deploy-apps.sh             # Deploy microservices to EKS
    └── teardown.sh                # Delete everything (with confirmation)
```

---

## Port / Namespace Mapping

| Cluster | Service | Port | Namespace |
|---|---|---|---|
| agent1 | inventory-service | 8081 | agent1 |
| agent1 | order-service | 8082 | agent1 |
| agent1 | revenue-service | 8083 | agent1 |
| agent1 | product-service | 8084 | agent1 |
| agent2 | inventory-service | 8181 | agent2 |
| agent2 | order-service | 8182 | agent2 |
| agent2 | revenue-service | 8183 | agent2 |
| agent2 | product-service | 8184 | agent2 |
| manager | central-api-gateway | 8090 | manager |
| manager | data-aggregation-service | 8091 | manager |
| manager | central-analytics-service | 8092 | manager |
| manager | alert-service | 8093 | manager |
| manager | automation-action-service | 8094 | manager |
| manager | report-service | 8095 | manager |
| manager | master-data-service | 8096 | manager |
| manager | ml-bridge-service | 8097 | manager |

---

## Accessing Services

### From outside the cluster (via ALB)
```bash
# Get ALB hostname (takes ~2 min after first deploy)
kubectl get ingress -n manager

# Access via HTTPS
curl https://<alb-hostname>/actuator/health
```

### Monitoring UIs (port-forward for local access)
```bash
# Prometheus
kubectl port-forward -n monitoring svc/prometheus 9090:9090
# → http://localhost:9090

# Grafana (admin / admin — change immediately)
kubectl port-forward -n monitoring svc/grafana 3000:3000
# → http://localhost:3000

# Kibana
kubectl port-forward -n monitoring svc/kibana 5601:5601
# → http://localhost:5601
```

---

## Security Checklist

- [x] Credentials injected via `kubectl create secret` — never in YAML files
- [x] EBS volumes encrypted at rest (`encrypted: "true"` in StorageClass)
- [x] IRSA (fine-grained IAM roles per namespace, not node-level)
- [x] Non-root containers (`runAsUser`, `fsGroup`)
- [x] `reclaimPolicy: Retain` — no accidental data loss
- [x] SSL redirect (HTTP → HTTPS) on ALB Ingress
- [x] `WaitForFirstConsumer` — EBS volumes in correct AZ
- [x] RDS connection with `useSSL=true&requireSSL=true`
- [ ] Rotate the Grafana `admin` password after first login
- [ ] Restrict Security Groups on RDS to only allow EKS worker node SG
- [ ] Enable AWS GuardDuty and CloudTrail for the account

---

## Teardown

```bash
bash k8s/scripts/teardown.sh
# Type 'yes' when prompted
```

> **Note:** EBS volumes with `reclaimPolicy: Retain` are NOT deleted.  
> Delete them manually: AWS Console → EC2 → Volumes → filter by cluster tag.
