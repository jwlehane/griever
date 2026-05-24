#!/bin/bash
# provision_db.sh
# Provisions a Google Cloud SQL PostgreSQL instance and creates the database.

ENV=${1:-staging}

PROJECT_ID="double-zenith-89117"
REGION="us-east1"
INSTANCE_NAME="tax-grieve-db"
DB_USER="griever_app"
DB_PASS="SUPER_SECURE_PASSWORD_CHANGE_ME"

if [ "$ENV" = "prod" ] || [ "$ENV" = "production" ]; then
    DB_NAME="grievance_data_prod"
    SERVICE="nygriever"
else
    DB_NAME="grievance_data_staging"
    SERVICE="nygriever-staging"
fi

echo "Setting project to $PROJECT_ID..."
gcloud config set project $PROJECT_ID

if gcloud sql instances describe $INSTANCE_NAME --project=$PROJECT_ID >/dev/null 2>&1; then
    echo "Instance $INSTANCE_NAME already exists, skipping creation."
else
    echo "Creating Cloud SQL instance $INSTANCE_NAME (db-f1-micro, Postgres 15) in $REGION..."
    gcloud sql instances create $INSTANCE_NAME \
        --database-version=POSTGRES_15 \
        --tier=db-f1-micro \
        --region=$REGION \
        --project=$PROJECT_ID
fi

if gcloud sql databases describe $DB_NAME --instance=$INSTANCE_NAME --project=$PROJECT_ID >/dev/null 2>&1; then
    echo "Database $DB_NAME already exists, skipping creation."
else
    echo "Creating database $DB_NAME..."
    gcloud sql databases create $DB_NAME --instance=$INSTANCE_NAME --project=$PROJECT_ID
fi

if gcloud sql users describe $DB_USER --instance=$INSTANCE_NAME --project=$PROJECT_ID >/dev/null 2>&1; then
    echo "User $DB_USER already exists, skipping creation."
else
    echo "Creating user $DB_USER..."
    gcloud sql users create $DB_USER --instance=$INSTANCE_NAME --password=$DB_PASS --project=$PROJECT_ID
fi

echo "Updating Cloud Run service $SERVICE to attach Cloud SQL..."
gcloud run services update "$SERVICE" \
    --add-cloudsql-instances=$PROJECT_ID:$REGION:$INSTANCE_NAME \
    --set-env-vars="DATABASE_URL=postgresql://$DB_USER:$DB_PASS@/$DB_NAME?host=/cloudsql/$PROJECT_ID:$REGION:$INSTANCE_NAME" \
    --region=$REGION \
    --project=$PROJECT_ID

echo "Done! The Cloud Run app $SERVICE is now connected to database $DB_NAME on Cloud SQL."
