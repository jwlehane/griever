#!/bin/bash
# deploy_cloud.sh

if [ -z "$RAPIDAPI_KEY" ]; then
    echo "Error: RAPIDAPI_KEY not found in environment."
    echo "Please run: export RAPIDAPI_KEY=your_key"
    exit 1
fi

echo "Cleaning up local locks..."
rm -f .git/index.lock

echo "Deploying to Cloud Run (us-east5) with extended timeout..."

# Using us-east5 as requested and adding --timeout to allow more time for the build/startup
gcloud run deploy tax-grieve-app --source . --project double-zenith-89117 --region us-east5 --allow-unauthenticated --timeout 600 --set-env-vars "RAPIDAPI_KEY=$RAPIDAPI_KEY"
