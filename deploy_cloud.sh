#!/bin/bash
# deploy_cloud.sh

PROJECT_ID="double-zenith-89117"
REGION="us-east1"
ENV=${1:-staging}

if [ "$ENV" = "prod" ] || [ "$ENV" = "production" ]; then
    SERVICE="nygriever"
else
    SERVICE="nygriever-staging"
fi

RAPIDAPI_SECRET_NAME="nygriever-rapidapi-key"

echo "Cleaning up local locks..."
rm -f .git/index.lock

if ! gcloud secrets describe "$RAPIDAPI_SECRET_NAME" --project "$PROJECT_ID" >/dev/null 2>&1; then
    if [ -z "$RAPIDAPI_KEY" ]; then
        echo "Error: Secret $RAPIDAPI_SECRET_NAME does not exist and RAPIDAPI_KEY is not set."
        echo "Create the secret first, or run: export RAPIDAPI_KEY=your_key"
        exit 1
    fi
    printf "%s" "$RAPIDAPI_KEY" | gcloud secrets create "$RAPIDAPI_SECRET_NAME" \
        --project "$PROJECT_ID" \
        --replication-policy=automatic \
        --data-file=-
fi

echo "Deploying $SERVICE to Cloud Run ($ENV: $REGION) with Secret Manager..."

# The runtime service account must have roles/secretmanager.secretAccessor for
# this secret. Cloud Run keeps the key out of revision env literals.
gcloud run deploy "$SERVICE" \
    --source . \
    --project "$PROJECT_ID" \
    --region "$REGION" \
    --allow-unauthenticated \
    --timeout 600 \
    --remove-env-vars RAPIDAPI_KEY \
    --set-secrets "RAPIDAPI_KEY=$RAPIDAPI_SECRET_NAME:latest" \
    --quiet
