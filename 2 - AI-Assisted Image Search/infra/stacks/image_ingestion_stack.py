from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_s3 as s3,
    aws_dynamodb as dynamodb,
    aws_lambda as lambda_,
    aws_s3_notifications as s3n,
    aws_iam as iam,
)
from constructs import Construct


class ImageIngestionStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── DynamoDB table ────────────────────────────────────────────────────
        # Partition key: project_id  |  Sort key: image_path
        # Allows efficient queries like "all images for PROJ-001"
        photo_table = dynamodb.Table(
            self,
            "PhotoMetadataTable",
            table_name="visual-project-photo-metadata",
            partition_key=dynamodb.Attribute(
                name="project_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="image_path", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,  # keep data on stack destroy
        )

        # ── S3 bucket ─────────────────────────────────────────────────────────
        # Expected key structure: {project_id}/{filename}
        # e.g.  PROJ-001/site-photo-01.jpg
        image_bucket = s3.Bucket(
            self,
            "ProjectImagesBucket",
            bucket_name=None,  # CDK generates a unique name; set explicitly if needed
            versioned=False,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # ── Lambda function ───────────────────────────────────────────────────
        ingest_fn = lambda_.Function(
            self,
            "ImageIngestionFunction",
            function_name="visual-project-image-ingest",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset("../lambda/image_ingestion"),
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                "PHOTO_TABLE_NAME": photo_table.table_name,
            },
        )

        # Grant Lambda read access to S3 and read/write to DynamoDB
        image_bucket.grant_read(ingest_fn)
        photo_table.grant_read_write_data(ingest_fn)

        # ── S3 → Lambda event notification ───────────────────────────────────
        # Trigger on any object created (PUT, POST, COPY, multipart complete)
        # Filter to common image types to avoid triggering on metadata files
        for suffix in [".jpg", ".jpeg", ".png", ".tif", ".tiff"]:
            image_bucket.add_event_notification(
                s3.EventType.OBJECT_CREATED,
                s3n.LambdaDestination(ingest_fn),
                s3.NotificationKeyFilter(suffix=suffix),
            )
