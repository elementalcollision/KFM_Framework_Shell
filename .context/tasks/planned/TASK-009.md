---
title: Implement Testing Environment for KFM Agent Shell
type: task
status: planned
created: 2025-05-14T12:38:06Z
updated: 2025-05-14T12:38:06Z
id: TASK-009
priority: high
memory_types: [procedural]
dependencies: ["TASK-007"]
tags: [infrastructure, testing, kubernetes, docker, environment-setup]
---

## Description
This task covers the complete setup and deployment of the infrastructure testing environment for the KFM Agent Shell, as specified in `docs/infrastructure_testing_environment_specs.md`. The goal is to create a stable, reproducible, and observable environment for validating the KFM application.

## Objectives
- Provision and configure the foundational Kubernetes infrastructure.
- Deploy all core KFM application dependencies (LanceDB, Redis).
- Deploy the KFM Agent Shell application.
- Implement a comprehensive observability stack (Prometheus, Grafana, Jaeger, Loki).
- Configure networking, security, and deployment strategies.
- Ensure the environment is reproducible and documented.

## Steps

**Phase 1: Foundational Infrastructure Setup**
1.  Kubernetes Cluster Provisioning (DigitalOcean DOKS or local).
2.  Container Registry Setup (GitHub Container Registry).
3.  Create Kubernetes namespace (e.g., `kfm-testing`).
4.  Install/Verify Helm.

**Phase 2: Core Dependencies Deployment**
1.  Configure Persistent Storage (`StorageClass`).
2.  Deploy Redis (Helm chart).
3.  Deploy LanceDB (`StatefulSet` with PVC).

**Phase 3: Observability Stack Deployment**
1.  Deploy Prometheus & Grafana (`kube-prometheus-stack` Helm chart).
2.  Deploy Jaeger (all-in-one deployment).
3.  Deploy Loki & Promtail.
4.  Configure Grafana data sources (Prometheus, Loki, Jaeger if applicable).

**Phase 4: KFM Application Deployment**
1.  Finalize KFM Agent Shell `Dockerfile`.
2.  Build and push KFM image to GHCR.
3.  Create Kubernetes manifests for KFM app (Deployment, Service, ConfigMap, Secret).
4.  Deploy KFM app.
5.  Integrate KFM with observability (Prometheus scrape, Jaeger traces, Loki logs).

**Phase 5: (Optional) Apache Iggy Deployment**
1.  If required for current testing scope, deploy Apache Iggy.
2.  Configure KFM app to connect to Iggy.

**Phase 6: Configuration, Networking & Security**
1.  Deploy Ingress Controller (if needed).
2.  Create Ingress rules for services.
3.  Implement basic Kubernetes Network Policies.
4.  Populate production-like (but test-specific) ConfigMaps/Secrets.

**Phase 7: Testing, Iteration, and Documentation**
1.  Develop and run data seeding scripts/jobs.
2.  Perform initial smoke tests.
3.  Monitor resources and adjust allocations as needed.
4.  Document all deployment procedures and configurations.

## Progress
- Task planned.
- Specifications for the testing environment are detailed in `docs/infrastructure_testing_environment_specs.md`.

## Dependencies
- `TASK-007`: M6 – Beta launch (internal) - The testing environment is for the beta product.
- `docs/infrastructure_testing_environment_specs.md`: This document provides the detailed specifications.

## Notes
- All deployments should target the dedicated `kfm-testing` namespace.
- Resource requests and limits should adhere to those specified in `infrastructure_testing_environment_specs.md`, with adjustments made based on observed performance.
- All Kubernetes manifests and configuration scripts should be version-controlled.

## Next Steps
- Begin Phase 1: Foundational Infrastructure Setup.
  - Confirm Kubernetes cluster choice (DigitalOcean DOKS or local).
  - Verify GitHub Container Registry access and readiness. 