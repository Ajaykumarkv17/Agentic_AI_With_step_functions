# AI Travel Concierge — Quickstart Guide

## Architecture Overview

```
Frontend (local)          Backend (AWS)
─────────────────         ──────────────────────────────────────
Next.js on :3000   ──►   API Gateway
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

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.12+ | `python --version` |
| Node.js | 18+ | `node --version` |
| AWS CLI | 2.x | `aws --version` |
| AWS CDK CLI | 2.150+ | `npx cdk --version` |
| AWS Account | — | `aws sts get-caller-identity` |

### Bedrock Model Access

You **must** enable access to these models in the AWS Console before deploying:

1. Go to **Amazon Bedrock** → **Model access** in your target region
2. Request access to:
   - `Amazon Nova Pro` (primary model)
   - `Amazon Nova Lite` (fallback model)
3. Wait for access to be granted (usually instant for Amazon models)

> Recommended regions: `us-east-1`, `us-west-2`, or `ap-south-1`

---

## Step 1 — Bootstrap CDK (one-time)

If you've never used CDK in this AWS account/region:

```bash
npx cdk bootstrap aws://ACCOUNT_ID/REGION
```

Replace `ACCOUNT_ID` and `REGION` with your values. Find them with:
```bash
aws sts get-caller-identity --query Account --output text
```

## Step 2 — Install CDK Dependencies

```bash
cd cdk
pip install -r requirements.txt
```

## Step 3 — Synthesize (verify before deploy)

```bash
npx cdk synth --all
```

This generates CloudFormation templates in `cdk/cdk.out/`. If it succeeds, you're ready to deploy.

## Step 4 — Deploy Backend to AWS

Deploy all 4 stacks in order:

```bash
npx cdk deploy --all --require-approval broadening
```

CDK will deploy in the correct order:
1. **AiTravelConciergeDataStack** — DynamoDB tables + S3 bucket
2. **AiTravelConciergeComputeStack** — 10 Lambda functions + shared layer
3. **AiTravelConciergeOrchestrationStack** — Step Functions state machine + SSM parameter
4. **AiTravelConciergeApiStack** — API Gateway REST API

> First deploy takes ~5 minutes. CDK will ask you to approve IAM changes — type `y`.

### Grab the API URL

After deploy, CDK prints outputs. Look for:

```
AiTravelConciergeApiStack.ApiEndpoint = https://xxxxxxxxxx.execute-api.REGION.amazonaws.com/prod/
```

Copy this URL — you'll need it for the frontend.

You can also retrieve it later:
```bash
aws cloudformation describe-stacks \
  --stack-name AiTravelConciergeApiStack \
  --query "Stacks[0].Outputs[?ExportName=='TravelConciergeApiEndpoint'].OutputValue" \
  --output text
```

## Step 5 — Upload Holiday Calendar to S3

Get the S3 bucket name:
```bash
aws cloudformation describe-stacks \
  --stack-name AiTravelConciergeDataStack \
  --query "Stacks[0].Outputs[?ExportName=='ArtifactStoreBucketName'].OutputValue" \
  --output text
```

Upload the calendar:
```bash
aws s3 cp backend/reference/indian_holiday_calendar.json \
  s3://BUCKET_NAME/reference/indian_holiday_calendar.json
```

## Step 6 — Configure & Run Frontend Locally

```bash
cd frontend
npm install
```

Update the API URL in `.env.local`:

```env
NEXT_PUBLIC_API_URL=https://xxxxxxxxxx.execute-api.REGION.amazonaws.com/prod
```

> Replace with the actual API Gateway URL from Step 4. **No trailing slash.**

Start the dev server:

```bash
npm run dev
```

Open **http://localhost:3000** in your browser.

---

## Using the Application

1. **Landing page** — Fill in your trip description, dates, budget (INR), and optional preferences
2. **Submit** — Click "Generate Itinerary" → redirects to `/trips/{id}`
3. **Workflow view** — Watch the 4 AI agents work in parallel (status updates every 4 seconds)
4. **Itinerary view** — Once complete, see your day-by-day itinerary with activities, weather, costs

---

## Useful Commands

| Command | Description |
|---------|-------------|
| `npx cdk synth --all` | Generate CloudFormation templates |
| `npx cdk deploy --all` | Deploy all stacks |
| `npx cdk diff` | Preview changes before deploy |
| `npx cdk destroy --all` | Tear down all resources |
| `npm run dev` | Start frontend dev server |
| `npm run build` | Build frontend for production |

## Monitoring & Debugging

- **Step Functions**: AWS Console → Step Functions → find execution by itinerary ID
- **Lambda logs**: AWS Console → CloudWatch → Log groups → `/aws/lambda/AiTravel*`
- **API Gateway**: AWS Console → API Gateway → AI Travel Concierge API → Dashboard
- **DynamoDB**: AWS Console → DynamoDB → Tables → look for `AiTravelConcierge*`

## Cleanup

To avoid ongoing charges, destroy all resources:

```bash
cd cdk
npx cdk destroy --all
```

Type `y` to confirm each stack deletion. The S3 bucket will auto-delete (configured with `auto_delete_objects=True`).

---

## Troubleshooting

### "AccessDeniedException" on Bedrock calls
→ Enable model access in the Bedrock console for your region. See Prerequisites above.

### "ResourceNotFoundException" for state machine
→ The SSM parameter `/travel-concierge/state-machine-arn` may not exist yet. Ensure the OrchestrationStack deployed successfully.

### CORS errors in browser
→ The API Gateway is configured with `allow_origins=ALL_ORIGINS`. If you still see CORS errors, check that your `.env.local` URL doesn't have a trailing slash.

### Lambda timeout errors
→ Agent Lambdas have 60s timeout. If Bedrock is slow, check CloudWatch logs. The circuit breaker will trip after 5 consecutive failures and route to fallback.

### CDK deploy fails with "Export not found"
→ Deploy stacks in order: `npx cdk deploy AiTravelConciergeDataStack AiTravelConciergeComputeStack AiTravelConciergeOrchestrationStack AiTravelConciergeApiStack`

## Cost Estimate

For light usage (a few trips/day), expect:
- **Lambda**: Free tier covers ~1M requests/month
- **DynamoDB**: Free tier covers 25 RCU/WCU
- **Step Functions**: ~$0.025 per 1000 state transitions
- **Bedrock**: ~$0.0008/1K input tokens, ~$0.0032/1K output tokens (Nova Pro)
- **API Gateway**: ~$3.50 per million requests
- **S3**: Negligible for this use case

> Total for development/demo: **< $5/month** with light usage.
