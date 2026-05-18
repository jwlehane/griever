#!/bin/bash
# provision_db.sh
# Provisions a Google Cloud SQL PostgreSQL instance and creates the database.

PROJECT_ID="double-zenith-89117"
REGION="us-east5"
INSTANCE_NAME="tax-grieve-db"
DB_NAME="grievance_data"
DB_USER="griever_app"
DB_PASS="SUPER_SECURE_PASSWORD_CHANGE_ME"

echo "Setting project..."
gcloud config set project $PROJECT_ID

echo "Creating Cloud SQL instance (this takes several minutes)..."
gcloud sql instances create $INSTANCE_NAME \
    --database-version=POSTGRES_15 \
    --cpu=1 \
    --memory=3840MB \
    --region=$REGION \
    --project=$PROJECT_ID

echo "Creating database..."
gcloud sql databases create $DB_NAME --instance=$INSTANCE_NAME

echo "Creating user..."
gcloud sql users create $DB_USER --instance=$INSTANCE_NAME --password=$DB_PASS

echo "Updating Cloud Run service to attach Cloud SQL..."
gcloud run services update tax-grieve-app \
    --add-cloudsql-instances=$PROJECT_ID:$REGION:$INSTANCE_NAME \
    --set-env-vars="DATABASE_URL=postgresql://$DB_USER:$DB_PASS@/$DB_NAME?host=/cloudsql/$PROJECT_ID:$REGION:$INSTANCE_NAME" \
    --region=$REGION \
    --project=$PROJECT_ID

echo "Done! The Cloud Run app is now connected to Cloud SQL."
