# Agent Shell Architecture Design with Apache Iggy Integration

Before diving into the detailed architecture, this report outlines a comprehensive design for the Agent Shell project as specified in the PRD, with Apache Iggy integrated as the message streaming backbone. The architecture emphasizes modularity, provider agnosticism, and high performance while leveraging Iggy's capabilities to replace a traditional Kafka-based message bus.

## Architecture Overview

The Agent Shell architecture follows a modular, event-driven approach with Apache Iggy serving as the central nervous system for asynchronous communication between components. This design supports the PRD's requirements for provider agnosticism, personality modularity, and observability.

### Core Architecture Principles

- **Decoupled Components**: Each architectural component operates independently, communicating via well-defined interfaces[2]
- **Event-Driven Communication**: Async event streams via Apache Iggy enable loose coupling[5]
- **Provider Abstraction**: Uniform interfaces to multiple LLM vendors[2]
- **Personality Modularity**: Self-contained personality packs that can be hot-loaded[2]
- **Observability First**: Comprehensive metrics and logging throughout the system[2]
- **Scalable Design**: Horizontal scaling through stateless components and Iggy's partitioning[5][6]

## Component Architecture

### Core Runtime Layer

The Core Runtime serves as the central orchestrator that manages the Turn → Plan → Step workflow.

```
┌────────────────────────────────┐
│ Core Runtime                   │
├────────────────────────────────┤
│ - Turn Manager                 │
│ - Plan Executor               │
│ - Step Processor              │
│ - Context Manager             │
│ - Event Publisher/Subscriber  │
└───────────────┬────────────────┘
                │
                ▼
        ┌───────────────┐
        │ Apache Iggy   │
        └───────────────┘
```

- **Turn Manager**: Coordinates the lifecycle of user interactions
- **Plan Executor**: Executes the generated plan for each turn
- **Step Processor**: Processes individual steps within a plan
- **Context Manager**: Maintains context across turns and steps
- **Event Publisher/Subscriber**: Interfaces with Iggy for event distribution[5][7]

### Provider Adapter Layer

This layer abstracts various LLM providers behind a consistent interface.

```
┌────────────────────────────────┐
│ Provider Adapter Layer         │
├────────────────────────────────┤
│ - Provider Factory             │
│ - Provider Interface           │
│ - Adapter Implementation       │
│   - OpenAI                     │
│   - Anthropic                  │
│   - Gemini                     │
│   - Others...                  │
│ - Retry/Backoff Logic          │
│ - Token Counter                │
└────────────────────────────────┘
```

- **Provider Interface**: Defines common methods (`generate`, `embed`, `moderate`)[2]
- **Adapter Implementations**: Provider-specific implementations of the interface[2]
- **Retry Logic**: Handles transient errors with exponential backoff[2]
- **Token Counter**: Tracks token usage for cost monitoring[2]

### Personality Pack Manager

Manages the loading and validation of personality packs.

```
┌────────────────────────────────┐
│ Personality Pack Manager       │
├────────────────────────────────┤
│ - Pack Loader                  │
│ - Manifest Parser              │
│ - Pack Validator               │
│ - Hot-Reload Controller        │
│ - Pack Registry                │
└────────────────────────────────┘
```

- **Pack Loader**: Loads personality packs from the filesystem
- **Manifest Parser**: Parses YAML manifests for metadata and configuration
- **Pack Validator**: Validates pack structure and content
- **Hot-Reload Controller**: Enables runtime reloading of packs[2]
- **Pack Registry**: Maintains registry of available personalities

### Memory Service

Provides persistent and temporary memory capabilities.

```
┌────────────────────────────────┐
│ Memory Service                 │
├────────────────────────────────┤
│ - Vector Store Adapter         │
│ - Cache Layer                  │
│ - Memory Operations            │
│ - TTL Manager                  │
└────────────────────────────────┘
```

- **Vector Store Adapter**: Interfaces with vector databases (pgvector, Weaviate, etc.)[2]
- **Cache Layer**: Redis-based short-term memory cache[2]
- **Memory Operations**: Standard operations (write, search, read, forget)
- **TTL Manager**: Manages time-to-live for memory entries

### Apache Iggy Integration

At the center of the architecture, Apache Iggy replaces Kafka as the message streaming platform.

```
┌────────────────────────────────┐
│ Apache Iggy Integration        │
├────────────────────────────────┤
│ - Stream Manager               │
│ - Topic Configuration          │
│ - Consumer Groups              │
│ - Client Abstraction           │
│ - Retention Policies           │
└────────────────────────────────┘
```

