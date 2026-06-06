# Data Redundancy Removal System

Cloud Computing Task 1 project for identifying redundant data, validating new entries against existing data, and appending only unique verified records.

## Features

- Classifies new data as `unique`, `redundant`, `false_positive`, or `invalid`.
- Uses SHA-256 hashes to block exact duplicate records.
- Uses normalized text similarity to detect near duplicates.
- Stores only accepted records in SQLite.
- Maintains a validation audit log for accepted and rejected submissions.
- Provides a web interface and JSON API endpoints.
- Runs with Python standard library only, so no package installation is required.

## How It Works

1. The user submits a source name and data content.
2. The system normalizes the content by trimming spaces, lowercasing text, and removing repeated whitespace.
3. A SHA-256 fingerprint is generated to detect exact duplicates.
4. Existing records are compared with the new entry using similarity scoring.
5. The system classifies the entry:
   - `redundant`: exact or near duplicate, rejected.
   - `false_positive`: similar but acceptable, inserted.
   - `unique`: no strong match found, inserted.
   - `invalid`: missing or too-short data, rejected.
6. Accepted data is appended to the database and every validation attempt is logged.

## Run Locally

```bash
python app.py
```

Open:

```text
http://127.0.0.1:8000
```

## Run the Agent

JavaScript agent:

```bash
node agent.js inspect --source user_upload --content "Customer Arun bought cloud storage plan A on Friday."
```

```bash
node agent.js submit --source user_upload --content "Customer Arun bought cloud storage plan A on Friday."
```

```bash
node agent.js stats
```

The JavaScript agent stores its records in `agent-data.json`.

Python agent:

Preview a record without saving it:

```bash
python redundancy_agent.py inspect --source user_upload --content "Customer Arun bought cloud storage plan A on Friday."
```

Validate and store a record:

```bash
python redundancy_agent.py submit --source user_upload --content "Customer Arun bought cloud storage plan A on Friday."
```

Process a batch file and generate a JSON report:

```bash
python redundancy_agent.py batch --input sample_records.csv --report reports/agent_report.json
```

The batch input must include a `content` column. A `source` column is optional.

## API Endpoints

- `GET /api/records` returns verified stored records.
- `GET /api/logs` returns recent validation attempts.

## Project Structure

```text
.
├── agent.js
├── app.py
├── redundancy_agent.py
├── LICENSE
├── README.md
└── redundancy.db
```

The `redundancy.db` file is created automatically when the app starts.

## Test Cases

Use these sample entries from the web form:

```text
Source: user_upload
Content: Customer Arun bought cloud storage plan A on Friday.
Expected: unique, accepted
```

```text
Source: crm_import
Content: Customer Arun bought cloud storage plan A on Friday.
Expected: redundant, rejected
```

```text
Source: crm_import
Content: Customer Arun purchased cloud storage plan A on Friday.
Expected: redundant or false_positive depending on similarity score
```

```text
Source: support_log
Content: Customer Meera requested database backup verification.
Expected: unique, accepted
```

## Deployment Notes

For a cloud demo, deploy the repository to a Python-friendly platform such as Render, Railway, or an academic cloud VM. Start command:

```bash
python app.py
```

If the platform provides a dynamic port, update `HOST` and `PORT` in `app.py` to read from environment variables before deploying.

## Internship Criteria Covered

- Designed a system that identifies and classifies redundant data and false positives.
- Implemented validation against existing stored data.
- Prevented duplicate data insertion.
- Appended only unique or verified entries.
- Improved database accuracy through redundancy avoidance and audit logging.
- Added an agent that can inspect, submit, and batch-process records.
