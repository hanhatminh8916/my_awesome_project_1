# Phase 1 Integration & Local Containerization

## 1) Spring Cloud OpenFeign (Synchronous Inter-Service Call)
Implemented flows:
- `agent1/revenueService` pushes payload to manager
- `agent2/revenueService` pushes payload to manager
- `manager/dataAggregationService` ingests payload

### Revenue service call path
- `POST /api/v1/revenue/push` -> `RevenuePushService` -> Feign client -> manager endpoint

Example request payload:
```json
{
  "agentId": "agent-1",
  "sourceService": "revenueService",
  "reportId": "RPT-2026-03-18-0001",
  "grossRevenue": 2500.00,
  "netRevenue": 2300.00,
  "currency": "USD",
  "reportedAt": "2026-03-18T08:30:00Z"
}
```

## 2) Observability setup

### Exact Maven dependencies
Use this dependency set in each Spring Boot service:

```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-actuator</artifactId>
</dependency>
<dependency>
    <groupId>io.micrometer</groupId>
    <artifactId>micrometer-registry-prometheus</artifactId>
</dependency>
<dependency>
    <groupId>net.logstash.logback</groupId>
    <artifactId>logstash-logback-encoder</artifactId>
    <version>8.1</version>
</dependency>
```

For Feign-enabled services add:
```xml
<dependency>
    <groupId>org.springframework.cloud</groupId>
    <artifactId>spring-cloud-starter-openfeign</artifactId>
</dependency>
```

If not already present, import Spring Cloud BOM:
```xml
<properties>
    <spring-cloud.version>2025.0.0</spring-cloud.version>
</properties>

<dependencyManagement>
    <dependencies>
        <dependency>
            <groupId>org.springframework.cloud</groupId>
            <artifactId>spring-cloud-dependencies</artifactId>
            <version>${spring-cloud.version}</version>
            <type>pom</type>
            <scope>import</scope>
        </dependency>
    </dependencies>
</dependencyManagement>
```

### `application.yml` snippet
```yaml
management:
  endpoints:
    web:
      exposure:
        include: health,info,prometheus
  endpoint:
    health:
      probes:
        enabled: true
  prometheus:
    metrics:
      export:
        enabled: true

logging:
  level:
    root: INFO
  logstash:
    host: ${LOGSTASH_HOST:localhost}
    port: ${LOGSTASH_PORT:5000}
```

Prometheus endpoint:
- `/actuator/prometheus`

## 3) Docker & Local orchestration

### Multi-stage Dockerfile
- `infra/docker/Dockerfile.spring-boot`
- Uses Maven build stage + slim JRE runtime + non-root user

### Full local stack
- `infra/docker-compose.yml`
- Includes:
  - PostgreSQL containers for all `agent1`, `agent2`, and `manager` services in this workspace
  - Elasticsearch, Logstash, Kibana
  - Prometheus
  - Spring Boot placeholders for all services under `apps` profile

### Logstash pipeline
- `infra/observability/logstash/logstash.conf`
- Listens on TCP `5000` with JSON codec and indexes to Elasticsearch

### Prometheus scrape config
- `infra/observability/prometheus/prometheus.yml`
- Scrapes Prometheus itself + example app metric endpoints

## Useful commands
From `infra/` directory:

Start infrastructure only:
```bash
docker compose up -d
```

Start infrastructure + example app services:
```bash
docker compose --profile apps up -d --build
```

Stop and remove containers:
```bash
docker compose down
```

Stop and remove containers + volumes:
```bash
docker compose down -v
```
