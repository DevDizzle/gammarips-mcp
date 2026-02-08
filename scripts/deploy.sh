#!/bin/bash

# GammaRips MCP Server - Cloud Run Deployment Script
# This script builds and deploys the MCP server to Google Cloud Run

set -e  # Exit on error

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-profitscout-lx6bb}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="gammarips-mcp"
REPOSITORY_NAME="gammarips-mcp"

echo "========================================="
echo "GammaRips MCP Server Deployment"
echo "========================================="
echo "Project ID: $PROJECT_ID"
echo "Region: $REGION"
echo "Service Name: $SERVICE_NAME"
echo ""

# Set the active project
echo "Setting active GCP project..."
gcloud config set project $PROJECT_ID

# Create Artifact Registry repository if it doesn't exist
echo "Checking Artifact Registry repository..."
if ! gcloud artifacts repositories describe $REPOSITORY_NAME --location=$REGION &>/dev/null; then
    echo "Creating Artifact Registry repository..."
    gcloud artifacts repositories create $REPOSITORY_NAME \
        --repository-format=docker \
        --location=$REGION \
        --description="GammaRips MCP Server container images"
else
    echo "Artifact Registry repository already exists."
fi

# Build the container image
echo ""
echo "Building container image..."
IMAGE_TAG="$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY_NAME/$SERVICE_NAME:latest"

gcloud builds submit \
    --region=$REGION \
    --tag $IMAGE_TAG

# Deploy to Cloud Run
echo ""
echo "Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
    --image $IMAGE_TAG \
    --region=$REGION \
    --platform=managed \
    --allow-unauthenticated \
    --port=8080 \
    --memory=1Gi \
    --cpu=1 \
    --timeout=300 \
    --max-instances=10 \
    --set-env-vars="GCP_PROJECT_ID=profitscout-fida8,GCP_REGION=$REGION,BIGQUERY_DATASET=profit_scout,GCS_BUCKET_NAME=profit-scout-data,GOOGLE_CSE_ID=${GOOGLE_CSE_ID},GOOGLE_API_KEY=${GOOGLE_API_KEY},REQUIRE_API_KEY=true,FIRESTORE_COLLECTION_USERS=users,WINNERS_DASHBOARD_TABLE=profitscout-lx6bb.profit_scout.winners_dashboard,OPTION_CHAINS_TABLE=profitscout-lx6bb.profit_scout.options_chain,PERFORMANCE_TRACKER_TABLE=profitscout-lx6bb.profit_scout.performance_tracker,CALENDAR_EVENTS_TABLE=profitscout-lx6bb.profit_scout.calendar_events"

echo ""
echo "========================================="
echo "Deployment complete!"
echo "========================================="
echo ""
echo "Service URL:"
gcloud run services describe $SERVICE_NAME --region=$REGION --format='value(status.url)'
echo ""
echo "To test the MCP server, use the Cloud Run proxy:"
echo "  gcloud run services proxy $SERVICE_NAME --region=$REGION"
echo ""
