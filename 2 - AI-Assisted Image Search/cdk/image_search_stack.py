import json
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    CfnOutput,
    aws_iam,
    aws_opensearchserverless as aoss,
)
from constructs import Construct


class ImageSearchStack(Stack):
    """CDK stack that provisions an OpenSearch Serverless collection for vector search."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Resolve the principal ARN(s) for the data access policy.
        # The deploying account root is always included.
        account_root_arn = f"arn:aws:iam::{self.account}:root"
        principals = [account_root_arn]

        # Optionally accept an application role ARN via CDK context:
        #   cdk deploy --context app_role_arn=arn:aws:iam::123456789012:role/MyRole
        app_role_arn = self.node.try_get_context("app_role_arn")
        if app_role_arn:
            principals.append(app_role_arn)

        # ------------------------------------------------------------------
        # 1. Encryption security policy — AWS-owned KMS keys
        # ------------------------------------------------------------------
        encryption_policy_body = json.dumps([
            {
                "Rules": [
                    {
                        "ResourceType": "collection",
                        "Resource": ["collection/image-search"],
                    }
                ],
                "AWSOwnedKey": True,
            }
        ])

        encryption_policy = aoss.CfnSecurityPolicy(
            self,
            "EncryptionPolicy",
            name="image-search-enc",
            type="encryption",
            policy=encryption_policy_body,
        )

        # ------------------------------------------------------------------
        # 2. Network security policy — public access for API + Dashboards
        # ------------------------------------------------------------------
        network_policy_body = json.dumps([
            {
                "Rules": [
                    {
                        "ResourceType": "collection",
                        "Resource": ["collection/image-search"],
                    },
                    {
                        "ResourceType": "dashboard",
                        "Resource": ["collection/image-search"],
                    },
                ],
                "AllowFromPublic": True,
            }
        ])

        network_policy = aoss.CfnSecurityPolicy(
            self,
            "NetworkPolicy",
            name="image-search-net",
            type="network",
            policy=network_policy_body,
        )

        # ------------------------------------------------------------------
        # 3. OpenSearch Serverless collection (VECTORSEARCH)
        # ------------------------------------------------------------------
        collection = aoss.CfnCollection(
            self,
            "ImageSearchCollection",
            name="image-search",
            type="VECTORSEARCH",
        )

        # The collection depends on both security policies being in place first.
        collection.add_dependency(encryption_policy)
        collection.add_dependency(network_policy)

        # ------------------------------------------------------------------
        # 4. Data access policy — aoss:* on all indexes for the principals
        # ------------------------------------------------------------------
        data_access_policy_body = json.dumps([
            {
                "Rules": [
                    {
                        "ResourceType": "index",
                        "Resource": ["index/image-search/*"],
                        "Permission": ["aoss:*"],
                    },
                    {
                        "ResourceType": "collection",
                        "Resource": ["collection/image-search"],
                        "Permission": ["aoss:*"],
                    },
                ],
                "Principal": principals,
            }
        ])

        aoss.CfnAccessPolicy(
            self,
            "DataAccessPolicy",
            name="image-search-access",
            type="data",
            policy=data_access_policy_body,
        )

        # ------------------------------------------------------------------
        # 5. Stack output — collection HTTPS endpoint
        # ------------------------------------------------------------------
        CfnOutput(
            self,
            "CollectionEndpoint",
            value=collection.attr_collection_endpoint,
            description="OpenSearch Serverless collection HTTPS endpoint",
        )
