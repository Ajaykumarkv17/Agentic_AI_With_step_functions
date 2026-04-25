# Building a Production-Grade Multi-Agent AI Travel Concierge with AWS Step Functions and Amazon Bedrock

> A deep dive into how I built a fully serverless, multi-agent AI system that generates personalized travel itineraries for Indian travelers — using AWS Step Functions for orchestration, Amazon Bedrock for intelligence, and production-grade resilience patterns that actually hold up under failure.

---

## Table of Contents

1. [The Problem with Naive LLM Wrappers](#1-the-problem-with-naive-llm-wrappers)
2. [Why AWS Step Functions is the Right Backbone for Agentic AI](#2-why-aws-step-functions-is-the-right-backbone-for-agentic-ai)
3. [System Architecture — The Big Picture](#3-system-architecture--the-big-picture)
4. [The Parallel Agent Pattern — Four Agents, One Workflow](#4-the-parallel-agent-pattern--four-agents-one-workflow)
5. [Inside Each Agent — Bedrock, Circuit Breakers, and External APIs](#5-inside-each-agent--bedrock-circuit-breakers-and-external-apis)
6. [Resilience Engineering — Circuit Breakers, Retries, and Fallbacks](#6-resilience-engineering--circuit-breakers-retries-and-fallbacks)
7. [The Merge Lambda — Synthesizing Four Outputs into One Itinerary](#7-the-merge-lambda--synthesizing-four-outputs-into-one-itinerary)
8. [Infrastructure as Code with AWS CDK (Python)](#8-infrastructure-as-code-with-aws-cdk-python)
9. [The Frontend — Real-Time Workflow Visualization in Next.js](#9-the-frontend--real-time-workflow-visualization-in-nextjs)
10. [Key Design Decisions and Trade-offs](#10-key-design-decisions-and-trade-offs)
11. [Cost and Scalability](#11-cost-and-scalability)
12. [Lessons Learned and What is Next](#12-lessons-learned-and-what-is-next)

---

## 1. The Problem with Naive LLM Wrappers

When most developers first start building with large language models, the architecture looks something like this: user sends a message, you call an LLM API, you return the response. Simple, fast, works great for demos.

Then reality hits.

You need to call three different APIs to gather data before the LLM can reason over it. One of those APIs is flaky and times out 20% of the time. The LLM occasionally returns malformed JSON. Your workflow takes 45 seconds and the user has no idea what is happening. A single failure anywhere kills the entire request.

This is the wall every serious agentic AI project runs into. The LLM is not the hard part — the orchestration is.

I built the AI Travel Concierge to solve exactly this class of problem. The application takes a natural language trip description from an Indian traveler — something like "a 7-day family trip to Rajasthan with heritage forts, camel safari, and local food under ₹80,000" — and produces a complete, day-by-day personalized itinerary. Four specialized AI agents work in parallel to research destinations, optimize the budget in INR, analyze weather and monsoon patterns, and curate local experiences including festivals from the Indian Holiday Calendar.

The interesting engineering is not the LLM prompts. It is everything around them: how the agents are coordinated, how failures are handled gracefully, how the system stays responsive when external APIs go down, and how a user watches their itinerary come together in real time.

---

## 2. Why AWS Step Functions is the Right Backbone for Agentic AI

This is the question worth spending time on, because the answer is not obvious until you have tried to build agentic systems without it.

### The Core Tension in Agentic AI

LLMs are non-deterministic. They can take variable amounts of time, return unexpected output formats, get throttled, or simply fail. External APIs are unreliable. Multi-step workflows have complex dependency graphs. And yet, users expect consistent, reliable results.

You need something deterministic to manage something non-deterministic. That is exactly what Step Functions provides.

### What Step Functions Gives You That Lambda Alone Cannot

**Durable state across long-running workflows.** A Step Functions execution can run for up to a year. Each state transition is persisted. If a Lambda times out or crashes mid-workflow, Step Functions knows exactly where it was and can retry from that point. With raw Lambda chaining, you lose all of this — a crash means starting over.

**Native parallel execution with independent error handling.** The `Parallel` state is the single most important feature for multi-agent systems. You define N branches, they all execute concurrently, and each branch has its own `Retry` and `Catch` configuration. One agent failing does not block or kill the others. This is not something you can replicate cleanly with Lambda alone without building your own fan-out/fan-in logic with SQS or EventBridge.

**Built-in retry with exponential backoff and jitter.** Step Functions handles retry logic at the orchestration layer, not inside your Lambda code. You configure it once in the state machine definition and it applies consistently across every agent invocation. The jitter strategy (`FULL` jitter) is critical for multi-agent systems — when four agents all fail simultaneously and retry at the same interval, you get a thundering herd. Full jitter randomizes the backoff window and spreads the load.

**Catch blocks that route to fallback paths.** When all retries are exhausted, Step Functions' `Catch` block routes execution to a fallback state. In this system, each agent branch has a dedicated fallback Lambda that serves cached data from S3 or generates best-effort output using a lighter model. The workflow continues — it does not fail.

**Complete audit trail out of the box.** Every state transition, input, output, retry attempt, and error is logged in the Step Functions execution history. When something goes wrong in production, you open the AWS console, find the execution, and see exactly what happened at every step. This is invaluable for debugging LLM-based systems where the failure mode is often subtle.

**Visual workflow representation.** The Step Functions console renders your state machine as a live graph during execution. You can watch each agent branch light up as it runs. This is not just a nice-to-have — it dramatically reduces debugging time.

### Why Step Functions is Critical for Agentic AI — The Broader Picture

Beyond the specific features I used in this project, there are deeper reasons why Step Functions has become the go-to orchestration layer for agentic AI on AWS. These apply to any multi-agent system, not just travel planning.

**Orchestration of complex, multi-step workflows.** Agentic AI has moved well past the single-prompt paradigm. A real agent needs to retrieve data from multiple sources, reason over it, take action, and then verify the result — often across dozens of steps. Step Functions coordinates these actions as a visual, declarative workflow. It acts as the deterministic "brain" that guides the agent's non-deterministic reasoning through a structured execution path. Without it, you are writing brittle glue code that is impossible to debug at scale.

**Persistent memory and state management.** Agents need to maintain context across long-running interactions. A travel itinerary workflow might run for two minutes, but enterprise agentic workflows can span hours or days — waiting for data, approvals, or external events. Step Functions manages the "agentic loop" natively: it persists state at every transition, tracks progress through multiple steps, and can resume exactly where it left off after any interruption. Lambda alone gives you 15 minutes and no memory between invocations.

**Built-in resilience and error handling.** This is not optional for autonomous systems. When an agent operates without human supervision, it must handle failures gracefully — API timeouts, model throttling, malformed responses, partial data. Step Functions provides automatic retries with configurable backoff, catch blocks that route to fallback paths, and timeout enforcement at every step. The alternative is hand-rolling all of this inside your application code, which is error-prone and hard to test.

**Tool use and service integration.** Agentic AI is only as useful as the tools it can call. Step Functions offers native integrations with over 200 AWS services — DynamoDB, S3, Bedrock, SQS, EventBridge, and more — plus the ability to call any HTTP endpoint through Lambda. In this project, each agent calls external travel APIs, writes to DynamoDB, caches in S3, and invokes Bedrock, all orchestrated through a single state machine. Adding a new tool or data source means adding a state, not rewriting the orchestration logic.

**Human-in-the-loop integration.** Not every agentic decision should be fully autonomous. For high-stakes actions — booking a flight, charging a credit card, approving a budget — you may want a human to validate before the agent proceeds. Step Functions supports this natively through task tokens: the workflow pauses, sends a notification to a human reviewer, and resumes only when the token is returned with an approval. This pattern is essential for building trust in agentic systems that handle real money or sensitive data.

**Scalability and security at the infrastructure level.** Step Functions is serverless. It scales automatically with demand — from one workflow execution to thousands running concurrently — with no capacity planning. Each Lambda function in the workflow runs with fine-grained IAM permissions, so an agent that researches destinations cannot accidentally write to the billing table. This least-privilege model is critical for agentic systems where the blast radius of a misconfigured agent needs to be contained.

### The Alternative and Why It Falls Short

You could build this with a single Lambda that calls four other Lambdas using `asyncio.gather()`. It would work for the happy path. But you would need to implement your own retry logic, your own timeout handling, your own fallback routing, your own state persistence for long-running workflows, and your own execution history. You would essentially be rebuilding Step Functions, badly, inside a Lambda with a 15-minute timeout ceiling.

Step Functions is not just a convenience. For agentic AI workflows that need to be production-grade, it is the right architectural choice.

---

## 3. System Architecture — The Big Picture

The system is fully serverless. There are no EC2 instances, no containers, no servers to manage. Everything runs on managed AWS services.

### Architecture Diagram

![Architecture Diagram — AI Travel Concierge Multi-Agent System](./screenshots/architecture_diagram.png)
*Full system architecture showing the frontend, API layer, Step Functions orchestration with 4 parallel AI agents, resilience patterns, and data layer. Open [architecture_diagram.drawio](./architecture_diagram.drawio) for the editable version.*

### Request Lifecycle Sequence

![Sequence Diagram — Trip Request Lifecycle](./screenshots/sequence_diagram.png)
*End-to-end request flow: trip submission → parallel agent execution → merge → polling → itinerary display. Open [sequence_diagram.drawio](./sequence_diagram.drawio) for the editable version.*

```
User (Browser)
      |
      v
Next.js Frontend (localhost:3000)
      |
      v
Amazon API Gateway (REST API)
      |
      +-- POST /trips        --> Trip Submission Lambda
      +-- GET  /trips/{id}   --> Trip Retrieval Lambda
      +-- GET  /trips/{id}/status --> Status Lambda
                                        |
                                        v
                             AWS Step Functions State Machine
                             (Standard Workflow, 5-min timeout)
                                        |
                             +----------+----------+
                             |                     |
                    ValidateInput           UpdateStatusStarted
                             |
                    ParallelAgents (4 concurrent branches)
                    +--------+--------+--------+
                    |        |        |        |
              Destination  Budget  Weather  Experience
              Researcher  Optimizer Analyzer  Curator
                    |        |        |        |
              (each with Retry x3 + Catch -> Fallback Lambda)
                    |
                    v
               MergeResults Lambda
                    |
               UpdateStatusComplete
                    |
              +-----+-----+
              |           |
          DynamoDB        S3
       (ItineraryStore) (ArtifactStore)
```

### The Five CDK Stacks

The infrastructure is organized into five CDK stacks, each with a clear responsibility boundary:

| Stack | What it owns |
|---|---|
| **MockApiStack** | Mock API Gateway simulating IRCTC, IMD, tourism, and pricing APIs |
| **DataStack** | DynamoDB ItineraryStore table, DynamoDB CircuitBreakerTable, S3 ArtifactStore bucket |
| **ComputeStack** | All 10 Lambda functions with least-privilege IAM roles |
| **OrchestrationStack** | Step Functions state machine definition |
| **ApiStack** | API Gateway REST API with request validation and CORS |

Stacks are deployed in dependency order: Data → Compute → Orchestration → API. Cross-stack references use CloudFormation exports and SSM parameters to avoid circular dependencies.

### Data Flow

1. User submits a trip request through the Next.js form
2. API Gateway validates the request body (required fields, query max 2000 chars, positive budget in INR)
3. Trip Submission Lambda generates a UUID, creates an initial record in DynamoDB, and starts a Step Functions execution
4. Step Functions runs the parallel agent workflow
5. Each agent calls Amazon Bedrock and external travel APIs, updating its status in DynamoDB as it runs
6. The Merge Lambda synthesizes all four agent outputs into a day-by-day itinerary using Bedrock
7. The merged itinerary is persisted to DynamoDB and S3
8. The Next.js frontend polls the status endpoint every 4 seconds and transitions to the itinerary view on completion

---

## 4. The Parallel Agent Pattern — Four Agents, One Workflow

The heart of the system is the Step Functions `Parallel` state. Here is the CDK definition that builds it:

```python
def _build_parallel_agents(self) -> sfn.Parallel:
    parallel = sfn.Parallel(
        self,
        "ParallelAgents",
        comment="Execute all four AI agents in parallel",
        result_path="$.agent_outputs",
    )

    for agent_name, agent_fn in [
        ("DestinationResearcher", self._props.destination_researcher_fn),
        ("BudgetOptimizer", self._props.budget_optimizer_fn),
        ("WeatherAnalyzer", self._props.weather_analyzer_fn),
        ("ExperienceCurator", self._props.experience_curator_fn),
    ]:
        parallel.branch(self._build_agent_branch(agent_name, agent_fn))

    return parallel
```

Each branch is built with its own retry and catch configuration:

```python
def _build_agent_branch(self, agent_name: str, agent_fn) -> sfn.Chain:
    agent_task = tasks.LambdaInvoke(
        self, f"{agent_name}Invoke",
        lambda_function=agent_fn,
        payload=sfn.TaskInput.from_object({
            "itinerary_id.$": "$.itinerary_id",
            "trip_request.$": "$.trip_request",
        }),
        payload_response_only=True,
        result_path="$",
    )

    agent_task.add_retry(
        errors=["States.TaskFailed", "States.Timeout"],
        interval=Duration.seconds(2),
        max_attempts=3,
        backoff_rate=2.0,
        jitter_strategy=sfn.JitterType.FULL,
    )

    agent_task.add_catch(
        handler=fallback_task,
        errors=["States.ALL"],
        result_path="$.error",
    )

    return sfn.Chain.start(agent_task)
```

A few things worth noting here:

**`result_path="$.agent_outputs"`** on the Parallel state means Step Functions collects all four branch outputs into an array at `$.agent_outputs`. The Merge Lambda receives this array directly — no custom fan-in logic needed.

**`payload_response_only=True`** unwraps the Lambda response from the Step Functions envelope. Without this, you get the full `{ "Payload": { ... }, "StatusCode": 200 }` wrapper, which every downstream state would need to unwrap manually.

**`jitter_strategy=sfn.JitterType.FULL`** is not the default. The default is no jitter. For a system where four agents can all fail simultaneously (say, Bedrock gets throttled), full jitter is essential to prevent all four retry attempts from hitting the service at the same instant.

The retry sequence with full jitter looks like this:
- Attempt 1 fails → wait between 0 and 2 seconds
- Attempt 2 fails → wait between 0 and 4 seconds  
- Attempt 3 fails → wait between 0 and 8 seconds
- All attempts exhausted → Catch block fires → Fallback Lambda invoked

The entire workflow — from trip submission to completed itinerary — targets completion within 120 seconds under normal operating conditions.

---

## 5. Inside Each Agent — Bedrock, Circuit Breakers, and External APIs

All four agents share the same structural pattern. Understanding one means understanding all of them.

### The Agent Execution Flow

Every agent Lambda follows this sequence when invoked by Step Functions:

1. Parse `itinerary_id` and `trip_request` from the event
2. Update agent status to `"running"` in DynamoDB
3. Set up circuit-breaker-wrapped API clients for relevant external services
4. Query external APIs (IRCTC, IMD, tourism boards, pricing APIs)
5. Build a system prompt and user message for Bedrock
6. Call Bedrock Converse API through the circuit breaker
7. Parse and validate the LLM JSON response
8. Apply any deterministic post-processing (sorting, validation, flag computation)
9. Update agent status to `"completed"` (or `"failed"` on exception)
10. Return the structured output dict

### The Four Agents and What They Do

**Destination Researcher** queries IRCTC railway data, domestic flight APIs, and accommodation listings. It passes this external data alongside the trip request to Bedrock Nova Pro, which analyzes the request and returns ranked destination recommendations with transport options and accommodation suggestions. Destinations are sorted by `relevance_score` descending — this sorting is done in Python code, not by the LLM, to guarantee deterministic ordering.

**Budget Optimizer** queries transport pricing, accommodation pricing, and activity pricing APIs. Bedrock generates a two-tier budget breakdown — economy and comfort — with line-item costs for transport, accommodation, food, activities, and a contingency reserve, all in INR. Overage detection is handled in Python: if the economy tier total exceeds the stated budget, `overage_flag` is set to `True` and savings tips are populated.

**Weather Analyzer** queries the Indian Meteorological Department (IMD) API for forecasts. Bedrock interprets the raw weather data and generates human-readable advisories. The monsoon warning flag is computed deterministically in Python — if any travel date falls between June 1 and September 30, `monsoon_warning` is `True`. This is not left to the LLM because it is a precise date range check that should never be wrong.

**Experience Curator** is the most India-specific agent. It loads the Indian Holiday Calendar from S3, filters it to find holidays that overlap with the travel dates, and passes those overlapping festivals directly to Bedrock as context. The LLM is instructed to include festival-specific experiences and add them to the `festival_events` list. Experience types are validated in Python against an allowed set (`food`, `culture`, `adventure`, `relaxation`, `shopping`) — invalid types default to `culture`.

### Why the Bedrock Converse API

All agents use the Bedrock Converse API rather than `InvokeModel`. The Converse API provides a unified interface across all Amazon Nova models — the request format is identical whether you are calling Nova Pro or Nova Lite. This makes the primary-to-fallback model switch completely transparent:

```python
class BedrockClient:
    PRIMARY_MODEL = "us.amazon.nova-pro-v1:0"
    FALLBACK_MODEL = "us.amazon.nova-lite-v1:0"

    def converse(self, messages: list, system_prompt: str) -> dict:
        try:
            return self.cb.call(
                self._invoke, self.PRIMARY_MODEL, messages, system_prompt
            )
        except CircuitOpenError:
            # Primary model circuit breaker is OPEN — fall back to Nova Lite
            return self._invoke(self.FALLBACK_MODEL, messages, system_prompt)

    def _invoke(self, model_id: str, messages: list, system_prompt: str) -> dict:
        return self.client.converse(
            modelId=model_id,
            messages=messages,
            system=[{"text": system_prompt}],
        )
```

If you used `InvokeModel` instead, the request body format differs between models. Switching models would require changing the serialization logic everywhere. The Converse API eliminates that entirely.

### Deterministic Post-Processing — A Critical Design Principle

One pattern that runs through every agent is this: anything that can be computed deterministically in Python is computed in Python, not by the LLM.

- Sorting destinations by relevance score → Python `sort()`
- Detecting monsoon season overlap → Python date range check
- Filtering holidays by travel dates → Python date comparison
- Validating experience types → Python set membership check
- Computing budget overage → Python arithmetic

LLMs are excellent at reasoning, synthesis, and generating structured content from unstructured input. They are not reliable calculators or date parsers. Keeping deterministic logic in code and creative/analytical reasoning in the LLM gives you the best of both.

---

## 6. Resilience Engineering — Circuit Breakers, Retries, and Fallbacks

This is where the system earns its production-grade label. Most LLM applications handle failures by returning an error to the user. This system has three layers of defense before it ever does that.

### Layer 1 — Step Functions Retry with Exponential Backoff

The first line of defense is at the orchestration layer. Step Functions retries each agent Lambda up to three times with exponential backoff and full jitter before giving up. This handles transient failures: a momentary Bedrock throttle, a brief API timeout, a Lambda cold start that ran long.

This retry logic lives in the state machine definition, not in the Lambda code. That is an important distinction. Lambda-level retries are asynchronous and harder to reason about. Step Functions retries are synchronous within the workflow, visible in the execution history, and configurable without touching application code.

### Layer 2 — DynamoDB-Backed Circuit Breaker

The second layer protects against persistent failures. If an external API or the primary LLM model is consistently failing, retrying it repeatedly wastes time and can make things worse (thundering herd, rate limit escalation). The circuit breaker detects this pattern and stops trying.

The circuit breaker state is stored in DynamoDB, not in memory. This is a critical design decision for Lambda-based systems. Lambda functions are stateless and ephemeral — in-memory state is lost between invocations. With four agents running in parallel across potentially different Lambda instances, you need shared, consistent state. DynamoDB provides that.

Each external service and the primary Bedrock model has its own circuit breaker record:

```
CircuitBreakerTable
├── irctc_api          { state: CLOSED, failure_count: 0 }
├── flights_api        { state: CLOSED, failure_count: 0 }
├── accommodations_api { state: CLOSED, failure_count: 0 }
├── imd_api            { state: OPEN,   failure_count: 5, last_failure_at: "..." }
├── tourism_api        { state: CLOSED, failure_count: 2 }
├── transport_pricing_api { state: CLOSED, failure_count: 0 }
└── bedrock_nova_pro   { state: CLOSED, failure_count: 0 }
```

The state machine has three states:

- **CLOSED** — Normal operation. Requests pass through. Failures increment the counter.
- **OPEN** — Circuit tripped. After 5 consecutive failures, requests are blocked immediately and routed to fallback data. No more calls to the failing service.
- **HALF_OPEN** — Recovery probe. After 60 seconds, one test request is allowed through. Success → back to CLOSED. Failure → back to OPEN.

DynamoDB conditional writes handle the atomic state transitions, preventing race conditions when multiple Lambda invocations try to update the same circuit breaker record simultaneously:

```python
def _on_failure(self) -> None:
    response = self._table.update_item(
        Key={"service_name": self.service_name},
        UpdateExpression=(
            "SET failure_count = if_not_exists(failure_count, :zero) + :one, "
            "last_failure_at = :now, updated_at = :now"
        ),
        ExpressionAttributeValues={":zero": 0, ":one": 1, ":now": now},
        ReturnValues="ALL_NEW",
    )
    failure_count = int(response["Attributes"].get("failure_count", 0))
    current_state = response["Attributes"].get("state", CLOSED)

    if current_state == HALF_OPEN:
        self._transition_to(OPEN)
    elif current_state == CLOSED and failure_count >= self._failure_threshold:
        self._transition_to(OPEN)
```

The `if_not_exists` expression initializes the counter atomically on first write. The `ReturnValues="ALL_NEW"` gets the post-update value in a single round trip, avoiding a separate read.

### Layer 3 — Three-Tier Fallback Strategy

When both retries and the circuit breaker are exhausted, the Step Functions Catch block fires and invokes the Fallback Lambda. The fallback has its own three-tier strategy:

**Tier 1 — S3 Cache.** Every successful external API response is written to S3 under a structured key (`cache/{service}/{cache_key}`). The fallback Lambda checks S3 first. If a cached response exists, it returns it with a `stale_data` annotation. The itinerary is generated with slightly older data, but it is generated.

**Tier 2 — Nova Lite Best-Effort.** If no cache exists, the fallback Lambda calls Amazon Nova Lite directly — bypassing the circuit breaker entirely, since this is already the fallback path. Nova Lite generates best-effort recommendations based on the trip request alone, without external API data. The output is annotated as `best_effort`.

**Tier 3 — Partial Itinerary.** If Nova Lite also fails, the fallback returns a minimal response with an `is_fallback: true` flag and an empty data structure. The Merge Lambda handles this gracefully — it annotates the affected section with a notice and generates the itinerary from whatever data is available.

The result: the system almost never returns a hard error to the user. It degrades gracefully through multiple fallback levels, always producing something useful.

---

## 7. The Merge Lambda — Synthesizing Four Outputs into One Itinerary

After all four agents complete (or fall back), Step Functions collects their outputs into an array and passes it to the Merge Lambda. This is where the magic of synthesis happens.

The Merge Lambda receives something like this:

```json
{
  "itinerary_id": "uuid-here",
  "trip_request": { "query": "...", "dates": {...}, "budget": 80000 },
  "agent_outputs": [
    { "agent": "destination_researcher", "is_fallback": false, "destinations": [...] },
    { "agent": "budget_optimizer", "is_fallback": false, "budget_tiers": [...] },
    { "agent": "weather_analyzer", "is_fallback": true, "daily_forecasts": [...] },
    { "agent": "experience_curator", "is_fallback": false, "experiences": [...] }
  ]
}
```

The Lambda first scans the outputs for any with `is_fallback: true` and builds `Notice` objects for them. These notices will appear in the final itinerary so the user knows which sections used fallback data.

Then it calls Bedrock Nova Pro with a carefully structured prompt that includes all four agent outputs and instructs the model to synthesize a day-by-day itinerary with morning, afternoon, and evening activity slots for each day. The prompt enforces a strict JSON output schema — no prose, no markdown, just the JSON object.

```python
user_text = (
    f"Trip request:\n{json.dumps(trip_request)}\n\n"
    f"Destination Researcher output:\n{json.dumps(destination_output)}\n\n"
    f"Budget Optimizer output:\n{json.dumps(budget_output)}\n\n"
    f"Weather Analyzer output:\n{json.dumps(weather_output)}\n\n"
    f"Experience Curator output:\n{json.dumps(experience_output)}"
)
```

The model synthesizes all of this into a structured day plan. Weather data informs activity suggestions and the packing advisory. Budget data determines which tier to use for cost estimates. Festival events from the Experience Curator get slotted into the appropriate days. Transport and accommodation details from the Destination Researcher fill in the logistics.

The final itinerary is persisted in two places:

- **DynamoDB** — The `itinerary` attribute on the existing record is updated, and `status` is set to `"completed"`. This is what the status endpoint reads.
- **S3** — The full itinerary JSON is stored at `itineraries/{id}/itinerary.json`, and each agent's raw output is stored at `itineraries/{id}/agent_outputs/{agent}.json`. S3 handles large payloads that would exceed DynamoDB's 400KB item limit.

One implementation detail worth noting: DynamoDB does not accept Python `float` values — it requires `Decimal`. The merge handler recursively converts all floats before writing:

```python
def _floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimal(v) for v in obj]
    return obj
```

This is the kind of detail that does not show up in tutorials but will break your production deployment if you miss it.

---

## 8. Infrastructure as Code with AWS CDK (Python)

The entire backend is defined in Python CDK, organized into five stacks. Using CDK rather than raw CloudFormation or the console gives you type safety, reusable constructs, and the ability to express infrastructure logic in real code.

### Stack Separation and Cross-Stack References

Each stack has a clear ownership boundary. The DataStack owns all storage. The ComputeStack owns all compute. The OrchestrationStack owns the workflow. The ApiStack owns the public interface.

Cross-stack references are handled through CloudFormation exports for most resources, and through an SSM parameter for the state machine ARN. The SSM approach was necessary to break a circular dependency: the ComputeStack needs to grant the Trip Submission Lambda permission to start the state machine, but the state machine ARN is not known until the OrchestrationStack is deployed. The solution is to store the ARN in SSM at deploy time and read it at Lambda runtime:

```python
# In OrchestrationStack — store ARN in SSM after state machine is created
ssm.StringParameter(
    self, "StateMachineArnParam",
    parameter_name="/travel-concierge/state-machine-arn",
    string_value=self.state_machine.state_machine_arn,
)

# In ComputeStack — grant SSM read permission to Trip Submission Lambda
self.trip_submission_fn.add_to_role_policy(
    iam.PolicyStatement(
        actions=["ssm:GetParameter"],
        resources=[
            Stack.of(self).format_arn(
                service="ssm",
                resource="parameter",
                resource_name="travel-concierge/*",
            )
        ],
    )
)
```

### Least-Privilege IAM

Every Lambda function has the minimum permissions it needs and nothing more. The pattern is explicit grants rather than wildcard policies:

```python
# Agent functions get read/write on both DynamoDB tables, S3, and Bedrock
for fn in [destination_researcher_fn, budget_optimizer_fn, ...]:
    itinerary_table.grant_read_write_data(fn)
    circuit_breaker_table.grant_read_write_data(fn)
    artifact_bucket.grant_read_write(fn)
    fn.add_to_role_policy(bedrock_policy)

# Status Lambda only needs DynamoDB read
itinerary_table.grant_read_data(self.status_fn)

# Trip Retrieval Lambda only needs DynamoDB read and S3 read
itinerary_table.grant_read_data(self.trip_retrieval_fn)
artifact_bucket.grant_read(self.trip_retrieval_fn)
```

The Bedrock policy is the one place where a wildcard resource is unavoidable — Bedrock model ARNs are not predictable at CDK synth time. Everything else is scoped to specific resource ARNs.

### Lambda Configuration

Agent Lambdas (the four AI agents and the Merge Lambda) run with 512 MB memory and 60-second timeouts. The Merge Lambda gets 90 seconds because it synthesizes all four outputs and makes a Bedrock call. API-facing Lambdas (submission, retrieval, status) run with 256 MB and 10-second timeouts — they should be fast.

All Lambdas use Python 3.12 and share the same code asset (the entire `backend/` directory), with the handler path specified per function. This avoids maintaining separate deployment packages while keeping the code organized in logical modules.

---

## 9. The Frontend — Real-Time Workflow Visualization in Next.js

The frontend is a Next.js 14 application with TypeScript. It has two pages: a landing page with the trip request form, and a trip page that shows the workflow in progress and then the completed itinerary.

### The Landing Page — Trip Request Form

![Landing Page — Trip Request Form](./screenshots/landing_page.png)
*The landing page where travelers describe their dream trip in natural language, select dates, set a budget in INR, and choose optional preferences like food, culture, or adventure.*

### The Workflow Visualization

The most interesting frontend component is the workflow status view. It displays four agent cards — Destination Research, Budget Optimization, Weather Analysis, Experience Curation — each showing its current status with visual indicators.

```typescript
const AGENTS = [
  { key: 'destination_researcher', label: 'Destination Research', icon: '🗺' },
  { key: 'budget_optimizer',       label: 'Budget Optimization',  icon: '💰' },
  { key: 'weather_analyzer',       label: 'Weather Analysis',     icon: '🌤' },
  { key: 'experience_curator',     label: 'Experience Curation',  icon: '🎭' },
];
```

The component polls `GET /trips/{id}/status` every 4 seconds using a recursive `setTimeout` pattern (not `setInterval`, which can stack up if responses are slow):

```typescript
useEffect(() => {
  let timer: ReturnType<typeof setTimeout>;
  let cancelled = false;

  async function tick() {
    if (cancelled) return;
    const done = await poll();
    if (!done && !cancelled) timer = setTimeout(tick, 4000);
  }
  tick();

  return () => { cancelled = true; clearTimeout(timer); };
}, [poll]);
```

Polling stops when the workflow status is `"completed"` or `"failed"`. At that point, the component calls `onComplete()`, which triggers the parent page to fetch the full itinerary and transition to the itinerary view.

A pipeline visualization below the agent cards shows the overall workflow progress: Submitted → Agents → Merging → Complete. Each step lights up as the workflow advances through those states.

![Workflow Status — Parallel Agents in Progress](./screenshots/workflow_status.png)
*Real-time workflow visualization showing four AI agents running in parallel. Each card transitions through pending → running → completed/failed/fallback. The pipeline bar at the bottom tracks overall progress.*

### The Itinerary View

The itinerary page renders the day-by-day plan with expandable day cards. Each card shows the destination, date, weather summary, and daily cost in the header. Expanding a card reveals the morning, afternoon, and evening activity slots, transport details, and accommodation.

Festival events get a special visual treatment — a highlighted border and a "Festival Event" badge — so travelers immediately see which activities are tied to Indian holidays.

![Final Itinerary — Day-by-Day View](./screenshots/itinerary_page.png)
*The completed itinerary rendered as expandable day cards with morning/afternoon/evening activity slots, weather summaries, transport details, accommodation info, and costs in INR. Sections that used fallback data are marked with notices at the top.*

Fallback notices appear at the top of the page when any agent used cached or best-effort data, so users know which sections might be less precise.

The INR formatting uses the `en-IN` locale for proper Indian number formatting (lakhs and crores notation):

```typescript
function formatINR(n: number): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0
  }).format(n);
}
```

---

## 10. Key Design Decisions and Trade-offs

Every architecture involves trade-offs. Here are the ones that shaped this system most significantly.

### Polling vs WebSockets for Status Updates

The frontend polls a REST endpoint every 4 seconds rather than using WebSockets or Server-Sent Events. This was a deliberate choice.

WebSockets would give lower latency status updates, but they require a persistent connection management layer — either API Gateway WebSocket APIs (which add complexity and cost) or a dedicated WebSocket server (which breaks the serverless model). For a workflow that takes 30-120 seconds, 4-second polling latency is completely acceptable. The simpler architecture wins.

### DynamoDB vs In-Memory for Circuit Breaker State

Lambda functions are stateless. Any in-memory state is lost when the function instance is recycled or when a new instance is created. With four agents potentially running on four different Lambda instances simultaneously, in-memory circuit breaker state would be inconsistent — one instance might think a service is healthy while another has already tripped the circuit.

DynamoDB provides shared, consistent state across all Lambda invocations. The slight latency overhead of a DynamoDB read on each API call is worth the correctness guarantee.

### S3 vs DynamoDB for Itinerary Storage

DynamoDB has a 400KB item size limit. A complete multi-day itinerary with all agent outputs can easily exceed this. S3 has no practical size limit and is cheaper for large objects. The pattern used here — store metadata and status in DynamoDB, store large payloads in S3, reference S3 keys from DynamoDB — is a standard pattern for this class of problem.

### Standard vs Express Step Functions Workflow

Standard workflows were chosen over Express workflows. Standard workflows support executions up to one year, have exactly-once execution semantics, and maintain full execution history in the console. Express workflows are cheaper and faster to start but have at-least-once semantics and limited history retention.

For a user-facing workflow where you want to debug failures and guarantee that each trip request is processed exactly once, Standard is the right choice. The cost difference is negligible at this scale.

### Bedrock Converse API vs InvokeModel

The Converse API provides a unified interface across all Amazon Nova models. Switching from Nova Pro to Nova Lite requires changing only the `modelId` string — the request and response format is identical. This made the primary-to-fallback model switch trivial to implement and test.

`InvokeModel` requires model-specific request body serialization. If you use it and later need to swap models, you are refactoring serialization code across every call site.

---

## 11. Cost and Scalability

One of the most compelling aspects of this architecture is the cost profile.

### Cost Breakdown for Light Usage

| Service | Estimated Monthly Cost |
|---|---|
| AWS Lambda | Free tier (~1M requests/month) |
| Amazon DynamoDB | Free tier (25 RCU/WCU) |
| AWS Step Functions | ~$0.025 per 1,000 state transitions |
| Amazon Bedrock (Nova Pro) | ~$0.0008/1K input tokens, ~$0.0032/1K output tokens |
| Amazon API Gateway | ~$3.50 per million requests |
| Amazon S3 | Negligible |

For a development or demo workload with a few trips per day, the total cost is under $5 per month. The dominant cost at scale will be Bedrock inference — each trip request involves five Bedrock calls (four agents plus the merge), each consuming several thousand tokens.

### Scalability

The serverless architecture scales automatically. Lambda scales to thousands of concurrent executions. DynamoDB with PAY_PER_REQUEST billing scales with traffic. Step Functions Standard workflows support up to 2,000 concurrent executions per account by default (adjustable via service quota increase).

The circuit breaker pattern also contributes to scalability under stress. When an external API is struggling, the circuit breaker prevents the system from amplifying the problem by sending more requests to an already-overloaded service.

---

## 12. Lessons Learned and What is Next

### What Worked Well

**Step Functions as the orchestration backbone** was the right call from day one. The parallel execution, built-in retry, catch blocks, and execution history made the system dramatically easier to build and debug than any Lambda-chaining approach would have been.

**The Bedrock Converse API** made the primary-to-fallback model switch completely transparent. There was zero code change required in the agent logic when switching between Nova Pro and Nova Lite — just a different model ID string.

**DynamoDB-backed circuit breakers** solved the stateless Lambda problem cleanly. The atomic conditional writes prevent race conditions without needing distributed locks.

**Deterministic post-processing in Python** — sorting, date checks, type validation — kept the LLM focused on what it is good at (synthesis and reasoning) and kept the code predictable and testable.

### What Was Harder Than Expected

**The SSM parameter workaround for circular CDK dependencies** was not obvious. When ComputeStack needs to know the state machine ARN (to grant StartExecution permission) but OrchestrationStack depends on ComputeStack (to get Lambda function references), you have a circular dependency. Storing the ARN in SSM and reading it at Lambda runtime breaks the cycle cleanly, but it took some iteration to land on this pattern.

**DynamoDB's float-to-Decimal requirement** is a silent failure mode. The `put_item` call succeeds but the data is wrong if you pass Python floats. The recursive conversion helper is essential and easy to forget.

**Prompt engineering for structured JSON output** required more iteration than expected. Getting the LLM to consistently return valid JSON without any surrounding prose, especially for the complex merge prompt, required explicit instructions and a few rounds of refinement.

### What is Next

There are several natural extensions to this system:

**Streaming responses** — Instead of polling for completion, use Step Functions callbacks with a task token to push status updates to the frontend via API Gateway WebSocket or Server-Sent Events. This would reduce perceived latency significantly.

**Persistent user accounts** — Add Amazon Cognito for authentication and associate itineraries with user accounts. Users could save, share, and revisit past itineraries.

**Real external API integrations** — The current system uses a mock API Gateway to simulate IRCTC, IMD, and tourism APIs. Integrating real APIs would make the destination research and weather data genuinely accurate.

**Itinerary refinement** — Add a conversational refinement loop where users can ask follow-up questions ("make it more budget-friendly" or "add a day in Jaipur") and the system updates the itinerary incrementally.

**Observability** — Add structured logging with correlation IDs, CloudWatch dashboards for circuit breaker state, and X-Ray tracing across the full request path from API Gateway through Step Functions to each Lambda.

---

## Conclusion

Building production-grade agentic AI is fundamentally an orchestration problem. The LLM is one component in a larger system that needs to handle failures gracefully, coordinate parallel work, maintain state across long-running workflows, and degrade intelligently when things go wrong.

AWS Step Functions provides the deterministic orchestration backbone that makes non-deterministic AI agents reliable. The Parallel state enables true concurrent agent execution. Native retry with exponential backoff and full jitter handles transient failures. Catch blocks route to fallback paths when retries are exhausted. The execution history gives you complete visibility into every workflow run.

Combined with Amazon Bedrock's Converse API for model-agnostic LLM inference, DynamoDB-backed circuit breakers for distributed resilience state, and a three-tier fallback strategy, the result is a system that handles the messy reality of production AI workloads — not just the happy path.

The full source code, CDK stacks, and deployment guide are available in the project repository. If you are building agentic AI systems on AWS, I hope the patterns here — particularly the circuit breaker implementation, the parallel agent orchestration, and the fallback strategy — give you a solid foundation to build on.

---

*Built with AWS Step Functions, Amazon Bedrock (Nova Pro + Nova Lite), AWS Lambda (Python 3.12), Amazon DynamoDB, Amazon S3, Amazon API Gateway, AWS CDK (Python), and Next.js 14.*
