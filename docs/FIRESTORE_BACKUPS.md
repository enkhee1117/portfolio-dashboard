# Firestore Automated Backups

## Setup (one-time, via Google Cloud Console)

1. Go to: https://console.cloud.google.com/firestore/databases/-default-/export-import
2. Select your project: `portfolio-tracker-and-analyzer`
3. Click **"Set up scheduled exports"**
4. Choose:
   - **Frequency:** Daily
   - **Cloud Storage bucket:** Create one like `gs://portfolio-tracker-backups`
   - **Collections:** All (or specific: `trades`, `users`, `asset_prices`)
5. Save

This uses Firestore's built-in export feature. Costs ~$0.10/GB/month for storage.

## Manual backup

```bash
gcloud firestore export gs://portfolio-tracker-backups/manual-$(date +%Y%m%d)
```

## Restore from backup

```bash
gcloud firestore import gs://portfolio-tracker-backups/2026-04-01
```

## Why this matters

- Protects against accidental data deletion (bad restore, bugs)
- Protects against Firestore outages (rare but possible)
- Required for compliance if handling financial data
- Point-in-time recovery capability
