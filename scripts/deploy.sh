#!/bin/bash

# GammaRips MCP Server - Cloud Run Deployment Script
#
# Deploys via Cloud Run SOURCE DEPLOY (`gcloud run deploy --source=.`), which is
# how this service is actually shipped (image lands in the cloud-run-source-deploy
# Artifact Registry repo). Matches the live config exactly and is safe to re-run.
#
# IMPORTANT — config that MUST match the live service (do not drift):
#   * Secrets are mounted from Secret Manager via --set-secrets (NOT plain env).
#     Setting these as plain env vars would clobber the secret mounts and break
#     Polygon + Google search.
#   * REQUIRE_API_KEY=false is the live auth posture. Do not flip to true here.
#   * BIGQUERY_DATASET / GCS_BUCKET_NAME / *_TABLE values are CODE DEFAULTS, not
#     env vars on the live service — intentionally not set here.

set -e  # Exit on error

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-profitscout-fida8}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="gammarips-mcp"

echo "========================================="
echo "GammaRips MCP Server Deployment"
echo "========================================="
echo "Project ID:   $PROJECT_ID"
echo "Region:       $REGION"
echo "Service Name: $SERVICE_NAME"
echo ""

# Deploy to Cloud Run from source. A new revision inherits prior config, but we
# pass the full secret/env/runtime spec explicitly so this also bootstraps a
# fresh service correctly and stays self-documenting.
echo "Building and deploying from source..."
gcloud run deploy "$SERVICE_NAME" \
    --source=. \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --platform=managed \
    --allow-unauthenticated \
    --port=8080 \
    --memory=1Gi \
    --cpu=1 \
    --concurrency=80 \
    --timeout=300 \
    --max-instances=10 \
    --set-env-vars="REQUIRE_API_KEY=false" \
    --set-secrets="POLYGON_API_KEY=POLYGON_API_KEY:latest,GOOGLE_API_KEY=GOOGLE_API_KEY:latest,GOOGLE_CSE_ID=GOOGLE_CSE_ID:latest"

echo ""
echo "========================================="
echo "Deployment complete!"
echo "========================================="
echo ""
echo "Service URL:"
gcloud run services describe "$SERVICE_NAME" --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)'
echo ""
echo "Live revision:"
gcloud run services describe "$SERVICE_NAME" --region="$REGION" --project="$PROJECT_ID" --format='value(status.latestReadyRevisionName)'
echo ""
