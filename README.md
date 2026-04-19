# AI Travel Concierge — Multi-Agent Agentic AI with AWS Step Functions

A serverless, multi-agent application that generates personalized travel itineraries for Indian travelers. Users describe their dream trip in natural language, and four parallel AI agents — powered by Amazon Bedrock — research destinations, optimize budgets, analyze weather, and curate local experiences in real time.

![Architecture](arch_1.png)

## Architecture

```
Frontend (Next.js)          Backend (AWS)
──────────────────          ──────────────────────────────────────
localhost:3000  ──────►     API Gateway
                              ├── POST /trips        → Trip Submission Lambda
                              ├── GET /trips/{id}     → Trip Retrieval Lambda
                              └── GET /trips/{id}/status → Status Lambda
                                       │
                                       ▼
                              Step Functions State Machine
                              ┌─ Destination Researcher ─┐
                              ├─ Budget Optimizer ────────┤  (parallel)
                              ├─ Weather Analyzer ────────┤
                              └─ Experience Curator ──────┘
                                       │
                                       ▼
                                 Merge Lambda
                                       │
                              ┌────────┴────────┐
                              DynamoDB          S3
```

### How It Works

1. User submits a natural language trip request (destination, dates, budget in INR)
2. API Gateway validates the request and triggers a Step Functions workflow
3. Four AI agents run **in parallel**, each calling Amazon Bedrock (Nova Pro) and external travel APIs:
   - **Destination Researcher** — researches destinations, transport routes, accommodations
   - **Budget Optimizer** — creates economy and comfort budget tiers in INR
   - **Weather Analyzer** — fetches forecasts and monsoon/seasonal advisories
   - **Experience Curator** — curates street food, festivals, cultural activities, hidden gems
4. A Merge Lambda combines all agent outputs into a cohesive day-by-day itinerary
5. The Next.js frontend polls for real-time status and renders the final itinerary

### Resilience Patterns

- **Circuit Breakers** (DynamoDB-backed) — protect every external API and the primary LLM model. After 5 consecutive failures, the circuit opens and requests are routed to fallback data.
- **Retry with Exponential Backoff + Jitter** — Step Functions native retry (2s → 4s → 8s) with full jitter on each agent branch.
- **LLM Model Fallback** — Amazon Nova Pro (primary) automatically falls back to Amazon Nova Lite when throttled or unavailable.
- **Cached Fallback Data** — S3-cached API responses are served when circuits are open. If no cache exists, Nova Lite generates best-effort recommendations.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js 14, TypeScript, React 18 |
| API | Amazon API Gateway (REST) |
| Orchestration | AWS Step Functions (Standard) |
| Compute | AWS Lambda (Python 3.12) |
| AI/ML | Amazon Bedrock — Nova Pro (primary), Nova Lite (fallback) |
| Database | Amazon DynamoDB (Itinerary Store + Circuit Breaker Table) |
| Storage | Amazon S3 (Artifact Store + API cache) |
| IaC | AWS CDK (Python) |

## Project Structure

```
├── backend/
│   ├── lambdas/
│   │   ├── destination_researcher/   # Destination research agent
│   │   ├── budget_optimizer/         # Budget optimization agent
│   │   ├── weather_analyzer/         # Weather & season analysis agent
│   │   ├── experience_curator/       # Local experience curation agent
│   │   ├── merge/                    # Combines agent outputs into itinerary
│   │   ├── fallback/                 # Serves cached/best-effort data on failure
│   │   ├── trip_submission/          # Validates & starts workflow
│   │   ├── trip_retrieval/           # Fetches completed itineraries
│   │   ├── status/                   # Returns real-time workflow status
│   │   ├── status_update/            # Updates status in DynamoDB
│   │   └── mock_api/                 # Mock external travel APIs
│   ├── shared/                       # Shared modules (Bedrock client, circuit breaker, API client)
│   └── reference/                    # Indian holiday calendar JSON
├── cdk/
│   ├── stacks/
│   │   ├── data_stack.py             # DynamoDB + S3
│   │   ├── compute_stack.py          # Lambda functions + layers
│   │   ├── orchestration_stack.py    # Step Functions state machine
│   │   ├── api_stack.py              # API Gateway
│   │   └── mock_api_stack.py         # Mock API Gateway
│   ├── app.py                        # CDK app entry point
│   └── requirements.txt
└── frontend/
    └── src/
        ├── app/                      # Next.js pages (home + trip view)
        ├── components/               # WorkflowStatus visualization
        ├── lib/                      # API client
        └── types/                    # TypeScript interfaces
```

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.12+ | `python --version` |
| Node.js | 18+ | `node --version` |
| AWS CLI | 2.x | `aws --version` |
| AWS CDK CLI | 2.150+ | `npx cdk --version` |
| AWS Account | — | `aws sts get-caller-identity` |

