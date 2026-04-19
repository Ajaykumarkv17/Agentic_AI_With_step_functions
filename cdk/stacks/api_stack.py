"""ApiStack — API Gateway REST API for the AI Travel Concierge.

Defines a REST API with three endpoints:
- POST /trips — submit a new trip request
- GET /trips/{id} — retrieve a completed itinerary
- GET /trips/{id}/status — get real-time workflow status

Includes request validation for POST /trips and CORS configuration
for the Next.js frontend.
"""

from aws_cdk import (
    CfnOutput,
    Stack,
    aws_apigateway as apigw,
    aws_lambda as _lambda,
)
from constructs import Construct


class ApiStackProps:
    """Props for ApiStack accepting Lambda function references from ComputeStack."""

    def __init__(
        self,
        trip_submission_fn: _lambda.IFunction,
        trip_retrieval_fn: _lambda.IFunction,
        status_fn: _lambda.IFunction,
    ) -> None:
        self.trip_submission_fn = trip_submission_fn
        self.trip_retrieval_fn = trip_retrieval_fn
        self.status_fn = status_fn


class ApiStack(Stack):
    """Stack for API Gateway REST API, request validators, and CORS configuration."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        api_props: ApiStackProps | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if api_props is None:
            return

        self._props = api_props

        # -----------------------------------------------------------------
        # REST API
        # -----------------------------------------------------------------
        self.api = apigw.RestApi(
            self,
            "TravelConciergeApi",
            rest_api_name="AI Travel Concierge API",
            description="REST API for trip submission, retrieval, and status",
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=["Content-Type", "Authorization"],
            ),
        )

        # -----------------------------------------------------------------
        # Request validator for POST /trips
        # -----------------------------------------------------------------
        body_validator = apigw.RequestValidator(
            self,
            "TripRequestBodyValidator",
            rest_api=self.api,
            request_validator_name="trip-request-body-validator",
            validate_request_body=True,
            validate_request_parameters=False,
        )

        # Request model for POST /trips validation
        trip_request_model = self.api.add_model(
            "TripRequestModel",
            content_type="application/json",
            model_name="TripRequestModel",
            schema=apigw.JsonSchema(
                type=apigw.JsonSchemaType.OBJECT,
                required=["query", "dates", "budget"],
                properties={
                    "query": apigw.JsonSchema(
                        type=apigw.JsonSchemaType.STRING,
                        min_length=1,
                        max_length=2000,
                    ),
                    "dates": apigw.JsonSchema(
                        type=apigw.JsonSchemaType.OBJECT,
                        required=["start", "end"],
                        properties={
                            "start": apigw.JsonSchema(type=apigw.JsonSchemaType.STRING),
                            "end": apigw.JsonSchema(type=apigw.JsonSchemaType.STRING),
                        },
                    ),
                    "budget": apigw.JsonSchema(
                        type=apigw.JsonSchemaType.NUMBER,
                        minimum=0,
                        exclusive_minimum=True,
                    ),
                    "preferences": apigw.JsonSchema(
                        type=apigw.JsonSchemaType.ARRAY,
                        items=apigw.JsonSchema(type=apigw.JsonSchemaType.STRING),
                    ),
                },
            ),
        )

        # -----------------------------------------------------------------
        # Resources and methods
        # -----------------------------------------------------------------
        trips_resource = self.api.root.add_resource("trips")

        # POST /trips
        trips_resource.add_method(
            "POST",
            apigw.LambdaIntegration(self._props.trip_submission_fn),
            request_models={"application/json": trip_request_model},
            request_validator=body_validator,
        )

        # /trips/{id}
        trip_by_id = trips_resource.add_resource("{id}")

        # GET /trips/{id}
        trip_by_id.add_method(
            "GET",
            apigw.LambdaIntegration(self._props.trip_retrieval_fn),
        )

        # /trips/{id}/status
        status_resource = trip_by_id.add_resource("status")

        # GET /trips/{id}/status
        status_resource.add_method(
            "GET",
            apigw.LambdaIntegration(self._props.status_fn),
        )

        # -----------------------------------------------------------------
        # Outputs
        # -----------------------------------------------------------------
        CfnOutput(
            self,
            "ApiEndpoint",
            value=self.api.url,
            description="API Gateway endpoint URL",
            export_name="TravelConciergeApiEndpoint",
        )
