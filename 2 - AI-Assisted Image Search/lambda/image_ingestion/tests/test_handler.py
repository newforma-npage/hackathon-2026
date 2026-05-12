"""
Unit tests for the image ingestion Lambda handler.

Uses moto to mock DynamoDB — no real AWS calls are made.
"""

import os
import pytest
import boto3
from moto import mock_aws
from unittest.mock import patch

# Set env var before importing the handler so it resolves at module load time
TABLE_NAME = "test-photo-metadata"
os.environ["PHOTO_TABLE_NAME"] = TABLE_NAME


@pytest.fixture(autouse=True)
def aws_credentials():
    """Ensure boto3 never hits real AWS during tests."""
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
    os.environ.setdefault("AWS_SESSION_TOKEN", "testing")


@pytest.fixture()
def ddb_table():
    """Create a mocked DynamoDB table and patch the handler's module-level table."""
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        resource.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "project_id", "KeyType": "HASH"},
                {"AttributeName": "image_path", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "project_id", "AttributeType": "S"},
                {"AttributeName": "image_path", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        import handler as h
        # Patch the module-level `table` to point at the mocked table
        h.table = resource.Table(TABLE_NAME)

        yield resource.Table(TABLE_NAME), h


def _make_event(bucket: str, key: str, event_time: str = "2024-04-15T08:30:00Z") -> dict:
    return {
        "Records": [
            {
                "eventTime": event_time,
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": key},
                },
            }
        ]
    }


# ── Happy-path tests ──────────────────────────────────────────────────────────

class TestParseProjectId:
    def test_standard_key(self):
        from handler import _parse_project_id
        assert _parse_project_id("PROJ-001/site-photo-01.jpg") == "PROJ-001"

    def test_nested_key(self):
        from handler import _parse_project_id
        assert _parse_project_id("PROJ-002/subdir/photo.jpg") == "PROJ-002"

    def test_flat_key_raises(self):
        from handler import _parse_project_id
        with pytest.raises(ValueError):
            _parse_project_id("site-photo-01.jpg")

    def test_empty_prefix_raises(self):
        from handler import _parse_project_id
        with pytest.raises(ValueError):
            _parse_project_id("/site-photo-01.jpg")


class TestBuildRecord:
    def test_fields_populated(self):
        from handler import _build_record
        rec = _build_record("my-bucket", "PROJ-001/photo.jpg", "2024-04-15T08:30:00Z")
        assert rec["project_id"] == "PROJ-001"
        assert rec["image_path"] == "PROJ-001/photo.jpg"
        assert rec["bucket_name"] == "my-bucket"
        assert rec["filename"] == "photo.jpg"
        assert rec["timestamp"] == "2024-04-15T08:30:00Z"
        assert rec["ai_indexed"] is False

    def test_ai_indexed_defaults_false(self):
        from handler import _build_record
        rec = _build_record("b", "PROJ-003/img.png", "2024-01-01T00:00:00Z")
        assert rec["ai_indexed"] is False


class TestLambdaHandler:
    def test_single_record_written_to_dynamo(self, ddb_table):
        table, h = ddb_table
        event = _make_event("npc-images", "PROJ-001/site-photo-01.jpg")
        result = h.lambda_handler(event, {})

        assert result["processed"] == 1
        assert result["skipped_or_failed"] == 0

        item = table.get_item(
            Key={"project_id": "PROJ-001", "image_path": "PROJ-001/site-photo-01.jpg"}
        )["Item"]
        assert item["filename"] == "site-photo-01.jpg"
        assert item["bucket_name"] == "npc-images"
        assert item["ai_indexed"] is False

    def test_url_encoded_key_decoded(self, ddb_table):
        table, h = ddb_table
        # S3 encodes spaces and special chars in keys
        event = _make_event("npc-images", "PROJ-002/site+photo+02.jpg")
        result = h.lambda_handler(event, {})
        assert result["processed"] == 1

        item = table.get_item(
            Key={"project_id": "PROJ-002", "image_path": "PROJ-002/site photo 02.jpg"}
        )["Item"]
        assert item["filename"] == "site photo 02.jpg"

    def test_flat_key_skipped(self, ddb_table):
        _, h = ddb_table
        event = _make_event("npc-images", "orphan-photo.jpg")
        result = h.lambda_handler(event, {})
        assert result["processed"] == 0
        assert result["skipped_or_failed"] == 1

    def test_multiple_records_batch(self, ddb_table):
        table, h = ddb_table
        event = {
            "Records": [
                {"eventTime": "2024-04-15T08:30:00Z", "s3": {"bucket": {"name": "b"}, "object": {"key": "PROJ-001/a.jpg"}}},
                {"eventTime": "2024-04-15T08:31:00Z", "s3": {"bucket": {"name": "b"}, "object": {"key": "PROJ-002/b.jpg"}}},
                {"eventTime": "2024-04-15T08:32:00Z", "s3": {"bucket": {"name": "b"}, "object": {"key": "bad-key.jpg"}}},
            ]
        }
        result = h.lambda_handler(event, {})
        assert result["processed"] == 2
        assert result["skipped_or_failed"] == 1

    def test_upsert_idempotent(self, ddb_table):
        """Calling handler twice for the same key should not raise and should
        leave exactly one record in DynamoDB."""
        table, h = ddb_table
        event = _make_event("npc-images", "PROJ-001/site-photo-01.jpg")
        h.lambda_handler(event, {})
        h.lambda_handler(event, {})  # second call — should be a no-op upsert

        response = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("project_id").eq("PROJ-001")
        )
        assert len(response["Items"]) == 1