- **Stream Manager**: Creates and manages Iggy streams for different data types[7][8]
- **Topic Configuration**: Configures topics within streams for specific event types[7]
- **Consumer Groups**: Manages consumer groups for parallel processing[7][22]
- **Client Abstraction**: Abstracts Iggy client interaction for components[10][13]
- **Retention Policies**: Configures data retention based on business needs[7][19]

### API and Interface Layer

Provides external access to the Agent Shell.

```
┌────────────────────────────────┐
│ API and Interface Layer        │
├────────────────────────────────┤
│ - FastAPI Server               │
│ - WebSocket Handler            │
│ - CLI Interface                │
│ - Authentication               │
│ - Rate Limiting                │
└────────────────────────────────┘
```

- **FastAPI Server**: Serves HTTP and WebSocket endpoints[2]
- **WebSocket Handler**: Manages streaming responses to clients[2]
- **CLI Interface**: Provides command-line interface for interaction[2][5]
- **Authentication**: Handles user authentication and authorization
- **Rate Limiting**: Prevents API abuse

### Observability Layer

Enables monitoring and debugging of the system.

```
┌────────────────────────────────┐
│ Observability Layer            │
├────────────────────────────────┤
│ - Structured Logger            │
│ - Metrics Collector            │
│ - Trace Manager                │
│ - Cost Tracker                 │
│ - Health Monitor               │
└────────────────────────────────┘
```

- **Structured Logger**: Generates structured logs with correlation IDs[2]
- **Metrics Collector**: Collects and exposes Prometheus metrics[2][11]
- **Trace Manager**: Manages distributed tracing across components[14]
- **Cost Tracker**: Tracks token usage and calculates costs[2]
- **Health Monitor**: Monitors system health and component status

## Apache Iggy vs. Kafka

The architecture leverages Apache Iggy as a direct replacement for Kafka with several advantages:

### Performance Benefits

- **Rust-based Efficiency**: Built with Rust for predictable resource usage without GC spikes[3][5][17]
- **High Throughput**: Capable of processing millions of messages per second[5][22]
- **Low Resource Footprint**: More efficient resource utilization compared to Kafka[3][6]

### Simplicity Advantages

- **Single Binary**: Simpler deployment with no external dependencies[20]
- **Built-in Management**: Includes CLI and Web UI for administration[3][5][17]
- **Multiple Transport Protocols**: Supports TCP, QUIC, and HTTP transport[3][5][17]

### Feature Parity with Kafka

- **Persistent Append-only Log**: Messages stored persistently with similar semantics to Kafka[7][8]
- **Streams, Topics, Partitions**: Similar structural concepts to Kafka[7][8]
- **Consumer Groups**: Support for parallel processing with consumer groups[7][22]

### Advanced Capabilities

- **Message Deduplication**: Built-in support for eliminating duplicate messages[3][5]
- **Data Encryption**: Native support for securing sensitive data[3][5]
- **Multiple SDKs**: Support for Python, Rust, and other languages[3][5][10]

## Iggy Configuration for Agent Shell

### Stream and Topic Structure

```
agent-streams/
├── turns/
│   ├── user-messages
│   ├── agent-responses
│   ├── plans
│   └── steps
├── events/
│   ├── lifecycle-events
│   └── system-notifications
├── metrics/
│   ├── latency
│   ├── token-usage
│   └── costs
└── logs/
    ├── info
    ├── warning
    └── error
```

Each stream will be configured with appropriate partitioning, retention policies, and consumer groups:

- **Partitioning Strategy**: Partition by tenant_id or session_id for scalability[7]
- **Retention Policies**: Configure different retention periods based on data importance[7][19]
- **Consumer Groups**: Define consumer groups for different components for parallel processing[7][22]

## Implementation Considerations

### Python SDK Integration

The Agent Shell will leverage Iggy's Python SDK for integration:

```python
from iggy.client import IggyClient

# Create client with connection string
client = IggyClient.from_connection_string("iggy://user:password@localhost:8090")

# Create producer for sending messages
producer = client.producer("agent-streams", "turns").build()
producer.init()

# Send messages to Iggy
messages = [Message.from_str("Agent response data")]
producer.send(messages)

# Create consumer for reading messages
consumer = client.consumer_group("agent-shell", "agent-streams", "events").build()
consumer.init()

# Process incoming messages
async for message in consumer:
    # Handle event
    process_event(message)
```

This integration enables seamless communication between components via Iggy streams[10][13].

### Deployment Architecture

The Agent Shell deployment will consist of containerized components with Iggy as the central message bus:

