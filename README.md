# TaxGrieve NY: Automated Property Tax Grievance Pipeline

TaxGrieve is an automated pipeline for property owners in New York (starting with Dutchess County) to challenge their property tax assessments. It automates the retrieval of local market data (Comparable Sales), verifies characteristics against official County records, and generates a formal narrative for the RP-524 grievance form.

## 🚀 Features

- **Authoritative Search:** Direct integration with County ParcelAccess APIs to verify square footage, bedrooms, and assessment history.
- **Market Discovery:** Real-time discovery of recently sold comparable properties via RapidAPI/Zillow.
- **Intelligent Curation:** Multi-factor similarity scoring and automated outlier detection.
- **Human-in-the-Loop:** Web interface for manual comp curation and persistent rejection of unsuitable sales.
- **Renovation Support:** "Effective Age" calculations to adjust valuations based on recent property upgrades.
- **Robustness:** Built-in retry logic, persistent discovery (resumes where it left off), and automated admin error reporting.

---

## 🛠️ Local Installation

### 1. Prerequisites
- Python 3.11+
- [RapidAPI Account](https://rapidapi.com/) (for real-estate data)

### 2. Setup
Clone the repository and run the setup script:

```bash
git clone <your-repo-url>
cd tax_grieve
bash tax_grieve_setup.sh
```

### 3. Configuration
Create a `.env` file in the root directory:

```bash
RAPIDAPI_KEY=your_rapidapi_key_here
# Optional: SMTP for error reporting
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password

# Optional: PostgreSQL Database URL (falls back to SQLite if omitted)
DATABASE_URL=postgresql://user:password@host/database
```

### 4. Run the Application
```bash
./tax-grieve-env/bin/python src/main.py
```
Open your browser to `http://localhost:8080`.

---

## ☁️ Cloud Deployment (Google Cloud Run)

The project includes scripts to deploy to Google Cloud Run and set up a persistent database.

### 1. Prerequisites
- [Google Cloud SDK (gcloud)](https://cloud.google.com/sdk/docs/install) installed and authenticated.
- A GCP project with Billing enabled.

### 2. Deploy
Run the deployment script from your local machine to deploy to `us-east1` (defaults to staging):

```bash
./deploy_cloud.sh staging
# or for production:
./deploy_cloud.sh prod
```

The script reads `RAPIDAPI_KEY` from Google Secret Manager, using `nygriever-rapidapi-key` by default. If the secret does not exist yet, export `RAPIDAPI_KEY` once and the script will create it:

```bash
export RAPIDAPI_KEY=your_key_here
./deploy_cloud.sh staging
```

The Cloud Run runtime service account must be able to read the secret. A project Owner or Secret Manager Admin should grant access to the specific secret:

```bash
gcloud secrets add-iam-policy-binding nygriever-rapidapi-key \
  --project double-zenith-89117 \
  --member serviceAccount:529334528547-compute@developer.gserviceaccount.com \
  --role roles/secretmanager.secretAccessor
```

### 3. Persistent Database Setup (Cloud SQL)
Since Cloud Run is stateless, hook it up to a persistent PostgreSQL instance. Run the provisioning script to create/link the database for the environment:

```bash
./provision_db.sh staging
# or for production:
./provision_db.sh prod
```

**Note:** The scripts default to the `us-east1` region, project `double-zenith-89117`, and target `nygriever-staging` or `nygriever` depending on the environment parameter.

---

## 🔑 Obtaining API Keys

### RapidAPI (Real-Time Real Estate Data)
We use the **"Real-Time Real Estate Data"** API from RapidAPI.

1.  Visit [RapidAPI.com](https://rapidapi.com/apidojo/api/real-time-real-estate-data).
2.  Sign up for a free account.
3.  Subscribe to the "Basic" plan (usually free for a limited number of calls).
4.  Go to the **Endpoints** tab and copy your `X-RapidAPI-Key`.
5.  Paste this into your `.env` file as `RAPIDAPI_KEY`.

---

## 🏗️ Technical Architecture

### County Abstraction (Factory Pattern)
The system is designed to be multi-county. All county-specific logic is isolated in `src/app/counties/`.
- To add a new county (e.g., Ulster), implement the `CountyInterface` in a new file (e.g., `ulster.py`) and update the `CountyFactory`.

### Database
- **SQLite (Local):** Uses `grievance_data.db` for local normalized storage.
- **PostgreSQL (Cloud):** Activated automatically if `DATABASE_URL` is defined in the environment. Recommended for Cloud Run deployments.
- **Persistence:** Discovery results are written to the database immediately to allow for session resumption and "repairing" of incomplete data.

---

## 👥 Contributors
- **JW LeHane** (Lead Developer)
- **Gemini CLI** (AI Engineering Agent)
