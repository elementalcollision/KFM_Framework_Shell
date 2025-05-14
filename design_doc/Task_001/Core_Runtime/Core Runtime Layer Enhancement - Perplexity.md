\# Architectural Review: Core Runtime Layer Enhancement Needed

\#\# Executive Summary

After reviewing the Agent Shell Architecture Design document, I identified a significant gap in the Core Runtime Layer section. While this component is mentioned as the central orchestrator for the entire system, it lacks the detailed elaboration found in other component sections. The Core Runtime needs a comprehensive subsection that describes its internal structure, responsibilities, and workflows to provide a complete architectural understanding.

\#\# Current State Analysis

The document presents a detailed architectural overview with Apache Iggy as the messaging backbone and describes numerous components in depth:

\- Provider Adapter Layer is thoroughly detailed with clear diagrams and interfaces\[2\]  
\- Personality Pack Manager has extensive documentation on structure and responsibilities\[2\]  
\- Memory Service provides comprehensive details on data structures and persistence\[2\]  
\- Apache Iggy Integration shows clear streaming patterns and configurations\[2\]  
\- API Layer and Observability Layer are well-structured with defined responsibilities\[2\]

However, the Core Runtime Layer-arguably the most critical component that orchestrates the entire system-lacks comparable details. The document mentions that it "serves as the central orchestrator that manages the Turn → Plan → Step workflow"\[2\] but does not elaborate on how this orchestration functions internally.

\#\# Gap Assessment

The current document:

1\. References Core Runtime sub-modules throughout other sections (TurnManager, PlanExecutor, StepProcessor, ContextManager, ConfigLoader, EventPublisherSubscriber)  
2\. Describes how other components interact with the Core Runtime  
3\. Does not provide a dedicated subsection explaining Core Runtime internals  
4\. Lacks a diagram showing Core Runtime's internal structure  
5\. Does not detail the Turn → Plan → Step workflow that is central to the system's operation

\#\# Recommendation: Add Core Runtime Layer Subsection

I recommend adding a detailed Core Runtime Layer subsection following the same pattern as other component descriptions. Below is an outline of what this section should include:

\#\#\# Core Runtime Layer

The Core Runtime Layer should be presented with a clear component diagram showing internal structure and relationships between sub-modules. The section should detail the processing flow from user input to agent response through the Turn → Plan → Step pipeline.