```
┌─────────────────────────────────────────────────────────────────┐
│                     Kubernetes Cluster                          │
│                                                                 │
│  ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌─────────┐ │
│  │  API       │   │  Core      │   │ Provider   │   │ Memory  │ │
│  │  Service   │   │  Runtime   │   │ Adapters   │   │ Service │ │
│  └────────────┘   └────────────┘   └────────────┘   └─────────┘ │
│         │               │                │               │      │
│         └───────────────┼────────────────┼───────────────┘      │
│                         │                │                      │
│                 ┌───────────────────────────────┐              │
│                 │        Apache Iggy            │              │
│                 └───────────────────────────────┘              │
│                               │                                │
│                 ┌─────────────┴────────────────┐              │
│                 │        Observability         │              │
│                 └──────────────────────────────┘              │
└─────────────────────────────────────────────────────────────────┘
```

### Replication and Clustering

For production environments, Iggy's developing replication capabilities will be leveraged:

- **Viewstamped Replication**: Utilizing Iggy's evolving replication capabilities[12][21][23]
- **Cluster Configuration**: Configuring Iggy for high availability and fault tolerance[20][23]
- **Data Redundancy**: Ensuring critical data is replicated across nodes[12][21]

## Conclusion

This architecture design provides a comprehensive framework for implementing the Agent Shell project with Apache Iggy as the central message streaming platform. The design adheres to the PRD requirements while leveraging Iggy's advantages over traditional Kafka deployments.

### Next Steps

1. **Component Specification**: Detail the interfaces and classes for each component
2. **Iggy Integration Proof-of-Concept**: Develop a small POC to validate Iggy integration
3. **Development Roadmap**: Create detailed development tasks aligned with PRD milestones
4. **Stakeholder Review**: Present architecture for final approval from Engineering Lead and Product Owner

This architecture positions the Agent Shell project for success by providing a modern, efficient, and scalable foundation that meets all the requirements outlined in the PRD.

