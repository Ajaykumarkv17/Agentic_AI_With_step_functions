"""MockApiStack — Lambda-backed API Gateway serving mock external API data.

Deploys a single Lambda function behind API Gateway with proxy integration
to serve realistic Indian travel data for all 8 external API endpoints.
"""

from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_apigateway as apigw,
    aws_lambda as _lambda,
)
from constructs import Construct

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


class MockApiStack(Stack):
    """Stack for mock external API (Lambda + API Gateway)."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.mock_fn = _lambda.Function(
            self,
            "MockApiFunction",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="backend.lambdas.mock_api.handler.handler",
            code=_lambda.Code.from_asset("..", exclude=_ASSET_EXCLUDES),
            description="Mock external API returning realistic Indian travel data",
            timeout=Duration.seconds(10),
            memory_size=128,
        )

        self.api = apigw.LambdaRestApi(
            self,
            "MockExternalApi",
            handler=self.mock_fn,
            rest_api_name="Travel Concierge Mock API",
            description="Mock external APIs for trains, flights, hotels, weather, tourism",
            proxy=True,
        )

        self.api_url = self.api.url

        CfnOutput(
            self,
            "MockApiEndpoint",
            value=self.api.url,
            description="Mock API Gateway endpoint URL",
            export_name="MockApiEndpoint",
        )
