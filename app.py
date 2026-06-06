from __future__ import annotations

import hashlib
import html
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


APP_TITLE = "Data Redundancy Removal System"
DB_PATH = Path("redundancy.db")
HOST = "127.0.0.1"
PORT = 8000
SIMILARITY_THRESHOLD = 0.88


@dataclass
class ValidationResult:
    classification: str
    status: str
    similarity: float
    matched_record_id: int | None
    reason: str


def normalize_text(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def fingerprint(value: str) -> str:
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                content TEXT NOT NULL,
                normalized_content TEXT NOT NULL,
                content_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS validation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                content TEXT NOT NULL,
                classification TEXT NOT NULL,
                status TEXT NOT NULL,
                similarity REAL NOT NULL,
                matched_record_id INTEGER,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (matched_record_id) REFERENCES records(id)
            );
            """
        )


def get_records() -> list[sqlite3.Row]:
    with connect() as conn:
        return list(conn.execute("SELECT * FROM records ORDER BY id DESC"))


def get_logs(limit: int = 25) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                "SELECT * FROM validation_logs ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        )


def find_best_match(normalized_content: str) -> tuple[sqlite3.Row | None, float]:
    best_record: sqlite3.Row | None = None
    best_score = 0.0
    for record in get_records():
        score = SequenceMatcher(
            None,
            normalized_content,
            record["normalized_content"],
        ).ratio()
        if score > best_score:
            best_record = record
            best_score = score
    return best_record, best_score


def validate_record(source: str, content: str) -> ValidationResult:
    normalized_content = normalize_text(content)
    if not source.strip():
        return ValidationResult(
            "invalid",
            "rejected",
            0.0,
            None,
            "Source is required.",
        )
    if len(normalized_content) < 8:
        return ValidationResult(
            "invalid",
            "rejected",
            0.0,
            None,
            "Content must contain at least 8 meaningful characters.",
        )

    current_hash = fingerprint(content)
    with connect() as conn:
        exact = conn.execute(
            "SELECT id FROM records WHERE content_hash = ?",
            (current_hash,),
        ).fetchone()

    if exact:
        return ValidationResult(
            "redundant",
            "rejected",
            1.0,
            exact["id"],
            "An exact duplicate already exists in the database.",
        )

    best_record, best_score = find_best_match(normalized_content)
    if best_record and best_score >= SIMILARITY_THRESHOLD:
        return ValidationResult(
            "redundant",
            "rejected",
            best_score,
            best_record["id"],
            "A highly similar record already exists.",
        )

    if best_record and best_score >= 0.65:
        return ValidationResult(
            "false_positive",
            "accepted",
            best_score,
            best_record["id"],
            "The record is similar, but not similar enough to block insertion.",
        )

    return ValidationResult(
        "unique",
        "accepted",
        best_score,
        best_record["id"] if best_record else None,
        "No matching record exceeded the redundancy threshold.",
    )


def append_unique_record(source: str, content: str) -> ValidationResult:
    result = validate_record(source, content)
    normalized_content = normalize_text(content)
    current_hash = fingerprint(content)
    now = utc_now()
    inserted_id: int | None = None

    with connect() as conn:
        if result.status == "accepted":
            cursor = conn.execute(
                """
                INSERT INTO records (
                    source,
                    content,
                    normalized_content,
                    content_hash,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (source.strip(), content.strip(), normalized_content, current_hash, now),
            )
            inserted_id = int(cursor.lastrowid)

        conn.execute(
            """
            INSERT INTO validation_logs (
                source,
                content,
                classification,
                status,
                similarity,
                matched_record_id,
                reason,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.strip(),
                content.strip(),
                result.classification,
                result.status,
                result.similarity,
                result.matched_record_id,
                result.reason,
                now,
            ),
        )

    if inserted_id is not None:
        result.matched_record_id = inserted_id
    return result


def stats() -> dict[str, Any]:
    with connect() as conn:
        total_records = conn.execute("SELECT COUNT(*) AS count FROM records").fetchone()[
            "count"
        ]
        total_checks = conn.execute(
            "SELECT COUNT(*) AS count FROM validation_logs"
        ).fetchone()["count"]
        rejected = conn.execute(
            "SELECT COUNT(*) AS count FROM validation_logs WHERE status = 'rejected'"
        ).fetchone()["count"]
        accepted = conn.execute(
            "SELECT COUNT(*) AS count FROM validation_logs WHERE status = 'accepted'"
        ).fetchone()["count"]
    return {
        "total_records": total_records,
        "total_checks": total_checks,
        "accepted": accepted,
        "rejected": rejected,
    }


def escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def badge(classification: str) -> str:
    classes = {
        "unique": "badge good",
        "false_positive": "badge warn",
        "redundant": "badge bad",
        "invalid": "badge bad",
    }
    return f'<span class="{classes.get(classification, "badge")}">{escape(classification.replace("_", " "))}</span>'


def render_page(result: ValidationResult | None = None) -> bytes:
    current_stats = stats()
    records = get_records()
    logs = get_logs()
    result_panel = ""

    if result:
        result_panel = f"""
        <section class="notice">
            <div>
                <p class="eyebrow">Validation result</p>
                <h2>{badge(result.classification)} {escape(result.status.title())}</h2>
                <p>{escape(result.reason)}</p>
            </div>
            <div class="score">
                <span>{result.similarity:.2%}</span>
                <small>Similarity</small>
            </div>
        </section>
        """

    rows = "\n".join(
        f"""
        <tr>
            <td>{record["id"]}</td>
            <td>{escape(record["source"])}</td>
            <td>{escape(record["content"])}</td>
            <td>{escape(record["created_at"])}</td>
        </tr>
        """
        for record in records
    )
    log_rows = "\n".join(
        f"""
        <tr>
            <td>{escape(log["created_at"])}</td>
            <td>{badge(log["classification"])}</td>
            <td>{escape(log["status"])}</td>
            <td>{log["similarity"]:.2%}</td>
            <td>{escape(log["reason"])}</td>
        </tr>
        """
        for log in logs
    )

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{APP_TITLE}</title>
    <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
    <main>
        <header>
            <div>
                <p class="eyebrow">Cloud Computing Task 1</p>
                <h1>{APP_TITLE}</h1>
                <p class="lede">Validate new data against existing cloud records, classify redundancy, and append only unique verified entries.</p>
            </div>
        </header>

        <section class="metrics">
            <article><span>{current_stats["total_records"]}</span><small>Stored records</small></article>
            <article><span>{current_stats["total_checks"]}</span><small>Validation checks</small></article>
            <article><span>{current_stats["accepted"]}</span><small>Accepted</small></article>
            <article><span>{current_stats["rejected"]}</span><small>Rejected</small></article>
        </section>

        {result_panel}

        <section class="workspace">
            <form method="post" action="/records">
                <label>
                    Data source
                    <input name="source" placeholder="CRM import, sensor stream, user upload" required>
                </label>
                <label>
                    New data entry
                    <textarea name="content" rows="8" placeholder="Paste the record content to validate..." required></textarea>
                </label>
                <button type="submit">Validate and append</button>
            </form>

            <aside>
                <h2>Validation logic</h2>
                <p>Exact duplicates are detected with SHA-256 fingerprints. Near duplicates are detected with normalized text similarity.</p>
                <ul>
                    <li>88% or higher: redundant, rejected</li>
                    <li>65% to 87%: false positive, accepted</li>
                    <li>Below 65%: unique, accepted</li>
                </ul>
            </aside>
        </section>

        <section>
            <div class="section-title">
                <h2>Verified Data</h2>
                <a href="/api/records">JSON API</a>
            </div>
            <div class="table-wrap">
                <table>
                    <thead><tr><th>ID</th><th>Source</th><th>Content</th><th>Created</th></tr></thead>
                    <tbody>{rows or '<tr><td colspan="4">No verified records yet.</td></tr>'}</tbody>
                </table>
            </div>
        </section>

        <section>
            <div class="section-title">
                <h2>Validation Audit</h2>
                <a href="/api/logs">JSON API</a>
            </div>
            <div class="table-wrap">
                <table>
                    <thead><tr><th>Checked</th><th>Class</th><th>Status</th><th>Similarity</th><th>Reason</th></tr></thead>
                    <tbody>{log_rows or '<tr><td colspan="5">No validation checks yet.</td></tr>'}</tbody>
                </table>
            </div>
        </section>
    </main>
</body>
</html>"""
    return html_doc.encode("utf-8")


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html(render_page())
        elif parsed.path == "/static/styles.css":
            self.send_css(STYLES)
        elif parsed.path == "/api/records":
            self.send_json([dict(row) for row in get_records()])
        elif parsed.path == "/api/logs":
            self.send_json([dict(row) for row in get_logs(100)])
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/records":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        form = parse_qs(body)
        source = form.get("source", [""])[0]
        content = form.get("content", [""])[0]
        result = append_unique_record(source, content)
        self.send_html(render_page(result))

    def send_html(self, content: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_css(self, content: str) -> None:
        encoded = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/css; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_json(self, content: Any) -> None:
        encoded = json.dumps(content, indent=2).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: Any) -> None:
        return


STYLES = """
:root {
    color-scheme: light;
    --ink: #15202b;
    --muted: #5e6b76;
    --line: #d9e1e8;
    --panel: #ffffff;
    --bg: #eef4f7;
    --accent: #176d62;
    --accent-dark: #0f4b43;
    --good: #1d7a38;
    --warn: #9a6410;
    --bad: #a93434;
}

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family: Arial, Helvetica, sans-serif;
    color: var(--ink);
    background: var(--bg);
}

main {
    width: min(1120px, calc(100vw - 32px));
    margin: 0 auto;
    padding: 32px 0 48px;
}

header {
    background: #dbece8;
    border: 1px solid #bdd5cf;
    border-radius: 8px;
    padding: 28px;
}

h1,
h2,
p {
    margin-top: 0;
}

h1 {
    margin-bottom: 10px;
    font-size: clamp(2rem, 5vw, 3.5rem);
}

h2 {
    margin-bottom: 12px;
    font-size: 1.25rem;
}

.eyebrow {
    margin-bottom: 8px;
    color: var(--accent-dark);
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0;
    text-transform: uppercase;
}

.lede {
    max-width: 760px;
    margin-bottom: 0;
    color: var(--muted);
    font-size: 1.05rem;
    line-height: 1.6;
}

.metrics {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 14px;
    margin: 18px 0;
}

.metrics article,
.notice,
.workspace,
section {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 8px;
}

.metrics article {
    padding: 18px;
}

.metrics span,
.score span {
    display: block;
    color: var(--accent-dark);
    font-size: 2rem;
    font-weight: 800;
}

small {
    color: var(--muted);
}

.notice {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 18px;
    padding: 20px;
}

.score {
    min-width: 130px;
    text-align: right;
}

.workspace {
    display: grid;
    grid-template-columns: minmax(0, 1.3fr) minmax(260px, 0.7fr);
    gap: 20px;
    margin-bottom: 18px;
    padding: 20px;
}

form {
    display: grid;
    gap: 14px;
}

label {
    display: grid;
    gap: 8px;
    color: var(--muted);
    font-weight: 700;
}

input,
textarea {
    width: 100%;
    border: 1px solid #bac8d2;
    border-radius: 6px;
    padding: 12px;
    color: var(--ink);
    font: inherit;
}

textarea {
    resize: vertical;
}

button {
    width: fit-content;
    border: 0;
    border-radius: 6px;
    padding: 12px 18px;
    color: #fff;
    background: var(--accent);
    font: inherit;
    font-weight: 800;
    cursor: pointer;
}

button:hover {
    background: var(--accent-dark);
}

aside {
    border-left: 4px solid var(--accent);
    padding-left: 18px;
}

aside p,
aside li {
    color: var(--muted);
    line-height: 1.55;
}

section {
    margin-bottom: 18px;
    padding: 20px;
}

.section-title {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

a {
    color: var(--accent-dark);
    font-weight: 700;
}

.table-wrap {
    overflow-x: auto;
}

table {
    width: 100%;
    border-collapse: collapse;
    min-width: 680px;
}

th,
td {
    border-top: 1px solid var(--line);
    padding: 12px;
    text-align: left;
    vertical-align: top;
}

th {
    color: var(--muted);
    font-size: 0.82rem;
    text-transform: uppercase;
}

.badge {
    display: inline-flex;
    align-items: center;
    min-height: 26px;
    border-radius: 999px;
    padding: 4px 10px;
    color: #fff;
    font-size: 0.78rem;
    font-weight: 800;
    text-transform: capitalize;
}

.good {
    background: var(--good);
}

.warn {
    background: var(--warn);
}

.bad {
    background: var(--bad);
}

@media (max-width: 760px) {
    main {
        width: min(100vw - 20px, 1120px);
        padding-top: 10px;
    }

    header,
    .workspace,
    section {
        padding: 16px;
    }

    .metrics,
    .workspace {
        grid-template-columns: 1fr;
    }

    .notice,
    .section-title {
        align-items: flex-start;
        flex-direction: column;
    }

    .score {
        text-align: left;
    }
}
"""


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), RequestHandler)
    print(f"{APP_TITLE} running at http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
