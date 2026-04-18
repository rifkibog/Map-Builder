# Building Viewer Indonesia

Web application untuk visualisasi 136 juta data building di Indonesia dengan H3 spatial indexing.

## Architecture

- **Frontend**: Next.js + Deck.gl + MapLibre GL (Cloud Run)
- **Backend**: FastAPI + BigQuery (Cloud Run)
- **Authentication**: Firebase (Google Sign-In with email whitelist)

## URL Production

- Frontend: https://building-viewer-frontend-1029375354934.asia-southeast1.run.app
- Backend API: https://building-viewer-api-1029375354934.asia-southeast1.run.app

## Deploy

See [building-viewer-docs/building-viewer-knowledge-base.md](./building-viewer-docs/building-viewer-knowledge-base.md) for full documentation.

### Backend

```bash
cd backend
gcloud run deploy building-viewer-api \
  --source . \
  --region asia-southeast1 \
  --allow-unauthenticated \
  --memory 2Gi --cpu 4 --timeout 300 --min-instances 1
```

### Frontend

```bash
cd frontend
gcloud run deploy building-viewer-frontend \
  --source . \
  --region asia-southeast1 \
  --allow-unauthenticated \
  --memory 2Gi --cpu 2 \
  --set-env-vars="API_KEY=<your-key>,BACKEND_URL=<backend-url>"
```

## GCP Project

- Project ID: `telkomsel-homepass`
- Region: `asia-southeast1`
