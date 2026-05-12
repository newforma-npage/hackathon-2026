"""
CDK snapshot/assertion tests for ImageSearchStack.

Uses aws_cdk.assertions.Template to verify the synthesised CloudFormation
template contains the correct resources and outputs.

Task 7 — CDK Snapshot Tests
Acceptance criteria references: Requirements 1.1–1.5
"""

import sys
import os

# Add the cdk/ directory to the path so we can import ImageSearchStack
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cdk"))

import pytest
import aws_cdk as cdk
from aws_cdk.assertions import Template

from image_search_stack import ImageSearchStack


@pytest.fixture(scope="module")
def template() -> Template:
    """Synthesise ImageSearchStack and return an assertions Template."""
    app = cdk.App()
    stack = ImageSearchStack(
        app,
        "ImageSearchStack",
        env=cdk.Environment(account="123456789012", region="us-east-1"),
    )
    return Template.from_stack(stack)


# ---------------------------------------------------------------------------
# Test 1 — Collection resource
# ---------------------------------------------------------------------------

def test_collection_resource(template: Template) -> None:
    """
    Assert the template has exactly one AWS::OpenSearchServerless::Collection
    resource with Type=VECTORSEARCH and Name=image-search.

    Validates: Requirements 1.1
    """
    template.has_resource_properties(
        "AWS::OpenSearchServerless::Collection",
        {
            "Type": "VECTORSEARCH",
            "Name": "image-search",
        },
    )
    # Verify there is exactly one such resource
    template.resource_count_is("AWS::OpenSearchServerless::Collection", 1)


# ---------------------------------------------------------------------------
# Test 2 — Encryption policy
# ---------------------------------------------------------------------------

def test_encryption_policy(template: Template) -> None:
    """
    Assert the template has an AWS::OpenSearchServerless::SecurityPolicy
    resource with Type=encryption and Name=image-search-enc.

    Validates: Requirements 1.2
    """
    template.has_resource_properties(
        "AWS::OpenSearchServerless::SecurityPolicy",
        {
            "Type": "encryption",
            "Name": "image-search-enc",
        },
    )


# ---------------------------------------------------------------------------
# Test 3 — Network policy
# ---------------------------------------------------------------------------

def test_network_policy(template: Template) -> None:
    """
    Assert the template has an AWS::OpenSearchServerless::SecurityPolicy
    resource with Type=network and Name=image-search-net.

    Validates: Requirements 1.3
    """
    template.has_resource_properties(
        "AWS::OpenSearchServerless::SecurityPolicy",
        {
            "Type": "network",
            "Name": "image-search-net",
        },
    )


# ---------------------------------------------------------------------------
# Test 4 — Data access policy
# ---------------------------------------------------------------------------

def test_data_access_policy(template: Template) -> None:
    """
    Assert the template has an AWS::OpenSearchServerless::AccessPolicy
    resource with Type=data and Name=image-search-access.

    Validates: Requirements 1.4
    """
    template.has_resource_properties(
        "AWS::OpenSearchServerless::AccessPolicy",
        {
            "Type": "data",
            "Name": "image-search-access",
        },
    )


# ---------------------------------------------------------------------------
# Test 5 — CollectionEndpoint output
# ---------------------------------------------------------------------------

def test_collection_endpoint_output(template: Template) -> None:
    """
    Assert the template has a CloudFormation output named CollectionEndpoint.

    Validates: Requirements 1.5
    """
    template.has_output(
        "CollectionEndpoint",
        {},
    )
