"""ComputeStack — Lambda functions for the AI Travel Concierge.

Defines all Lambda functions (4 agents, merge, fallback, trip submission,
trip retrieval, status, status_update). Shared modules (circuit_breaker,
bedrock_client, api_client, cache) are included in the main code bundle
under backend/shared/.

Each function receives least-privilege IAM grants scoped to the specific
DynamoDB tables, S3 bucket, Bedrock models, and Step Functions resources
it requires.
"""

from aws_cdk import (
    Duration,
    Stack,
    ArnFormat,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_s3 as s3,
)
from constructs import Construct

# Exclude everything except the backend/ directory from the Lambda code asset.
_ASSET_EXCLUDES = [
    "cdk",
    "frontend",
    ".git",
    "**/__pycache__",
    ".pytest_cache",
    ".kiro",
    "*.png",
    "*.md",
]


class ComputeStackProps:
    """Props for ComputeStack accepting DataStack resource references."""

    def __init__(
        self,
        itinerary_table: dynamodb.ITable,
        circuit_breaker_table: dynamodb.ITable,
        artifact_bucket: s3.IBucket,
        mock_api_url: str = "",
    ) -> None:
        self.itinerary_table = itinerary_table
        self.circuit_breaker_table = circuit_breaker_table
        self.artifact_bucket = artifact_bucket
        self.mock_api_url = mock_api_url


