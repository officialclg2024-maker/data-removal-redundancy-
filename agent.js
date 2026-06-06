const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const DB_PATH = path.join(__dirname, "agent-data.json");
const SIMILARITY_THRESHOLD = 0.88;
const FALSE_POSITIVE_THRESHOLD = 0.65;

function normalizeText(value) {
  return String(value || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function fingerprint(value) {
  return crypto.createHash("sha256").update(normalizeText(value)).digest("hex");
}

function loadDatabase() {
  if (!fs.existsSync(DB_PATH)) {
    return { records: [], logs: [] };
  }
  return JSON.parse(fs.readFileSync(DB_PATH, "utf8"));
}

function saveDatabase(database) {
  fs.writeFileSync(DB_PATH, JSON.stringify(database, null, 2));
}

function similarity(a, b) {
  const left = normalizeText(a);
  const right = normalizeText(b);
  const matrix = Array.from({ length: left.length + 1 }, () =>
    Array(right.length + 1).fill(0)
  );

  for (let i = 0; i <= left.length; i += 1) matrix[i][0] = i;
  for (let j = 0; j <= right.length; j += 1) matrix[0][j] = j;

  for (let i = 1; i <= left.length; i += 1) {
    for (let j = 1; j <= right.length; j += 1) {
      const cost = left[i - 1] === right[j - 1] ? 0 : 1;
      matrix[i][j] = Math.min(
        matrix[i - 1][j] + 1,
        matrix[i][j - 1] + 1,
        matrix[i - 1][j - 1] + cost
      );
    }
  }

  const maxLength = Math.max(left.length, right.length, 1);
  return 1 - matrix[left.length][right.length] / maxLength;
}

function findBestMatch(records, content) {
  let bestRecord = null;
  let bestScore = 0;

  for (const record of records) {
    const score = similarity(content, record.content);
    if (score > bestScore) {
      bestRecord = record;
      bestScore = score;
    }
  }

  return { bestRecord, bestScore };
}

function validateRecord(source, content, database = loadDatabase()) {
  const cleanSource = String(source || "").trim();
  const cleanContent = String(content || "").trim();
  const normalizedContent = normalizeText(cleanContent);

  if (!cleanSource) {
    return buildDecision(source, content, "invalid", "rejected", 0, null, "Source is required.");
  }

  if (normalizedContent.length < 8) {
    return buildDecision(
      source,
      content,
      "invalid",
      "rejected",
      0,
      null,
      "Content must contain at least 8 meaningful characters."
    );
  }

  const contentHash = fingerprint(cleanContent);
  const exactMatch = database.records.find((record) => record.hash === contentHash);

  if (exactMatch) {
    return buildDecision(
      source,
      content,
      "redundant",
      "rejected",
      1,
      exactMatch.id,
      "An exact duplicate already exists in the database."
    );
  }

  const { bestRecord, bestScore } = findBestMatch(database.records, cleanContent);

  if (bestRecord && bestScore >= SIMILARITY_THRESHOLD) {
    return buildDecision(
      source,
      content,
      "redundant",
      "rejected",
      bestScore,
      bestRecord.id,
      "A highly similar record already exists."
    );
  }

  if (bestRecord && bestScore >= FALSE_POSITIVE_THRESHOLD) {
    return buildDecision(
      source,
      content,
      "false_positive",
      "accepted",
      bestScore,
      bestRecord.id,
      "The record is similar, but not similar enough to block insertion."
    );
  }

  return buildDecision(
    source,
    content,
    "unique",
    "accepted",
    bestScore,
    bestRecord ? bestRecord.id : null,
    "No matching record exceeded the redundancy threshold."
  );
}

function buildDecision(source, content, classification, status, similarityScore, matchedRecordId, reason) {
  return {
    source: String(source || "").trim(),
    content: String(content || "").trim(),
    classification,
    status,
    similarity: Number(similarityScore.toFixed(4)),
    matchedRecordId,
    reason,
    action: status === "accepted" ? "stored" : "blocked",
    checkedAt: new Date().toISOString(),
  };
}

function submitRecord(source, content) {
  const database = loadDatabase();
  const decision = validateRecord(source, content, database);

  if (decision.status === "accepted") {
    const record = {
      id: database.records.length + 1,
      source: decision.source,
      content: decision.content,
      normalizedContent: normalizeText(decision.content),
      hash: fingerprint(decision.content),
      createdAt: decision.checkedAt,
    };
    database.records.push(record);
    decision.matchedRecordId = record.id;
  }

  database.logs.push(decision);
  saveDatabase(database);
  return decision;
}

function inspectRecord(source, content) {
  const decision = validateRecord(source, content);
  return { ...decision, action: "preview_only" };
}

function usage() {
  console.log(`
Data Redundancy Removal Agent

Commands:
  node agent.js inspect --source "upload" --content "record text"
  node agent.js submit  --source "upload" --content "record text"
  node agent.js stats
`);
}

function readArg(name) {
  const index = process.argv.indexOf(`--${name}`);
  if (index === -1) return "";
  return process.argv[index + 1] || "";
}

function main() {
  const command = process.argv[2];

  if (!command || command === "help") {
    usage();
    return;
  }

  if (command === "stats") {
    const database = loadDatabase();
    console.log(
      JSON.stringify(
        {
          storedRecords: database.records.length,
          validationChecks: database.logs.length,
          accepted: database.logs.filter((log) => log.status === "accepted").length,
          rejected: database.logs.filter((log) => log.status === "rejected").length,
        },
        null,
        2
      )
    );
    return;
  }

  const source = readArg("source");
  const content = readArg("content");

  if (command === "inspect") {
    console.log(JSON.stringify(inspectRecord(source, content), null, 2));
    return;
  }

  if (command === "submit") {
    console.log(JSON.stringify(submitRecord(source, content), null, 2));
    return;
  }

  usage();
}

if (require.main === module) {
  main();
}

module.exports = {
  inspectRecord,
  submitRecord,
  validateRecord,
};
