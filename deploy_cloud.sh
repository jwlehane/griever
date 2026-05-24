#!/bin/bash
# deploy_cloud.sh

if [ -z "$RAPIDAPI_KEY" ]; then
    echo "Error: RAPIDAPI_KEY not found in environment."
    echo "Please run: export RAPIDAPI_KEY=your_key"
    exit 1
fi

echo "Cleaning up local locks..."
rm -f .git/index.lock

echo "Deploying to Cloud Run (us-east1) with extended timeout..."

# Using us-east1 and service name nygriever
gcloud run deploy nygriever --source . --project double-zenith-89117 --region us-east1 --allow-unauthenticated --timeout 600 --set-env-vars "RAPIDAPI_KEY=$RAPIDAPI_KEY"

