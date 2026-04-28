# 13 — FastAPI Endpoints

**Status:** [x] done

## Description

Expose the core analysis functions as a REST API so a frontend can be built later. Single-user; no authentication.

## Acceptance Criteria

- `uvicorn utgiftsanalys.app:app --reload` starts the server.
- `POST /import` accepts a multipart CSV file upload and returns inserted/skipped counts.
- `GET /analyze` returns recurring patterns and one-offs as JSON.
- `GET /predict` returns predicted amounts for a given month as JSON.
- `GET /stats` returns per-year stats as JSON.
- `GET /accounts` returns list of account numbers.
- All endpoints accept optional `?account=` query parameter.
- `/analyze` and `/predict` accept optional `?month=YYYY-MM`.
- Errors return JSON `{"detail": "..."}` with appropriate HTTP status codes.

## Endpoints

### `POST /import`
- Body: `multipart/form-data` with field `file` (CSV).
- Saves the uploaded file to a temp path, runs `import_file`, returns:
  ```json
  {"inserted": 12, "skipped": 3, "warnings": ["Warning: month 2026-02 missing..."]}
  ```

### `GET /analyze?month=YYYY-MM&account=ACCOUNT`
- Returns:
  ```json
  {
    "recurring": [
      {"description": "Spotify", "cadence": "monthly", "amount_type": "fixed",
       "fixed_amount": 119.0, "start_date": "2024-06-01", "status": "active"}
    ],
    "one_offs": [
      {"description": "ICA Maxi", "booking_date": "2026-04-05", "amount": -543.20}
    ]
  }
  ```

### `GET /predict?month=YYYY-MM&account=ACCOUNT`
- Returns:
  ```json
  {
    "month": "2026-05",
    "lines": [
      {"description": "Lf Uppsala", "cadence": "monthly", "predicted_amount": 195.0,
       "amount_type": "fixed", "range": null}
    ],
    "total": 314.0
  }
  ```

### `GET /stats?account=ACCOUNT`
- Returns list of year-stat objects (see spec 09 for fields).

### `GET /accounts`
- Returns:
  ```json
  [{"account": "123456789", "transaction_count": 248}]
  ```

## Implementation Notes

- New file `utgiftsanalys/app.py`.
- DB path from environment variable `UTGIFTSANALYS_DB` (default: `./data/utgiftsanalys.db`).
- FastAPI dependency `get_conn()` yields a connection and closes it on teardown.
- Reuse existing business logic functions directly (`build_patterns`, `predict_month`, etc.).
- Add to optional dependencies: `fastapi[standard]>=0.111` (includes uvicorn).
  ```toml
  [project.optional-dependencies]
  api = ["fastapi[standard]>=0.111"]
  dev = ["pytest>=8.0", "pytest-cov>=5.0", "httpx>=0.27"]
  ```
- Uploaded files are handled with `UploadFile`; write to `tempfile.NamedTemporaryFile` before passing to `import_file`.
- Warnings from hole detection should be captured and returned in the import response.