Sources
[1] TASK-001.md https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/64137834/5515ecf5-6951-4546-a3a7-22078f56c7bb/TASK-001.md
[2] prd.md https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/64137834/3aefb70d-4489-46ba-8494-980ad03e379c/prd.md
[3] iggy.apache.org https://iggy.apache.org
[4] Hello from Hyper-Efficient Message Streaming at Laser Speed. | Hyper-Efficient Message Streaming at Laser Speed. https://iggy.apache.org/
[5] Apache Iggy (Incubating) - Message streaming platform https://iggy.rs
[6] Top 6 Kafka Alternatives for Data Streaming in 2025 - Estuary https://estuary.dev/blog/kafka-alternatives/
[7] Architecture | Iggy.rs https://docs.iggy.rs/introduction/architecture
[8] Iggy joins the Apache Incubator https://blog.iggy.rs/posts/apache-incubator/
[9] Iggy.rs — one year of building the message streaming https://blog.iggy.rs/posts/one-year-of-building-the-message-streaming/
[10] Intro | Iggy.rs https://docs.iggy.rs/sdk/python/intro
[11] Using prometheus - Inspektor Gadget https://inspektor-gadget.io/docs/v0.38.1/legacy/prometheus/
[12] Technology Radar & current goals - Iggy.rs https://blog.iggy.rs/posts/technology-radar-and-currrent-goals/
[13] iggy::http::client - Rust - Docs.rs https://docs.rs/iggy/latest/iggy/http/client/index.html
[14] Apache Iggy (Incubating) - iggyrs #otel #opentelemetry - LinkedIn https://www.linkedin.com/posts/apache-iggy_iggyrs-otel-opentelemetry-activity-7252560060071956481-xhwN
[15] Apache Iggy: Hyper-Efficient Message Streaming at Laser Speed https://github.com/apache/iggy
[16] Introduction | Iggy.rs https://docs.iggy.rs/server/introduction
[17] Apache Iggy - The Apache Software Foundation https://iggy.apache.org
[18] Iggy.rs - Technology Radar & current goals https://iggy.apache.org/blogs/2024/10/28/technology-radar-and-currrent-goals
[19] Getting started - Iggy.rs https://docs.iggy.rs/introduction/getting-started
[20] Iggy Proposal - The Apache Software Foundation https://cwiki.apache.org/confluence/display/INCUBATOR/Iggy+Proposal
[21] Apache Iggy (Incubating) on X: "Replication is an indispensable ... https://x.com/ApacheIggy/status/1843160083284533645
[22] iggy/README.md at master · apache/iggy - GitHub https://github.com/apache/iggy/blob/master/README.md
[23] Sandbox for the future implementation of Iggy.rs clustering feature. https://github.com/iggy-rs/iggy-cluster-sandbox
[24] Apache Iggy (Incubating) (@iggy.rs) — Bluesky https://bsky.app/profile/iggy.rs
[25] Iggy.rs - Technology Radar & current goals : r/rust - Reddit https://www.reddit.com/r/rust/comments/1gdw742/iggyrs_technology_radar_current_goals/
[26] Iggy.rs — one year of building the message streaming : r/rust - Reddit https://www.reddit.com/r/rust/comments/1d35fsb/iggyrs_one_year_of_building_the_message_streaming/
[27] iggy-py · PyPI https://pypi.org/project/iggy-py/
[28] Transparent Benchmarking with Apache Iggy : r/rust - Reddit https://www.reddit.com/r/rust/comments/1irouxk/transparent_benchmarking_with_apache_iggy/
[29] The Guide to Apache Kafka Alternatives - Macrometa https://www.macrometa.com/event-stream-processing/kafka-alternatives
[30] IggyEx - official Elixir client SDK for Iggy.rs message streaming https://elixirforum.com/t/iggyex-official-elixir-client-sdk-for-iggy-rs-message-streaming/61212
[31] iggy 0.6.210 - Docs.rs https://docs.rs/crate/iggy/latest/source/Cargo.toml.orig
[32] Iggy.rs — one year of building the message streaming https://blog.iggy.rs/posts/one-year-of-building-the-message-streaming/
[33] Comparing Apache Kafka alternatives - Redpanda https://www.redpanda.com/guides/kafka-alternatives
[34] Stream Builder | Hyper-Efficient Message Streaming ... - Apache Iggy https://iggy.apache.org/docs/introduction/stream-builder
[35] Welcome | Hyper-Efficient Message Streaming at Laser Speed. https://iggy.apache.org/docs/
[36] About | Hyper-Efficient Message Streaming at Laser Speed. https://iggy.apache.org/docs/introduction/about/
[37] Metrics - Debugging - Lib.rs https://lib.rs/crates/metrics
[38] Compare BlueCats vs. Iggy in 2025 https://slashdot.org/software/comparison/BlueCats-vs-Iggy/
[39] Iggy.rs - message streaming platform : r/rust - Reddit https://www.reddit.com/r/rust/comments/151tjsr/iggyrs_message_streaming_platform/
[40] Official Python client SDK for Iggy.rs message streaming. - GitHub https://github.com/iggy-rs/iggy-python-client
[41] iggy - Tools for consistency based analysis of influence graphs and ... https://bioasp.github.io/iggy/
[42] PostgreSQL Cluster/Replication Aware backup Configuration https://community.commvault.com/self-hosted-q-a-2/postgresql-cluster-replication-aware-backup-configuration-4527
[43] iggy-py - PyPI https://pypi.org/project/iggy-py/0.2.0/
[44] About - Iggy.rs https://docs.iggy.rs/introduction/about
[45] iggy - crates.io: Rust Package Registry https://crates.io/crates/iggy/0.0.4
[46] Args in iggy::args - Rust - Docs.rs https://docs.rs/iggy/latest/iggy/args/struct.Args.html
[47] List of Prometheus Metrics - JupyterHub documentation https://jupyterhub.readthedocs.io/en/stable/reference/metrics.html
[48] High-level SDK | Iggy.rs https://docs.iggy.rs/introduction/high-level-sdk
[49] IGDB API docs: Getting Started https://api-docs.igdb.com
[50] How to Retrieve All Prometheus Metrics - A Step-by-Step Guide https://signoz.io/guides/how-to-get-all-the-metrics-of-an-instance-with-prometheus-api/
[51] Integrations | OpenTelemetry https://opentelemetry.io/ecosystem/integrations/
[52] iggy - crates.io: Rust Package Registry https://crates.io/crates/iggy/0.0.16
[53] Iggy | Public APIs | Postman API Network https://www.postman.com/iggyf
[54] Metric types - Prometheus https://prometheus.io/docs/concepts/metric_types/
[55] OpenTelemetry https://opentelemetry.io
[56] iggy-rs/iggy-node-http-client - GitHub https://github.com/iggy-rs/iggy-node-http-client
[57] Prometheus Metrics: A Practical Guide | Tigera - Creator of Calico https://www.tigera.io/learn/guides/prometheus-monitoring/prometheus-metrics/
[58] Iggy.rs - Technology Radar & current goals https://iggy.apache.org/blogs/2024/10/28/technology-radar-and-currrent-goals

> Written with [StackEdit](https://stackedit.io/).
