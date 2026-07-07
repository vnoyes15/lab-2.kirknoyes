import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DATA_DIR = join(__dirname, "..", "data");
const DATA_FILE = join(DATA_DIR, "entries.json");

function ensureDataFile() {
  if (!existsSync(DATA_DIR)) mkdirSync(DATA_DIR, { recursive: true });
  if (!existsSync(DATA_FILE)) writeFileSync(DATA_FILE, "[]");
}

export function readEntries() {
  ensureDataFile();
  return JSON.parse(readFileSync(DATA_FILE, "utf-8"));
}

function writeEntries(entries) {
  writeFileSync(DATA_FILE, JSON.stringify(entries, null, 2));
}

export function addEntry({ date, type, distanceMiles, durationMinutes, notes }) {
  const entries = readEntries();
  const entry = {
    id: randomUUID(),
    date,
    type,
    distanceMiles: distanceMiles ?? null,
    durationMinutes: durationMinutes ?? null,
    notes: notes ?? "",
    createdAt: new Date().toISOString(),
  };
  entries.push(entry);
  writeEntries(entries);
  return entry;
}

export function deleteEntry(id) {
  const entries = readEntries();
  const next = entries.filter((e) => e.id !== id);
  const removed = next.length !== entries.length;
  if (removed) writeEntries(next);
  return removed;
}
