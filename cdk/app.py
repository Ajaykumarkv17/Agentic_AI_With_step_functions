#!/usr/bin/env python3
"""CDK app entry point for the AI Travel Concierge application."""

import aws_cdk as cdk
from aws_cdk import aws_ssm as ssm

from Agentic_AI_With_step_functions.cdk.stacks.data_stack import DataStack
from Agentic_AI_With_step_functions.cdk.stacks.compute_stack import ComputeStack, ComputeStackProps
from Agentic_AI_With_step_functions.cdk.stacks.orchestration_stack import OrchestrationStack, OrchestrationStackProps
from Agentic_AI_With_step_functions.cdk.stacks.api_stack import ApiStack, ApiStackProps
from Agentic_AI_With_step_functions.cdk.stacks.mock_api_stack import MockApiStack

app = cdk.App(outdir="cdk.out")

# Mock external API (deployed first — no dependencies)
mock_api_stack = MockApiStack(app, "AiTravelConciergeMockApiStack",
    description="Mock external APIs: trains, flights, hotels, weather, tourism",
)

data_stack = DataStack(app, "AiTravelConciergeDataStack",
    description="Data layer: DynamoDB tables and S3 artifact store",
)

compute_stack = ComputeStack(app, "AiTravelConciergeComputeStack",
    compute_props=ComputeStackProps(
        itinerary_table=data_stack.itinerary_table,
        circuit_breaker_table=data_stack.circuit_breaker_table,
        artifact_bucket=data_stack.artifact_bucket,
        mock_api_url=mock_api_stack.api_url,
    ),
    description="Compute layer: Lambda functions and shared layers",
)

orchestration_stack = OrchestrationStack(app, "AiTravelConciergeOrchestrationStack",
    orchestration_props=OrchestrationStackProps(
        destination_researcher_fn=compute_stack.destination_researcher_fn,
        budget_optimizer_fn=compute_stack.budget_optimizer_fn,
        weather_analyzer_fn=compute_stack.weather_analyzer_fn,
        experience_curator_fn=compute_stack.experience_curator_fn,
        merge_fn=compute_stack.merge_fn,
        fallback_fn=compute_stack.fallback_fn,
        status_update_fn=compute_stack.status_update_fn,
    ),
    description="Orchestration layer: Step Functions state machine",
)

# Store the state machine ARN in SSM so the trip submission Lambda can
# read it at runtime.  This avoids a circular cross-stack dependency
# (ComputeStack ↔ OrchestrationStack).
ssm.StringParameter(
    orchestration_stack,
    "StateMachineArnParam",
    parameter_name="/travel-concierge/state-machine-arn",
    string_value=orchestration_stack.state_machine.state_machine_arn,
    description="Step Functions state machine ARN for trip submission Lambda",
)

api_stack = ApiStack(app, "AiTravelConciergeApiStack",
    api_props=ApiStackProps(
        trip_submission_fn=compute_stack.trip_submission_fn,
        trip_retrieval_fn=compute_stack.trip_retrieval_fn,
        status_fn=compute_stack.status_fn,
    ),
    description="API layer: API Gateway REST API",
)

app.synth()
