# Cloud Run deployment — Radar Público

## Prerequisites
Use the existing Google Cloud **project ID**, not the Cloud Run service name, as GCP_PROJECT_ID. The earlier DODF service is unrelated and must not be modified.

The webhook is public but checks Telegram's secret header. Never send tokens in GitHub variables or commit them to source.

## 1. Enable services
```bash
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com iamcredentials.googleapis.com sts.googleapis.com
```

## 2. Secrets
Create three Secret Manager secrets in the chosen project:
- radar-telegram-token: newly rotated Telegram bot token
- radar-webhook-secret: long random string of letters, digits, underscore or hyphen
- radar-allowed-user-ids: comma-separated numeric Telegram IDs allowed to issue commands

Do not put the secret values in the repository. Grant the **Cloud Run runtime service account** the `roles/secretmanager.secretAccessor` role on these three secrets only.

## 3. GitHub OIDC
Create a dedicated GitHub deployment service account, a Workload Identity Pool and OIDC provider restricted to `assertion.repository == 'bravedragon-gif/radar-publico-bot'`. Grant the GitHub principal `roles/iam.workloadIdentityUser` on the deployment service account. The deployment account needs `roles/run.admin`, `roles/cloudbuild.builds.editor`, `roles/artifactregistry.writer`, `roles/serviceusage.serviceUsageConsumer`, and `roles/iam.serviceAccountUser` on the runtime service account. Depending on organization settings, Cloud Build's service account may require additional permissions.

Set GitHub Actions **Variables**:
- GCP_PROJECT_ID (actual Google Cloud project ID)
- GCP_WORKLOAD_IDENTITY_PROVIDER (projects/NUMBER/locations/global/workloadIdentityPools/POOL/providers/PROVIDER)
- GCP_DEPLOY_SERVICE_ACCOUNT (deployment service account email)
- GCP_RUNTIME_SERVICE_ACCOUNT (runtime service account email)

## 4. Deploy
Run workflow `Deploy Cloud Run` manually. Confirm `/health` returns `{\"status\":\"ok\"}`.

## 5. Register webhook
After deployment, register the Cloud Run HTTPS URL plus `/telegram/webhook` with Telegram `setWebhook`, including the **same secret** stored in Secret Manager as `secret_token`. This must be done securely without printing the token in terminal history/logs. Test `/start` and `/pncp viaturas` in a private chat with the bot using an allowlisted Telegram user ID.

## Limitations
The PNCP query is a small sample and must not be represented as exhaustive; briefing publication remains disabled pending official-source verification. GitHub Actions workflow dispatch is manual for deployment.
