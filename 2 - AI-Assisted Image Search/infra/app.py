#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.image_ingestion_stack import ImageIngestionStack

app = cdk.App()
ImageIngestionStack(app, "VisualProjectImageIngestion")
app.synth()
