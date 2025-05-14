# KFM Agent Shell - Infrastructure Testing Environment Specifications

## 1. Introduction

This document outlines the specifications for the infrastructure testing environment for the Kernel Function Machine (KFM) Agent Shell. The goal is to create a stable, reproducible, and representative environment for testing the application's core functionality, performance, and integration of its various components. This environment will primarily leverage Docker for containerization and Kubernetes for orchestration, with DigitalOcean as a potential cloud provider.

## 2. Core Principles for the Testing Environment

*   **Consistency & Reproducibility:** The environment should be easily reproducible to ensure consistent test results. Achieved through Docker, Kubernetes manifests, and version-controlled configurations.
*   **Isolation:** The testing environment must be isolated from development and production environments to prevent interference.
*   **Representativeness:** While not a full-scale production replica, it should mirror key architectural components and configurations of the production environment.
*   **Scalability (Basic):** Should allow for testing basic scaling behavior of core components.
*   **Observability:** Integrated logging, monitoring, and tracing to facilitate debugging and performance analysis.

## 3. Components to be Deployed

The following components, derived from the project's architecture (`.context/architecture/architecture_document.md`) and best practices, will be deployed in the testing environment. All components should be containerized (Docker).

**A. Core Application Components:**

1.  **KFM Agent Shell Application:**
    *   Source: Main Python FastAPI application (`server.py`).
    *   Includes: Core Runtime, API Layer, Provider Adapter Layer, Personality Pack Manager.
    *   Dependencies: Access to personality pack files.

**B. Key Dependencies (from Architecture Document):**

2.  **Memory Service Components:**
    *   **Vector Database:** LanceDB. Required for long-term memory and RAG.
    *   **Cache:** Redis. For session context, knowledge index caching, etc.

3.  **Messaging/Event Bus:**
    *   **Apache Iggy Server:** For asynchronous inter-component communication. *(Note: Current implementation uses an in-memory event system. For full architecture testing, Iggy would be included. For initial testing environment focused on current code, this might be deferred or mocked if not yet integrated).*

**C. Observability Stack Components:**

4.  **Prometheus Server:** For scraping and storing metrics.
5.  **Grafana:** For visualizing metrics, logs, and traces.
6.  **Tracing Backend:** Jaeger (consider the "all-in-one" deployment for simplicity in testing environments). For receiving and storing distributed traces.
7.  **Log Aggregation System:** Loki (often paired with Promtail for log collection). For collecting and querying structured logs.

**D. Underlying Platform Assumptions:**

*   **Docker:** For containerizing all components.
*   **Kubernetes:** For orchestrating containers.
*   **(Optional) DigitalOcean:** As the cloud provider for hosting the Kubernetes cluster.

## 4. Resource Allocation (CPU, Memory, Storage)

The following are *initial, cost-effective estimates* for a testing environment designed for functional and integration testing. These are starting points and **should be monitored and adjusted** based on observed performance and load during testing. Define resource `requests` (guaranteed allocation for scheduling) and `limits` (maximum allowable consumption) in your Kubernetes manifests.

*   **General Kubernetes Guidelines:**
    *   Start with lean requests and slightly higher limits.
    *   Utilize Horizontal Pod Autoscalers (HPAs) for stateless components if load testing becomes a requirement, but for initial functional testing, fixed replicas are often simpler.
    *   Monitor resource utilization closely using Prometheus/Grafana to identify bottlenecks or over-provisioning.

**A. Core Application Components:**

1.  **KFM Agent Shell Application:**
    *   CPU: Request `0.25` CPU, Limit `1` CPU
    *   Memory: Request `512Mi`, Limit `1.5Gi`
    *   Ephemeral Storage: Request `1Gi` (for logs if not immediately shipped, temp files)

**B. Key Dependencies:**

2.  **Vector Database (LanceDB):**
    *   CPU: Request `0.5` CPU, Limit `1` CPU (can be bursty during indexing/complex queries)
    *   Memory: Request `1Gi`, Limit `2Gi` (adjust based on test dataset size)
    *   Persistent Storage: `10-20Gi` (NVMe SSD recommended; for embeddings and DB files)

3.  **Cache (Redis):**
    *   CPU: Request `0.1` CPU, Limit `0.5` CPU
    *   Memory: Request `256Mi`, Limit `1Gi`
    *   Persistent Storage: Optional for testing. If enabled for faster restarts with data: `1-5Gi`.

4.  **Messaging/Event Bus (Apache Iggy Server):**
    *   *(Note: Deploy if fully integrated and required for end-to-end flow testing. If using in-memory events for initial tests, these resources are not needed for Iggy itself.)*
    *   CPU: Request `0.25` CPU, Limit `0.75` CPU
    *   Memory: Request `512Mi`, Limit `1Gi`
    *   Persistent Storage: `5-10Gi` (for message stream persistence during tests)

**C. Observability Stack Components (Lean Test Setup):**

5.  **Prometheus Server:**
    *   CPU: Request `0.25` CPU, Limit `1` CPU
    *   Memory: Request `512Mi`, Limit `2Gi` (memory can grow with metric cardinality and retention)
    *   Persistent Storage: `10-20Gi` (for metrics with short retention, e.g., 7-14 days for testing)

