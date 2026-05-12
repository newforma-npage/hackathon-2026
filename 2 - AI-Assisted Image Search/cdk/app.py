#!/usr/bin/env python3
import aws_cdk as cdk
from image_search_stack import ImageSearchStack

app = cdk.App()

ImageSearchStack(
    app,
    "ImageSearchStack",
    env=cdk.Environment(region="us-east-1"),
)

app.synth()
