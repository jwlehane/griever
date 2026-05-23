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
```

### 4. Run the Application
```bash
./tax-grieve-env/bin/python src/main.py
```
Open your browser to `http://localhost:8080`.

---

## ☁️ Cloud Deployment (Google Cloud Run)

The project includes a `deploy_cloud.sh` script for rapid deployment to Google Cloud Run.

### 1. Prerequisites
- [Google Cloud SDK (gcloud)](https://cloud.google.com/sdk/docs/install) installed and authenticated.
- A GCP project with Billing enabled.

### 2. Deploy
Run the deployment script from your local machine:

```bash
./deploy_cloud.sh
```

The script reads `RAPIDAPI_KEY` from Google Secret Manager, using
`tax-grieve-app-rapidapi-key` by default. If the secret does not exist yet,
export `RAPIDAPI_KEY` once and the script will create it without storing the
key as a Cloud Run literal environment variable.

```bash
export RAPIDAPI_KEY=your_key_here
./deploy_cloud.sh
```

The Cloud Run runtime service account must be able to read the secret:

```bash
gcloud projects add-iam-policy-binding double-zenith-89117 \
  --member serviceAccount:529334528547-compute@developer.gserviceaccount.com \
  --role roles/secretmanager.secretAccessor
```

**Note:** The script defaults to the `us-east5` region and project `double-zenith-89117`. Override `PROJECT_ID`, `REGION`, `SERVICE`, or `RAPIDAPI_SECRET_NAME` to change these targets.

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
- **SQLite:** Uses `grievance_data.db` for normalized storage.
- **Persistence:** Discovery results are written to the database immediately to allow for session resumption and "repairing" of incomplete data.

---

## 👥 Contributors
- **JW LeHane** (Lead Developer)
- **Gemini CLI** (AI Engineering Agent)