### Enable Bedrock Model Access

In the AWS Console → **Amazon Bedrock** → **Model access**:
1. Request access to **Amazon Nova Pro** and **Amazon Nova Lite**
2. Recommended regions: `us-east-1`, `us-west-2`, or `ap-south-1`

## Getting Started

### 1. Bootstrap CDK (one-time)

```bash
npx cdk bootstrap aws://ACCOUNT_ID/REGION
```

### 2. Deploy Backend

```bash
cd cdk
pip install -r requirements.txt
npx cdk deploy --all --require-approval broadening
```

This deploys 5 stacks in order:
1. **MockApiStack** — Mock external travel APIs
2. **DataStack** — DynamoDB tables + S3 bucket
3. **ComputeStack** — 10 Lambda functions + shared layer
4. **OrchestrationStack** — Step Functions state machine
5. **ApiStack** — API Gateway REST API

Copy the API URL from the output:
```
AiTravelConciergeApiStack.ApiEndpoint = https://xxxxxxxxxx.execute-api.REGION.amazonaws.com/prod/
```

### 3. Upload Holiday Calendar

```bash
# Get bucket name
aws cloudformation describe-stacks \
  --stack-name AiTravelConciergeDataStack \
  --query "Stacks[0].Outputs[?ExportName=='ArtifactStoreBucketName'].OutputValue" \
  --output text

# Upload
aws s3 cp backend/reference/indian_holiday_calendar.json \
  s3://BUCKET_NAME/reference/indian_holiday_calendar.json
```

### 4. Run Frontend

```bash
cd frontend
npm install
```

Create `.env.local`:
```env
NEXT_PUBLIC_API_URL=https://xxxxxxxxxx.execute-api.REGION.amazonaws.com/prod
```

```bash
npm run dev
```

Open **http://localhost:3000**.

## Usage

1. Describe your trip — destination, dates, budget (INR), and optional preferences
2. Click **Generate Itinerary** — you'll be redirected to a live workflow view
3. Watch the 4 AI agents work in parallel (status updates every 3-5 seconds)
4. View your day-by-day itinerary with activities, weather, costs, and local experiences

## Useful Commands

| Command | Description |
|---------|-------------|
| `npx cdk synth --all` | Generate CloudFormation templates |
| `npx cdk deploy --all` | Deploy all stacks |
| `npx cdk diff` | Preview changes before deploy |
| `npx cdk destroy --all` | Tear down all resources |
| `npm run dev` | Start frontend dev server |

## Cleanup

```bash
cd cdk
npx cdk destroy --all
```

## Cost Estimate

For light usage (a few trips/day):

| Service | Estimated Cost |
|---------|---------------|
| Lambda | Free tier (~1M requests/month) |
| DynamoDB | Free tier (25 RCU/WCU) |
| Step Functions | ~$0.025 per 1K state transitions |
| Bedrock (Nova Pro) | ~$0.0008/1K input tokens, ~$0.0032/1K output tokens |
| API Gateway | ~$3.50 per 1M requests |
| S3 | Negligible |

**Total for development/demo: < $5/month**

## License

This project is provided as-is for educational and demonstration purposes.