class ComputeStack(Stack):
    """Stack for Lambda functions (agents, merge, trip submission, retrieval, status) and layers."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        compute_props: ComputeStackProps | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if compute_props is None:
            return

        self._props = compute_props
        self._backend_code = _lambda.Code.from_asset("..", exclude=_ASSET_EXCLUDES)

        # Common environment variables used by most functions
        common_env = {
            "ITINERARY_TABLE_NAME": self._props.itinerary_table.table_name,
            "CIRCUIT_BREAKER_TABLE_NAME": self._props.circuit_breaker_table.table_name,
            "ARTIFACT_BUCKET_NAME": self._props.artifact_bucket.bucket_name,
            "MOCK_API_URL": self._props.mock_api_url,
        }

        # -----------------------------------------------------------------
        # Agent Lambda functions (60s timeout each)
        # -----------------------------------------------------------------
        self.destination_researcher_fn = self._create_agent_function(
            "DestinationResearcherFunction",
            handler="backend.lambdas.destination_researcher.handler.handler",
            description="Destination Researcher agent",
            timeout=Duration.seconds(60),
            environment=common_env,
        )

        self.budget_optimizer_fn = self._create_agent_function(
            "BudgetOptimizerFunction",
            handler="backend.lambdas.budget_optimizer.handler.handler",
            description="Budget Optimizer agent",
            timeout=Duration.seconds(60),
            environment=common_env,
        )

        self.weather_analyzer_fn = self._create_agent_function(
            "WeatherAnalyzerFunction",
            handler="backend.lambdas.weather_analyzer.handler.handler",
            description="Weather Analyzer agent",
            timeout=Duration.seconds(60),
            environment=common_env,
        )

        self.experience_curator_fn = self._create_agent_function(
            "ExperienceCuratorFunction",
            handler="backend.lambdas.experience_curator.handler.handler",
            description="Experience Curator agent",
            timeout=Duration.seconds(60),
            environment=common_env,
        )

        # -----------------------------------------------------------------
        # Merge Lambda (90s timeout)
        # -----------------------------------------------------------------
        self.merge_fn = self._create_agent_function(
            "MergeResultsFunction",
            handler="backend.lambdas.merge.handler.handler",
            description="Merge agent outputs into a cohesive day-by-day itinerary",
            timeout=Duration.seconds(90),
            environment=common_env,
        )

        # -----------------------------------------------------------------
        # Fallback Lambda (30s timeout)
        # -----------------------------------------------------------------
        self.fallback_fn = self._create_agent_function(
            "FallbackHandlerFunction",
            handler="backend.lambdas.fallback.handler.handler",
            description="Fallback handler — serves cached data or best-effort output",
            timeout=Duration.seconds(30),
            environment=common_env,
        )

        # -----------------------------------------------------------------
        # Trip Submission Lambda (10s timeout)
        # -----------------------------------------------------------------
        self.trip_submission_fn = _lambda.Function(
            self,
            "TripSubmissionFunction",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="backend.lambdas.trip_submission.handler.handler",
            code=self._backend_code,
            description="POST /trips — validates trip request, starts Step Functions workflow",
            timeout=Duration.seconds(10),
            memory_size=256,
            environment={
                "ITINERARY_TABLE_NAME": self._props.itinerary_table.table_name,
            },
        )

        # -----------------------------------------------------------------
        # Trip Retrieval Lambda (10s timeout)
        # -----------------------------------------------------------------
        self.trip_retrieval_fn = _lambda.Function(
            self,
            "TripRetrievalFunction",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="backend.lambdas.trip_retrieval.handler.handler",
            code=self._backend_code,
            description="GET /trips/{id} — retrieves full itinerary by ID",
            timeout=Duration.seconds(10),
            memory_size=256,
            environment={
                "ITINERARY_TABLE_NAME": self._props.itinerary_table.table_name,
                "ARTIFACT_BUCKET_NAME": self._props.artifact_bucket.bucket_name,
            },
        )

        # -----------------------------------------------------------------
        # Status Lambda (10s timeout)
        # -----------------------------------------------------------------
        self.status_fn = _lambda.Function(
            self,
            "WorkflowStatusFunction",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="backend.lambdas.status.handler.handler",
            code=self._backend_code,
            description="GET /trips/{id}/status — retrieves workflow status",
            timeout=Duration.seconds(10),
            memory_size=256,
            environment={
                "ITINERARY_TABLE_NAME": self._props.itinerary_table.table_name,
            },
        )

        # -----------------------------------------------------------------
        # Status Update Lambda (used by Step Functions)
        # -----------------------------------------------------------------
        self.status_update_fn = _lambda.Function(
            self,
            "StatusUpdateFunction",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="backend.lambdas.status_update.handler.handler",
            code=self._backend_code,
            description="Updates workflow status in DynamoDB during Step Functions execution",
            timeout=Duration.seconds(10),
            memory_size=256,
            environment={
                "ITINERARY_TABLE_NAME": self._props.itinerary_table.table_name,
            },
        )

        # -----------------------------------------------------------------
        # IAM — Least-privilege grants
        # -----------------------------------------------------------------
        self._grant_permissions()

    def _create_agent_function(
        self,
        construct_id: str,
        handler: str,
        description: str,
        timeout: Duration,
        environment: dict,
    ) -> _lambda.Function:
        """Create a Lambda function with 512 MB memory."""
        return _lambda.Function(
            self,
            construct_id,
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler=handler,
            code=self._backend_code,
            description=description,
            timeout=timeout,
            memory_size=512,
            environment=environment,
        )

    def _grant_permissions(self) -> None:
        """Apply least-privilege IAM grants to each Lambda function."""
        itinerary_table = self._props.itinerary_table
        cb_table = self._props.circuit_breaker_table
        bucket = self._props.artifact_bucket

        bedrock_policy = iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=["*"],
            effect=iam.Effect.ALLOW,
        )

        # Agent functions: DynamoDB (both tables), S3, Bedrock
        for fn in [
            self.destination_researcher_fn,
            self.budget_optimizer_fn,
            self.weather_analyzer_fn,
            self.experience_curator_fn,
        ]:
            itinerary_table.grant_read_write_data(fn)
            cb_table.grant_read_write_data(fn)
            bucket.grant_read_write(fn)
            fn.add_to_role_policy(bedrock_policy)

        # Merge: DynamoDB (both tables), S3, Bedrock
        itinerary_table.grant_read_write_data(self.merge_fn)
        cb_table.grant_read_write_data(self.merge_fn)
        bucket.grant_read_write(self.merge_fn)
        self.merge_fn.add_to_role_policy(bedrock_policy)

        # Fallback: DynamoDB (itinerary), S3 read, Bedrock
        itinerary_table.grant_read_write_data(self.fallback_fn)
        cb_table.grant_read_data(self.fallback_fn)
        bucket.grant_read(self.fallback_fn)
        self.fallback_fn.add_to_role_policy(bedrock_policy)

        # Trip Submission: DynamoDB write (itinerary), Step Functions start, SSM read
        itinerary_table.grant_read_write_data(self.trip_submission_fn)
        self.trip_submission_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["states:StartExecution"],
                resources=[
                    Stack.of(self).format_arn(
                        service="states",
                        resource="stateMachine",
                        resource_name="*",
                        arn_format=ArnFormat.COLON_RESOURCE_NAME,
                    )
                ],
            )
        )
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

        # Trip Retrieval: DynamoDB read (itinerary), S3 read
        itinerary_table.grant_read_data(self.trip_retrieval_fn)
        bucket.grant_read(self.trip_retrieval_fn)

        # Status: DynamoDB read (itinerary)
        itinerary_table.grant_read_data(self.status_fn)

        # Status Update: DynamoDB write (itinerary)
        itinerary_table.grant_read_write_data(self.status_update_fn)