6.  **Grafana:**
    *   CPU: Request `0.1` CPU, Limit `0.5` CPU
    *   Memory: Request `256Mi`, Limit `1Gi`
    *   Persistent Storage: `1-2Gi` (for dashboard definitions, user settings if persisted; often ConfigMaps are sufficient for dashboards)

7.  **Tracing Backend (e.g., Jaeger - all-in-one image for testing, or Grafana Tempo):**
    *   CPU: Request `0.25` CPU, Limit `1` CPU
    *   Memory: Request `512Mi`, Limit `2Gi`
    *   Persistent Storage: `10-20Gi` (for trace storage with short retention)

8.  **Log Aggregation System (e.g., Loki - single binary mode or simple scalable mode):**
    *   CPU: Request `0.25` CPU, Limit `1` CPU
    *   Memory: Request `512Mi`, Limit `2Gi`
    *   Persistent Storage: `20-30Gi` (for logs with short retention; adjust based on log volume)

*   **Storage Classes:** Ensure appropriate Kubernetes `StorageClass` definitions are available for persistent volumes (e.g., for DigitalOcean Block Storage, or local-path provisioner for single-node test clusters if applicable).

These lean estimates prioritize cost-effectiveness for a dedicated testing environment. For performance or soak testing, these allocations would likely need to be increased.

## 5. Networking Configuration

*   **Kubernetes Cluster Network:**
    *   Use DigitalOcean's default CNI plugin when deploying on DigitalOcean Kubernetes (DOKS).
    *   If on DigitalOcean, utilize VPC-native clusters for better integration and custom CIDR ranges.
*   **Service Discovery:** Use Kubernetes internal DNS for services to discover each other.
*   **Service Exposure:**
    *   KFM Agent Shell API: Expose via a Kubernetes `LoadBalancer` service (if external access needed for tests) or an `Ingress` controller. Internally, use `ClusterIP` services.
    *   Grafana: Expose via `LoadBalancer` or `Ingress` for UI access.
    *   Other services (DB, Redis, Iggy): Typically exposed internally via `ClusterIP` services, accessed by the KFM app.
*   **Network Policies:** Implement Kubernetes Network Policies to restrict traffic flow between pods for security (allow only necessary communication).

## 6. Environment Configuration Management

*   **Kubernetes ConfigMaps:** For non-sensitive application configuration, feature flags, external service URLs.
*   **Kubernetes Secrets:** For sensitive data (API keys, database passwords, Iggy credentials).
*   **Injection:** Mount ConfigMaps and Secrets as environment variables or files into containers.
*   **Version Control:** All Kubernetes manifests, ConfigMap/Secret definitions (excluding actual secret values), and Dockerfiles should be stored in Git.
*   **(Recommended) GitOps:** Consider tools like ArgoCD or Flux for managing deployments and configurations from Git.

## 7. Logging and Monitoring Setup

*   **Structured Logging:** KFM application should produce structured JSON logs.
*   **Log Aggregation:**
    *   Deploy Promtail (or a similar log collection agent compatible with Loki) as a Kubernetes DaemonSet.
    *   Forward logs to Loki.
*   **Metrics:**
    *   KFM app exposes metrics via `/metrics` (Prometheus format).
    *   Prometheus scrapes metrics from the app, Kubernetes components, Iggy, Redis, and the database.
*   **Tracing:**
    *   KFM app instrumented with OpenTelemetry.
    *   Traces exported to Jaeger.
*   **Visualization & Alerting:**
    *   Grafana for dashboards (metrics, logs, traces).
    *   Alertmanager (with Prometheus) for alerts on critical issues (error rates, resource limits, service unavailability).

## 8. Deployment Strategies

*   **Container Registry:** Use GitHub Container Registry (GHCR) to store application images, assuming the project's code is hosted on GitHub.
*   **Kubernetes Manifests:** Define all deployments, services, ConfigMaps, Secrets, etc., using Kubernetes YAML files.
*   **Deployment Tools:**
    *   `kubectl apply -f <manifest_dir>` for manual deployments.
    *   Helm charts for packaging and managing Kubernetes applications.
    *   Kustomize for customizing manifests for different environments.
    *   GitOps tools (ArgoCD, Flux) for automated deployments from Git.
*   **Update Strategy:** Use Kubernetes `Deployment` objects with a `RollingUpdate` strategy for zero-downtime updates of the KFM application.

## 9. Test Environment Stability and Reproducibility

*   **Infrastructure as Code (IaC):** All environment setup (Kubernetes cluster, cloud resources) should be defined using code (e.g., Terraform, Pulumi, or DigitalOcean CLI scripts).
*   **Immutable Images:** Docker images should be treated as immutable. No changes inside running containers; rebuild and redeploy images instead.
*   **Version Pinning:** Pin versions for OS, base images, application dependencies (`poetry.lock`), and Kubernetes components where possible.
*   **Data Seeding/Reset:** Develop scripts or mechanisms to populate the testing environment with necessary test data and to reset the state of databases/caches for repeatable tests.
*   **Documentation:** Keep this document and related configuration files up-to-date.

## 10. Security Considerations for Testing Environment

*   While not production, apply basic security hygiene:
    *   Use strong, unique credentials for database, Iggy, etc. (managed via Secrets).
    *   Limit public exposure of services (use internal IPs/services where possible).
    *   Regularly update container base images for security patches.
    *   Implement Network Policies.

This document will be updated as the testing environment requirements and design evolve. 