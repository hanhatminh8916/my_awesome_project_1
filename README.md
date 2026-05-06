# 🏗️ Microservices Manager Platform

> **Nền tảng quản lý Microservices** — Hệ thống microservices đa cụm với observability toàn diện, phát hiện bất thường tự động bằng ML, và cảnh báo qua email — triển khai trên AWS EKS và chạy được cục bộ qua Docker Compose.

[![Java](https://img.shields.io/badge/Java-17-orange)](https://adoptium.net/)
[![Spring Boot](https://img.shields.io/badge/Spring%20Boot-3.2-green)](https://spring.io/projects/spring-boot)
[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://www.python.org/)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-1.33-blue)](https://kubernetes.io/)
[![AWS EKS](https://img.shields.io/badge/AWS-EKS-orange)](https://aws.amazon.com/eks/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 📋 Mục lục / Table of Contents

- [Kiến trúc / Architecture](#-kiến-trúc--architecture)
- [Khởi động nhanh / Quick Start](#-khởi-động-nhanh--quick-start)
- [Danh sách dịch vụ / Service Map](#-danh-sách-dịch-vụ--service-map)
- [Pipeline ML / ML Pipeline](#-pipeline-ml--ml-pipeline)
- [Triển khai AWS EKS / AWS EKS Deployment](#-triển-khai-aws-eks--aws-eks-deployment)
- [Cấu hình / Configuration](#-cấu-hình--configuration)
- [Xử lý sự cố / Troubleshooting](#-xử-lý-sự-cố--troubleshooting)
- [Cấu trúc dự án / Project Structure](#-cấu-trúc-dự-án--project-structure)
- [Tiến độ các giai đoạn / Phase Summary](#-tiến-độ-các-giai-đoạn--phase-summary)

---

## 🏛️ Kiến trúc / Architecture

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                    MICROSERVICES MANAGER PLATFORM                            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  ┌──────────────── agent1-net ─────────────┐  ┌──── agent2-net ───────────┐ ║
║  │  inventory:8081    product:8084         │  │  inventory:8181           │ ║
║  │  order:8082        revenue:8083 ──┐     │  │  order:8182               │ ║
║  └────────────────────────────────── │ ────┘  │  revenue:8183 ─────┐      │ ║
║                                      │ Feign  └────────────────────│──────┘ ║
║  ┌──────────────── manager-net ───────▼────────────────────────────▼──────┐ ║
║  │                                                                         │ ║
║  │  centralAPIGateway:8090     dataAggregationService:8091                │ ║
║  │  centralAnalyticsService:8092  alertService:8093                       │ ║
║  │  automationActionService:8094  reportService:8095                      │ ║
║  │  masterDataService:8096     ML-BridgeService:8097                      │ ║
║  │  ml-model (FastAPI):8000    ◄──── polls Prometheus every 30s           │ ║
║  └───────────────────────────────────────────────────────────────────────┘  ║
║                                     │                                        ║
║  ┌──────────── app-observability-net ▼ ─────────────────────────────────┐   ║
║  │  Prometheus:9090    Grafana:3000    Elasticsearch:9200                │   ║
║  │  Logstash:5000      Kibana:5601     Filebeat (log shipper)            │   ║
║  └───────────────────────────────────────────────────────────────────────┘  ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

### 🔍 Pipeline phát hiện bất thường ML / ML Anomaly Detection Pipeline

```
  ┌──────────────┐  scrape   ┌────────────┐  poll/30s  ┌──────────────┐
  │ 16 services  │──────────▶│ Prometheus │◀───────────│ ML-Bridge    │
  │ /actuator/   │           │  :9090     │            │ Service:8097 │
  │ prometheus   │           └────────────┘            └──────┬───────┘
  └──────────────┘                                            │ POST /predict
                                                              ▼
                                                    ┌─────────────────┐
                                                    │ FastAPI ML Model│
                                                    │  :8000          │
                                                    │  RF + IsoForest │
                                                    │  F1 = 0.9857    │
                                                    └────────┬────────┘
                                                             │ prob > 0.5 → anomaly
                                                             ▼
                                                    ┌─────────────────┐
                                                    │  Alert Service  │
                                                    │  :8093          │
                                                    │  Gmail SMTP     │
                                                    └────────┬────────┘
                                                             │
                                                             ▼ 📧 Email
```

> **Luồng hoạt động**: 16 dịch vụ Spring Boot xuất metrics qua `/actuator/prometheus` → Prometheus scrape mỗi 15s → ML-BridgeService gọi Prometheus mỗi 30s để lấy metrics → gửi đến ML Model (FastAPI) để dự đoán → nếu xác suất bất thường > 0.5 → AlertService gửi email qua Gmail SMTP đến đúng người phụ trách từng dịch vụ (inventory, order, revenue, product) và CC cho quản lý.

---

## 🚀 Khởi động nhanh / Quick Start

### Yêu cầu / Prerequisites

- **Java 17**, **Maven 3.8+**
- **Docker** & **Docker Compose**
- **Python 3.10+** (cho ML model / for ML model)
- **AWS CLI**, **eksctl**, **kubectl**, **helm** (cho EKS / for EKS)

### Chạy cục bộ / Local Run (3 lệnh / 3 commands)

```bash
# 1. Clone và cấu hình email / Clone and configure email
cp infra/.env.example infra/.env
# Sửa infra/.env với Gmail App Password của bạn / Edit with your Gmail App Password

# 2. Khởi động toàn bộ hệ thống / Start everything
docker compose -f infra/docker-compose.yml --profile apps up -d

# 3. Chạy kiểm thử end-to-end / Run end-to-end test
bash scripts/e2e_test.sh --skip-build --no-cleanup
```

---

## 📊 Danh sách dịch vụ / Service Map

### Cụm Agent (×2: agent1 + agent2) / Agent Clusters

| Dịch vụ / Service | Container | Port | Mô tả / Description |
|---|---|---|---|
| inventoryService | agent{1,2}-inventory-service | 8081/8181 | Quản lý tồn kho / Stock levels, reservations |
| orderService | agent{1,2}-order-service | 8082/8182 | Vòng đời đơn hàng / Order lifecycle |
| productService | agent{1,2}-product-service | 8084/8184 | Danh mục sản phẩm / Product catalogue |
| revenueService | agent{1,2}-revenue-service | 8083/8183 | Đẩy doanh thu về manager / Revenue push → manager |

### Cụm Manager / Manager Cluster

| Dịch vụ / Service | Container | Port | Mô tả / Description |
|---|---|---|---|
| centralAPIGateway | manager-central-api-gateway-service | 8090 | Điểm vào duy nhất cho client / Single entry point |
| dataAggregationService | manager-data-aggregation-service | 8091 | Tổng hợp doanh thu từ agent / Ingest revenue from agents |
| centralAnalyticsService | manager-central-analytics-service | 8092 | Phân tích xuyên cụm / Cross-cluster analytics |
| alertService | manager-alert-service | 8093 | Gửi cảnh báo qua Gmail / Send email alerts via Gmail |
| automationActionService | manager-automation-action-service | 8094 | Hành động tự động khắc phục / Auto-remediation |
| reportService | manager-report-service | 8095 | Báo cáo định kỳ / Scheduled reports |
| masterDataService | manager-master-data-service | 8096 | Cấu hình & dữ liệu tham chiếu / Shared config & reference data |
| ML-BridgeService | manager-ml-bridge-service | 8097 | Điều phối phát hiện bất thường / Orchestrates anomaly detection |
| ML Model (FastAPI) | ml-model-service | 8000 | Dự đoán RF + IsolationForest / RF + IsolationForest inference |

### Ngăn xếp Observability / Observability Stack

| Dịch vụ / Service | Port | Tài khoản / Credentials | Mục đích / Purpose |
|---|---|---|---|
| Prometheus | 9090 | — | Thu thập & lưu trữ metrics / Metrics scraping & storage |
| Grafana | 3000 | admin / admin | Bảng điều khiển / Dashboards |
| Elasticsearch | 9200 | — | Lưu trữ log / Log storage |
| Kibana | 5601 | — | Khám phá log / Log exploration |
| Logstash | 5000 | — | Pipeline tổng hợp log / Log aggregation pipeline |

---

## 🤖 Pipeline ML / ML Pipeline

### Huấn luyện / Training

```
model/training_data.csv  (41,280 dòng × 8 đặc trưng / rows × 8 features)
         │
         ▼
infra/ml-model/train_model.py
  1. Nạp & lọc chất lượng / Load & quality filter
  2. Feature engineering (cờ is_down, log1p feign)
  3. train_test_split (80/20, stratified)
  4. Cắt outlier trên TẬP TRAIN / Clip outliers on TRAIN bounds only
  5. StandardScaler fit trên TẬP TRAIN / fit on TRAIN only
  6. RandomForestClassifier (n_estimators=200, class_weight=balanced)
  7. IsolationForest (contamination=auto, capped at 0.5)
  8. Lưu → models/{rf_model.pkl, iso_model.pkl, scaler.pkl, clip_bounds.json}
```

### Kết quả huấn luyện / Training Results

| Chỉ số / Metric | Giá trị / Value |
|---|---|
| RF F1 (tập test) | **0.9857** |
| RF AUC-ROC | **0.9899** |
| Cross-val F1 (5-fold) | 0.9874 ± 0.0015 |
| Đặc trưng quan trọng nhất / Top feature | error_rate (48.3%) |

### Dự đoán / Inference

```json
POST /predict
{
  "memory_used_bytes": 157286400,
  "request_rate": 0.05,
  "error_rate": 0.001,
  "cpu_usage": 0.03,
  "feign_failures": 0,
  "is_down": 0
}

→ Response: { "probability": 0.141, "is_anomaly": false }
```

### Ngưỡng bất thường / Anomaly Threshold

Mặc định / Default: `ml.anomaly.threshold=0.5` (có thể cấu hình qua biến môi trường `ML_ANOMALY_THRESHOLD_OVERRIDE`).

---

## ☁️ Triển khai AWS EKS / AWS EKS Deployment

### Triển khai một lệnh / One-command Deployment

```powershell
# Từ thư mục gốc dự án / From project root
.\k8s\scripts\full-create.ps1 -DbUsername masteruser -DbPassword 'YourStrongPass123!' -ImageTag latest -Force
```

**Script này tự động / This script automatically:**
1. Tạo EKS cluster + 2 nodegroups (4× t3.micro + 2× m7i.large)
2. Cài đặt OIDC, EBS CSI driver, AWS Load Balancer Controller
3. Tạo namespaces + IRSA service accounts
4. Tạo RDS PostgreSQL + khởi tạo databases
5. Build & push 17 Docker images lên ECR
6. Deploy toàn bộ manifests (agent1, agent2, manager, ml-model)
7. Deploy monitoring stack (Prometheus, Grafana, ELK, Alertmanager)

### Hủy toàn bộ / Full Destroy

```powershell
.\k8s\scripts\full-destroy.ps1 -Force
```

> ⚠️ **Cảnh báo**: Lệnh này xóa **TẤT CẢ** tài nguyên AWS của dự án (EKS, RDS, ECR, EBS, CloudWatch logs). Đưa chi phí về 0.

### Cấu trúc thư mục K8s / K8s Directory Structure

```
k8s/
├── namespaces/namespaces.yaml
├── aws/
│   ├── storageclass.yaml
│   └── service-accounts.yaml
├── agent1/    (inventory, order, product, revenue)
├── agent2/    (inventory, order, product, revenue)
├── manager/   (gateway, aggregation, analytics, alert, automation, report, master-data, ml-bridge)
├── monitoring/
│   ├── prometheus/   (rbac, configmap, pvc, statefulset)
│   ├── grafana/      (pvc, deployment)
│   ├── alertmanager/ (alertmanager.yaml)
│   └── elk/          (elasticsearch, logstash, kibana, filebeat)
├── jobs/init-databases-job.yaml
└── scripts/
    ├── full-create.ps1
    └── full-destroy.ps1
```

---

## ⚙️ Cấu hình / Configuration

### Biến môi trường / Environment Variables

Tạo file `infra/.env`:

```dotenv
# Email cảnh báo / Alert emails (Gmail App Password)
ALERT_EMAIL_FROM=your-project@gmail.com
ALERT_EMAIL_PASSWORD=xxxx-xxxx-xxxx-xxxx
ALERT_EMAIL_TO=admin@example.com

# Định tuyến email theo dịch vụ / Per-service email routing
ALERT_EMAIL_MANAGER_FROM=manager@gmail.com
ALERT_EMAIL_MANAGER_PASSWORD=xxxx-xxxx-xxxx-xxxx
ALERT_EMAIL_MANAGER_TO=manager@gmail.com
ALERT_EMAIL_INVENTORY_FROM=inventory@gmail.com
ALERT_EMAIL_INVENTORY_PASSWORD=xxxx-xxxx-xxxx-xxxx
ALERT_EMAIL_INVENTORY_TO=inventory@gmail.com
ALERT_EMAIL_ORDER_FROM=order@gmail.com
ALERT_EMAIL_ORDER_PASSWORD=xxxx-xxxx-xxxx-xxxx
ALERT_EMAIL_ORDER_TO=order@gmail.com
ALERT_EMAIL_REVENUE_FROM=revenue@gmail.com
ALERT_EMAIL_REVENUE_PASSWORD=xxxx-xxxx-xxxx-xxxx
ALERT_EMAIL_REVENUE_TO=revenue@gmail.com
ALERT_EMAIL_PRODUCT_FROM=product@gmail.com
ALERT_EMAIL_PRODUCT_PASSWORD=xxxx-xxxx-xxxx-xxxx
ALERT_EMAIL_PRODUCT_TO=product@gmail.com

# Ngưỡng ML / ML threshold
ML_ANOMALY_THRESHOLD_OVERRIDE=0.5
```

### Thuộc tính ứng dụng chính / Key Application Properties

| Dịch vụ / Service | Thuộc tính / Property | Mặc định / Default | Mô tả / Description |
|---|---|---|---|
| ML-Bridge | ml.polling.interval-ms | 30000 | Tần suất gọi Prometheus / How often to poll Prometheus |
| ML-Bridge | ml.anomaly.threshold.override | -1 | Ghi đè ngưỡng model (đặt 0-1 để ép) / Override model threshold |
| ML-Bridge | ml.prometheus.url | http://localhost:9090 | Prometheus base URL |
| ML-Bridge | ml.model.url | http://localhost:8000 | FastAPI model URL |
| ML-Bridge | ml.alert-service.url | http://localhost:8093 | AlertService URL |
| AlertService | alert.email.correlation-window-seconds | 300 | Cửa sổ thời gian tương quan cảnh báo ML + Prometheus |

---

## 🔧 Xử lý sự cố / Troubleshooting

### Tất cả 16 dịch vụ báo bất thường / All 16 services show as anomalous

**Nguyên nhân / Cause**: Thiếu label `cluster` trên Prometheus metrics.
**Khắc phục / Fix**: Đảm bảo `prometheus.yml` có `labels: cluster: agent1` (hoặc agent2/manager) trong mỗi `static_configs` target block.

### Email cảnh báo không gửi được / Alert emails not sending

1. Kiểm tra Gmail App Password đã được thiết lập
2. Xác minh port 587 không bị chặn bởi firewall
3. Xem log alert-service: `docker logs manager-alert-service | grep -i mail`
4. Đảm bảo 2FA đã bật trên Gmail và đang dùng App Password (không phải mật khẩu tài khoản)

### `Connect timed out` trong log ml-bridge

Kiểm tra biến `ALERT_SERVICE_URL` trỏ đúng port (8093, không phải 8080):
```bash
# Docker:
docker exec manager-ml-bridge-service env | grep ALERT
# K8s:
kubectl exec deployment/ml-bridge-service -n manager -- env | grep ALERT
```

### Dịch vụ crash với `DataSourceBeanCreationException`

Database phải sẵn sàng trước khi Spring Boot khởi động:
```bash
# Khởi động infra trước, đợi ~30s, rồi mới khởi động apps
docker compose -f infra/docker-compose.yml up -d
sleep 30
docker compose -f infra/docker-compose.yml --profile apps up -d
```

### ml-model-service không khởi động / ml-model-service does not start

```bash
# Xem log
docker logs ml-model-service

# Nguyên nhân phổ biến: thiếu thư mục models/ (cần train trước)
cd Manager-microservices
.venv\Scripts\activate
python infra/ml-model/train_model.py
```

---

## 📁 Cấu trúc dự án / Project Structure

```
Manager-microservices/
├── agent1/                          # Cụm Agent 1 (ports 8081-8084)
│   ├── inventoryService/            # Spring Boot microservice
│   ├── orderService/
│   ├── productService/
│   └── revenueService/
├── agent2/                          # Cụm Agent 2 (ports 8181-8184)
│   └── ...
├── manager/                         # Cụm Manager (ports 8090-8097)
│   ├── centralAPIGateway/           # API Gateway (Spring Cloud Gateway)
│   ├── dataAggregationService/      # Tổng hợp dữ liệu / Data aggregation
│   ├── centralAnalyticsService/     # Phân tích / Analytics
│   ├── alertService/                # Cảnh báo email / Email alerting
│   ├── automationActionService/     # Tự động hóa / Automation
│   ├── reportService/               # Báo cáo / Reporting
│   ├── masterDataService/           # Dữ liệu chủ / Master data
│   └── ML-BridgeService/            # Cầu nối ML / ML bridge
├── model/                           # Dữ liệu huấn luyện ML / ML training data
│   └── training_data.csv            # 41,280 mẫu / samples
├── infra/
│   ├── docker-compose.yml           # Toàn bộ stack / Full stack orchestration
│   ├── docker/
│   │   └── Dockerfile.spring-boot   # Dockerfile chung cho Spring Boot
│   ├── ml-model/
│   │   ├── Dockerfile               # Container ML model
│   │   ├── serve.py                 # API dự đoán / Inference API
│   │   ├── train_model.py           # Pipeline huấn luyện / Training pipeline
│   │   ├── requirements.txt
│   │   ├── models/                  # Model artifacts (git-ignored)
│   │   └── k8s/                     # K8s manifests cho ML model
│   └── observability/
│       ├── prometheus/              # prometheus.yml + alert_rules.yml
│       ├── alertmanager/            # alertmanager.yml
│       ├── grafana/                 # Dashboards provisioning
│       ├── logstash/                # Logstash pipeline config
│       ├── kibana/
│       └── filebeat/
├── k8s/                             # Kubernetes manifests & scripts
│   ├── agent1/                      # Manifests cho agent1
│   ├── agent2/                      # Manifests cho agent2
│   ├── manager/                     # Manifests cho manager
│   ├── monitoring/                  # Prometheus, Grafana, ELK, Alertmanager
│   ├── jobs/                        # Init jobs
│   └── scripts/                     # full-create.ps1, full-destroy.ps1
└── scripts/
    └── e2e_test.sh                  # Kiểm thử end-to-end
```

---

## ✅ Tiến độ các giai đoạn / Phase Summary

| Giai đoạn / Phase | Mô tả / Description | Trạng thái / Status |
|---|---|---|
| 1 | Gọi liên dịch vụ Spring Cloud OpenFeign | ✅ Hoàn thành |
| 2 | Metrics Prometheus + Grafana | ✅ Hoàn thành |
| 3 | Logging có cấu trúc ELK Stack | ✅ Hoàn thành |
| 4 | Triển khai Kubernetes (AWS EKS) | ✅ Hoàn thành |
| 5 | Thu thập dữ liệu huấn luyện ML (41,280 dòng) | ✅ Hoàn thành |
| 6 | Huấn luyện & deploy model RF + cảnh báo email | ✅ Hoàn thành |
| 7 | Tích hợp cuối & kiểm thử end-to-end | ✅ Hoàn thành |

---

## 📝 Giấy phép / License

MIT License — Xem file [LICENSE](LICENSE) để biết chi tiết.

---

## 👥 Tác giả / Author

**hanhatminh8916** — [GitHub](https://github.com/hanhatminh8916)

> Dự án được xây dựng với mục đích học tập và trình diễn kiến trúc microservices toàn diện trên nền tảng AWS EKS kết hợp Machine Learning.
>
> *Project built for learning and demonstrating a comprehensive microservices architecture on AWS EKS integrated with Machine Learning.*
