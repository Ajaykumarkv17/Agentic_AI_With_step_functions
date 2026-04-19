from aws_cdk import (
    CfnOutput,
    RemovalPolicy,
    Stack,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
)
from constructs import Construct


class DataStack(Stack):
    """Stack for DynamoDB tables (ItineraryStore, CircuitBreakerTable) and S3 ArtifactStore bucket."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ItineraryStore DynamoDB table
        # PK: itinerary_id, TTL on `ttl` attribute, PAY_PER_REQUEST billing
        self.itinerary_table = dynamodb.Table(
            self,
            "ItineraryStoreTable",
            partition_key=dynamodb.Attribute(
                name="itinerary_id",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # CircuitBreakerTable DynamoDB table
        # PK: service_name
        self.circuit_breaker_table = dynamodb.Table(
            self,
            "CircuitBreakerStateTable",
            partition_key=dynamodb.Attribute(
                name="service_name",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # S3 ArtifactStore bucket
        self.artifact_bucket = s3.Bucket(
            self,
            "ArtifactStoreBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Stack outputs for cross-stack references
        CfnOutput(
            self,
            "ItineraryStoreTableName",
            value=self.itinerary_table.table_name,
            description="Name of the ItineraryStore DynamoDB table",
            export_name="ItineraryStoreTableName",
        )

        CfnOutput(
            self,
            "CircuitBreakerTableName",
            value=self.circuit_breaker_table.table_name,
            description="Name of the CircuitBreaker DynamoDB table",
            export_name="CircuitBreakerTableName",
        )

        CfnOutput(
            self,
            "ArtifactStoreBucketName",
            value=self.artifact_bucket.bucket_name,
            description="Name of the S3 ArtifactStore bucket",
            export_name="ArtifactStoreBucketName",
        )