\`\`\`  
                                 API Layer  
                                     │ ▲  
                                     │ │ (User input/Agent responses)  
                                     ▼ │  
┌────────────────────────────────────────────────────────────────────────────┐  
│ Core Runtime Layer                                                         │  
├────────────────────────────────────────────────────────────────────────────┤  
│ ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐            │  
│ │   TurnManager    │ │   PlanExecutor   │ │  StepProcessor   │            │  
│ │ \- Turn Lifecycle │ │ \- Plan Generation│ │ \- Step Execution │            │  
│ │ \- Personality    │ │ \- LLM Prompting  │ │ \- Tool Invocation│            │  
│ │   Selection      │ │ \- Plan Validation│ │ \- State Updates  │            │  
│ └────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘            │  
│          │                    │                    │                       │  
│          │                    │                    │                       │  
│ ┌────────▼─────────┐ ┌────────▼─────────┐ ┌────────▼─────────┐            │  
│ │  ContextManager  │ │   ConfigLoader   │ │ EventPublisher   │            │  
│ │ \- Session State  │ │ \- Config Loading │ │ Subscriber       │            │  
│ │ \- Memory Bridge  │ │ \- Env Variables  │ │ \- Event Routing  │            │  
│ └──────────────────┘ └──────────────────┘ └──────────────────┘            │  
└────────────────────────────────────────────────────────────────────────────┘  
                │                    │                    │  
                ▼                    ▼                    ▼  
       Memory Service        Provider Adapters       Apache Iggy  
          (Context)           (LLM Calls)         (Event Streams)  
\`\`\`

\#\#\#\# Sub-Modules and Responsibilities

1\. \*\*\`TurnManager\`\*\*:  
   \* \*\*Responsibilities\*\*:  
     \* Manages the lifecycle of a user interaction "turn" from input to response  
     \* Coordinates with Personality Pack Manager to select and load appropriate PersonalityInstance  
     \* Initiates plan creation through PlanExecutor  
     \* Handles conversation context maintenance with ContextManager  
     \* Manages turns as atomic units of interaction with proper transaction semantics  
   \* \*\*Key Interactions\*\*: API Layer, PlanExecutor, Personality Pack Manager, ContextManager

2\. \*\*\`PlanExecutor\`\*\*:  
   \* \*\*Responsibilities\*\*:  
     \* Converts user input into a structured execution plan using LLM capabilities  
     \* Constructs appropriate prompts with personality system instructions and context  
     \* Validates generated plans against schema requirements  
     \* Breaks plans into discrete, executable steps  
     \* Handles plan retries or repairs when execution issues occur  
   \* \*\*Key Interactions\*\*: TurnManager, StepProcessor, Provider Adapter Layer

3\. \*\*\`StepProcessor\`\*\*:  
   \* \*\*Responsibilities\*\*:  
     \* Executes individual steps from the plan sequentially  
     \* Invokes appropriate tools from personality packs  
     \* Makes calls to LLM providers through the Provider Adapter Layer  
     \* Updates turn state after each step execution  
     \* Handles step failures with appropriate recovery or fallback mechanisms  
   \* \*\*Key Interactions\*\*: PlanExecutor, Provider Adapter Layer, Personality Pack Manager, Memory Service

4\. \*\*\`ContextManager\`\*\*:  
   \* \*\*Responsibilities\*\*:  
     \* Maintains in-memory state for the current turn  
     \* Coordinates with Memory Service for persistent storage  
     \* Retrieves and updates conversation history  
     \* Manages user preferences and session information  
     \* Ensures context is appropriately scoped for LLM prompts  
   \* \*\*Key Interactions\*\*: TurnManager, Memory Service

5\. \*\*\`ConfigLoader\`\*\*:  
   \* \*\*Responsibilities\*\*:  
     \* Loads and validates system configuration (from config.toml)  
     \* Manages environment variable access for secrets  
     \* Provides configuration values to other components  
     \* Supports runtime configuration changes where appropriate  
   \* \*\*Key Interactions\*\*: All Core Runtime components, Provider Adapter Layer

6\. \*\*\`EventPublisherSubscriber\`\*\*:  
   \* \*\*Responsibilities\*\*:  
     \* Interfaces with Apache Iggy for event-driven communication  
     \* Publishes events for turn lifecycle (started, completed, failed)  
     \* Publishes plan and step events for observability  
     \* Subscribes to system events that may affect turn processing  
     \* Facilitates asynchronous processing patterns across components  
   \* \*\*Key Interactions\*\*: Apache Iggy Integration, Observability Layer

\#\#\#\# Turn → Plan → Step Workflow

The Core Runtime implements the central workflow pattern that defines the Agent Shell's operation:

1\. \*\*Turn Initiation\*\*:  
   \* User input received via API Layer  
   \* TurnManager creates a new Turn with unique ID  
   \* Appropriate Personality selected (default or user-specified)  
   \* Context loaded from Memory Service

2\. \*\*Plan Generation\*\*:  
   \* PlanExecutor constructs prompt with:  
     \* Personality's system instructions  
     \* User input  
     \* Relevant context (conversation history, user preferences)  
   \* LLM call made through Provider Adapter Layer  
   \* Response parsed into structured Plan object  
   \* Plan validated against schema requirements

3\. \*\*Step Execution\*\*:  
   \* StepProcessor receives Plan with multiple Steps  
   \* Each Step executed sequentially (or with controlled parallelism where applicable)  
   \* Step types include:  
     \* LLM calls (through Provider Adapter)  
     \* Tool invocations (from Personality Pack)  
     \* Memory operations (through Memory Service)  
     \* External API calls (if supported by Personality)  
   \* Results of each Step stored in Context

4\. \*\*Response Generation\*\*:  
   \* Final Steps typically generate user-facing response  
   \* Response formatted according to API requirements  
   \* Turn state updated and persisted  
   \* Events published to Iggy for observability

\#\#\#\# Configuration (\`config.toml\`)

\`\`\`toml  
\[core\_runtime\]  
  \# Default behavior configuration  
  max\_turn\_duration\_seconds \= 60  
  max\_steps\_per\_plan \= 15  
  enable\_parallel\_steps \= false  
    
  \# Failure handling  
  max\_plan\_retries \= 2  
  max\_step\_retries \= 3  
    
  \# Default personality  
  default\_personality\_id \= "assistant\_v1"  
    
  \# Context limitations  
  max\_conversation\_turns \= 10  
  max\_context\_tokens \= 8000  
\`\`\`

This detailed Core Runtime section would complete the architectural overview by explaining the central orchestration mechanism that drives the entire Agent Shell system.

\#\# Conclusion

The Core Runtime Layer represents the heart of the Agent Shell architecture and requires a detailed explanation commensurate with its importance. Adding the suggested section would:

1\. Provide a comprehensive understanding of the system's central orchestration mechanism  
2\. Clarify how the Turn → Plan → Step workflow functions  
3\. Detail the responsibilities of each Core Runtime sub-module  
4\. Illustrate internal component relationships with a clear diagram  
5\. Create consistency with the level of detail provided for other architectural components

These additions would significantly enhance the architectural document's completeness and utility for implementation teams\[2\].

Sources  
\[1\] architecture\_document.md https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/64137834/9566d7b4-5a52-41dd-a01b-ed9bd4f7027f/architecture\_document.md  
\[2\] \[PDF\] LLMs Can't Plan, But Can Help Planning in LLM-Modulo Frameworks https://arxiv.org/pdf/2402.01817.pdf  
\[3\] Automating Galaxy Workflows \- Planemo \- Read the Docs https://planemo.readthedocs.io/en/latest/automating\_workflows.html  
\[4\] Process Orchestration: Guide to Benefits & Software | Camunda https://camunda.com/process-orchestration/  
\[5\] MCP Server and AI Tools | Wallaby https://wallabyjs.com/docs/features/mcp/  
\[6\] How can I create an executable to run on a certain processor ... https://stackoverflow.com/questions/1344631/how-can-i-create-an-executable-to-run-on-a-certain-processor-architecture-inste  
\[7\] The Context Manager Pattern — AFL-agent documentation https://pages.nist.gov/AFL-agent/en/v1.0.0/explanations/context\_manager.html  
\[8\] how do you folks manage config for your microservices? are ... \- Reddit https://www.reddit.com/r/golang/comments/1184t0q/how\_do\_you\_folks\_manage\_config\_for\_your/  
\[9\] The Publisher-Subscriber Design Pattern \- UMLBoard https://www.umlboard.com/design-patterns/publisher-subscriber.html  
\[10\] What is LLM Orchestration? \- IBM https://www.ibm.com/think/topics/llm-orchestration  
\[11\] Building the Ideal AI Agent: From Async Event Streams to Context ... https://dev.to/louis-sanna/building-the-ideal-ai-agent-from-async-event-streams-to-context-aware-state-management-33  
\[12\] Plan-and-Act: Improving Planning of Agents for Long-Horizon Tasks https://arxiv.org/html/2503.09572v2  
\[13\] \[PDF\] Ruffle\&Riley: Insights from Designing and Evaluating a Large ... https://www.xiameng.org/AIED\_2024\_\_\_Conversational\_Tutoring\_\_camera\_ready\_.pdf  
\[14\] How Do Out-of-Order Processors Work Anyway? \- Cadence Blogs https://community.cadence.com/cadence\_blogs\_8/b/breakfast-bytes/posts/how-do-out-of-order-processors-work-anyway  
\[15\] LLM Orchestration in 2025: Frameworks \+ Best Practices \- Orq.ai https://orq.ai/blog/llm-orchestration  
\[16\] Build an LLM from Scratch 7: Instruction Finetuning \- YouTube https://www.youtube.com/watch?v=4yNswvhPWCQ  
\[17\] Hardware-Aware Coding: CPU Architecture Concepts Every ... https://blog.codingconfessions.com/p/hardware-aware-coding  
\[18\] Fine Tuning LLMs and Optimizing Generative AI Architectures https://www.youtube.com/watch?v=zK0CNvmLqdM  
\[19\] \[PDF\] The ARM9 Family \- High Performance Microprocessors for ... https://www.cs.ucr.edu/\~bhuyan/cs162/LECTURE9a.pdf  
\[20\] Making LLM fine-tuning accessible with InstructLab \- YouTube https://www.youtube.com/watch?v=eaia9MstLNs  
\[21\] \[PDF\] Hazardless Processor Architecture Without Register Renaming https://www.cs.cmu.edu/afs/cs/academic/class/15740-f19/www/papers/micro18-irie-straight.pdf  
\[22\] Publisher-Subscriber pattern \- Azure Architecture Center https://learn.microsoft.com/en-us/azure/architecture/patterns/publisher-subscriber  
\[23\] Use an LLM to translate help documentation on-the-fly | Stephen ... https://www.linkedin.com/posts/turnersd\_use-an-llm-to-translate-help-documentation-activity-7273720975899209728-20JD  
\[24\] \[PDF\] Wisteria: Nurturing Scalable Data Cleaning Infrastructure https://amplab.cs.berkeley.edu/wp-content/uploads/2015/07/demo.pdf  
\[25\] Advanced Serverless Orchestration with AWS Step Functions https://www.youtube.com/watch?v=lKbeBBV1gyc  
\[26\] Enabling Code-Driven Evolution and Context Management for AI ... https://arxiv.org/abs/2409.16120  
\[27\] Difference between publisher-subscriber model and Event Driven ... https://www.reddit.com/r/leetcode/comments/1dcf9ph/difference\_between\_publishersubscriber\_model\_and/  
\[28\] Conversation Patterns | AutoGen 0.2 \- Microsoft Open Source https://microsoft.github.io/autogen/0.2/docs/tutorial/conversation-patterns/  
\[29\] \[PDF\] Architecture of a Database System \- University of California, Berkeley https://dsf.berkeley.edu/papers/fntdb07-architecture.pdf  
\[30\] AWS Step Functions \- Workflow Orchestration https://aws.amazon.com/step-functions/  
\[31\] Agents \- PydanticAI https://ai.pydantic.dev/agents/  
\[32\] Publish–subscribe pattern \- Wikipedia https://en.wikipedia.org/wiki/Publish%E2%80%93subscribe\_pattern  
\[33\] Turn Based RPG Help : r/godot \- Reddit https://www.reddit.com/r/godot/comments/1hejy0e/turn\_based\_rpg\_help/  
\[34\] \[PDF\] CHAPTER FIFTEEN https://faculty.etsu.edu/tarnoff/ntes2150/Ch15\_v02.pdf  
\[35\] contextlib — Utilities for with-statement contexts — Python 3.13.3 ... https://docs.python.org/3/library/contextlib.html  
\[36\] Best way to load configurations to microservice docker container https://stackoverflow.com/questions/42380585/best-way-to-load-configurations-to-microservice-docker-container  
\[37\] Design Pattern: Publisher-Subscriber \- DEV Community https://dev.to/nilebits/design-pattern-publisher-subscriber-5136  
\[38\] \[PDF\] IA-32 Processor Architecture \- Emory Computer Science http://www.cs.emory.edu/\~cheung/Courses/255/Syllabus/9-Intel/Resources/Book01-partial/chapt\_02\_IA-32-arch.pdf  
\[39\] Python context manager that measures time \- Stack Overflow https://stackoverflow.com/questions/33987060/python-context-manager-that-measures-time  
\[40\] Package time config management for microservices https://softwareengineering.stackexchange.com/questions/355348/package-time-config-management-for-microservices  
\[41\] Arm Fundamentals: Introduction to understanding Arm processors https://community.arm.com/arm-community-blogs/b/architectures-and-processors-blog/posts/arm-fundamentals-introduction-to-understanding-arm-processors  
\[42\] Context Managers and Python's with Statement \- Real Python https://realpython.com/python-with-statement/  
\[43\] 8 microservices best practices to remember | TechTarget https://www.techtarget.com/searchapparchitecture/tip/Microservices-best-practices-to-remember  
\[44\] What is LLM Orchestration? \- Portkey https://portkey.ai/blog/what-is-llm-orchestration  
\[45\] Automate tasks in your application using AI agents \- Amazon Bedrock https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html  
\[46\] AI agent context overview \- Make Help Center https://help.make.com/ai-agent-context-overview  
\[47\] How to manage configuration files in microservice architecture ... https://stackoverflow.com/questions/57699189/how-to-manage-configuration-files-in-microservice-architecture-among-multiple-de  
\[48\] Publish-subscribe pattern \- AWS Prescriptive Guidance https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/publish-subscribe.html  
\[49\] Introduction to Architectures for LLM Applications \- FRANKI T https://www.francescatabor.com/articles/2024/12/7/introduction-to-architectures-for-llm-applications  
\[50\] Guidelines and best practices for automating with AI agent https://help.webex.com/article/nelkmxk/Guidelines-and-best-practices-for-automating-with-AI-agent  
\[51\] Next-Level Agents: Unlocking the Power of Dynamic Context https://towardsdatascience.com/next-level-agents-unlocking-the-power-of-dynamic-context-68b8647eef89/  
\[52\] \[PDF\] LLMs Orchestration with Informatica Boosting AI Efficiency https://www.informatica.com/content/dam/informatica-cxp/techtuesdays-slides-pdf/LLMs%20Orchestration%20with%20Informatica%20Boosting%20AI%20Efficiency.pdf  
\[53\] LLM Agent Orchestration: A Step by Step Guide \- IBM https://www.ibm.com/think/tutorials/LLM-agent-orchestration  
\[54\] Intro to AI Agents and Architectures \- by Giancarlo Mori \- AI Uncovered https://giancarlomori.substack.com/p/intro-to-ai-agents-and-architectures  
\[55\] Saga orchestration pattern \- AWS Prescriptive Guidance https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/saga-orchestration.html  
\[56\] Agent architectures \- GitHub Pages https://langchain-ai.github.io/langgraph/concepts/agentic\_concepts/  
\[57\] Types of Agent Architectures: A Guide to Reactive, Deliberative, and ... https://smythos.com/ai-agents/agent-architectures/types-of-agent-architectures/  
\[58\] Orchestration Pattern: Managing Distributed Transactions https://www.gaurgaurav.com/patterns/orchestration-pattern/  
\[59\] \[PDF\] LLM Agent for Chip Design \- Hot Chips 2024 \- https://www.hc2024.hotchips.org/assets/program/tutorials/6-HC2024.nvidia.MarkRen.agent.v04.pdf  
\[60\] Architecture AI Agent | ClickUp™ https://clickup.com/p/ai-agents/architecture  
\[61\] \[PDF\] Oracle® GoldenGate \- Microservices Architecture Documentation https://docs.oracle.com/en/middleware/goldengate/core/23/coredoc/microservices-architecture-documentation.pdf  
\[62\] How to Build an LLM Agent With AutoGen: Step-by-Step Guide https://neptune.ai/blog/building-llm-agents-with-autogen  
\[63\] RoboPlanner: a pragmatic task planning framework for autonomous ... https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/ccs.2019.0025  
\[64\] Understanding LLM Agents: The ReAct Framework and Its Application https://www.linkedin.com/pulse/understanding-llm-agents-react-framework-its-rany-elhousieny-phd%E1%B4%AC%E1%B4%AE%E1%B4%B0-h4huc  
\[65\] Step: AI Agent \- Respond.io https://respond.io/help/workflows/step-ai-agent  
\[66\] Plan-and-Execute Agents \- LangChain Blog https://blog.langchain.dev/planning-agents/  
\[67\] Workflow for a ReAct Agent \- LlamaIndex https://docs.llamaindex.ai/en/stable/examples/workflow/react\_agent/  
\[68\] AI Agent Blueprint: Build, Train, & Deploy in 9 Steps \- LinkedIn https://www.linkedin.com/pulse/ai-agent-blueprint-build-train-deploy-9-steps-opengrowth-q9pif  
\[69\] Complete Guide to Building LangChain Agents with the LangGraph ... https://www.getzep.com/ai-agents/langchain-agents-langgraph  
\[70\] What is a ReAct Agent? \- IBM https://www.ibm.com/think/topics/react-agent  
\[71\] A Step-by-Step Guide to How to Build an AI Agent in 2025 \- Turing https://www.turing.com/resources/how-to-build-an-ai-agent  
\[72\] ReAct \- Prompt Engineering Guide https://www.promptingguide.ai/techniques/react  
\[73\] What Are AI Agents? Types, Examples, and Benefits | Triple Whale https://www.triplewhale.com/blog/ai-agents  
\[74\] ReAct \- ️   LangChain https://python.langchain.com/v0.1/docs/modules/agents/agent\_types/react/  
\[75\] My guide on what tools to use to build AI agents (if you are a newb) https://www.reddit.com/r/AI\_Agents/comments/1il8b1i/my\_guide\_on\_what\_tools\_to\_use\_to\_build\_ai\_agents/  
\[76\] Advanced configuration — kedro 0.19.12 documentation https://docs.kedro.org/en/stable/configuration/advanced\_configuration.html  
\[77\] LLM agents \- Agent Development Kit \- Google https://google.github.io/adk-docs/agents/llm-agents/  
\[78\] AI Floor Plan Generator – Best AI Interior Design Tool Online https://planner5d.com/use/ai-floor-plan-generator  
\[79\] How to Use Context Manager Pattern in JavaScript for Efficient Code ... https://dev.to/vishnusatheesh/how-to-use-context-manager-pattern-in-javascript-for-efficient-code-execution-57ef  
\[80\] kedro.config.OmegaConfigLoader https://docs.kedro.org/en/stable/api/kedro.config.OmegaConfigLoader.html  
\[81\] \[PDF\] Watch Every Step\! LLM Agent Learning via Iterative Step-Level ... https://aclanthology.org/2024.emnlp-main.93.pdf  
\[82\] Finch – Optimizing Architecture https://www.finch3d.com  
\[83\] Understanding the SAGA pattern with AWS Step Functions \- YouTube https://www.youtube.com/watch?v=lDEbFPKGozA  
\[84\] Make it easier to use the Config Loader · Issue \#2819 · kedro-org ... https://github.com/kedro-org/kedro/issues/2819  
\[85\] AgentBoard: An Analytical Evaluation Board of Multi-turn LLM Agents https://github.com/hkust-nlp/AgentBoard  
\[86\] What is LLM orchestration? Definition, Strategies, and Challenges https://www.infobip.com/glossary/llm-orchestration  
\[87\] Exploring Popular LLM Orchestration Frameworks \- LinkedIn https://www.linkedin.com/pulse/exploring-popular-llm-orchestration-frameworks-dr-rabi-prasad-hjxkc  
\[88\] Compare Top 11 LLM Orchestration Frameworks in 2025 https://research.aimultiple.com/llm-orchestration/  
\[89\] Introducing multi-turn conversation with an agent node for Amazon ... https://aws.amazon.com/blogs/machine-learning/introducing-multi-turn-conversation-with-an-agent-node-for-amazon-bedrock-flows-preview/  
\[90\] AI Agent Architecture: The Framework Behind Smart Decisions | Engati https://www.engati.com/blog/ai-agent-architecture  
\[91\] AI Agent Architecture: Explained with Real Examples https://www.azilen.com/blog/ai-agent-architecture/  
\[92\] AI Agent Architecture: Building Blocks for Intelligent Systems https://smythos.com/ai-agents/agent-architectures/ai-agent-architecture/  
\[93\] 10x Your AI Agents with this ONE Agent Architecture \- YouTube https://www.youtube.com/watch?v=AgN3RHSZGwI  
\[94\] Exploring the Key Components of AI Agent Architecture https://www.debutinfotech.com/blog/key-components-of-ai-agent-architecture  
\[95\] Orchestrator Pattern \- Thoughts? : r/SoftwareEngineering \- Reddit https://www.reddit.com/r/SoftwareEngineering/comments/rr8zp6/orchestrator\_pattern\_thoughts/  
\[96\] WeiminXiong/IPR: Watch Every Step\! LLM Agent Learning ... \- GitHub https://github.com/WeiminXiong/IPR  
\[97\] Agentic Architecture: Everything You Need to Know \- Astera Software https://www.astera.com/type/blog/agentic-architecture/  
\[98\] Agents \- ️   LangChain https://python.langchain.com/docs/concepts/agents/  
\[99\] Architecture \- ️   LangChain https://python.langchain.com/docs/concepts/architecture/  
\[100\] Conceptual guide \- ️   LangChain https://python.langchain.com/v0.2/docs/concepts/  
\[101\] Agent Architecture Langchain Overview | Restackio https://www.restack.io/p/agent-architecture-answer-langchain-agent-architecture-cat-ai  
\[102\] ReAct Agent — AgentIQ \- NVIDIA Docs Hub https://docs.nvidia.com/agentiq/1.0.0/components/react-agent.html  
\[103\] How to build an AI agent: 8-step tutorial \- Sendbird https://sendbird.com/blog/how-to-build-an-ai-agent  
\[104\] A Deep Dive into LangChain Agents \- TiDB https://www.pingcap.com/article/a-deep-dive-into-langchain-agents/  
\[105\] Experimenting with LLM Agents to generate their own plans ... \- Reddit https://www.reddit.com/r/OpenWebUI/comments/1h1oyyy/experimenting\_with\_llm\_agents\_to\_generate\_their/  
\[106\] A Visual Guide to LLM Agents \- by Maarten Grootendorst https://newsletter.maartengrootendorst.com/p/a-visual-guide-to-llm-agents  
\[107\] Mixtral Agents with Tools for Multi-turn Conversations | Niklas Heidloff https://heidloff.net/article/mixtral-agents-tools-multi-turn-sql/  
\[108\] Build an LLM-Powered API Agent for Task Execution https://developer.nvidia.com/blog/build-an-llm-powered-api-agent-for-task-execution/  
\[109\] INCREDIBLE AI Tools for Architectural plan generation \- YouTube https://www.youtube.com/watch?v=jMXhZB-udKI  
\[110\] Choreography pattern \- Azure Architecture Center | Microsoft Learn https://learn.microsoft.com/en-us/azure/architecture/patterns/choreography  
\[111\] The Context Manager Pattern — AFL-agent documentation https://pages.nist.gov/AFL-agent/en/v1.0.0/explanations/context\_manager.html

