import process from "node:process";
import cors from "cors";
import express from "express";
import { addEntry, deleteEntry, readEntries } from "./store.js";
import { computeStats } from "./stats.js";

const PORT = process.env.PORT || 3001;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

const app = express();
app.use(cors());
app.use(express.json());

app.get("/api/health", (_req, res) => res.json({ ok: true }));

app.get("/api/entries", (_req, res) => {
  const entries = readEntries().sort((a, b) => b.date.localeCompare(a.date));
  res.json(entries);
});

app.post("/api/entries", (req, res) => {
  const { date, type, distanceMiles, durationMinutes, notes } = req.body ?? {};

  if (!DATE_RE.test(date)) {
    return res.status(400).json({ error: "date must be YYYY-MM-DD" });
  }
  if (type !== "run" && type !== "strength") {
    return res.status(400).json({ error: "type must be 'run' or 'strength'" });
  }
  if (type === "run" && !(Number(distanceMiles) > 0)) {
    return res.status(400).json({ error: "distanceMiles must be a positive number for a run" });
  }
  if (durationMinutes !== undefined && durationMinutes !== null && !(Number(durationMinutes) >= 0)) {
    return res.status(400).json({ error: "durationMinutes must be a non-negative number" });
  }

  const entry = addEntry({
    date,
    type,
    distanceMiles: type === "run" ? Number(distanceMiles) : null,
    durationMinutes: durationMinutes != null ? Number(durationMinutes) : null,
    notes,
  });
  res.status(201).json(entry);
});

app.delete("/api/entries/:id", (req, res) => {
  const removed = deleteEntry(req.params.id);
  if (!removed) return res.status(404).json({ error: "entry not found" });
  res.status(204).end();
});

app.get("/api/stats", (req, res) => {
  const entries = readEntries();
  const today = typeof req.query.today === "string" && DATE_RE.test(req.query.today) ? req.query.today : undefined;
  res.json(computeStats(entries, today));
});

app.listen(PORT, () => {
  console.log(`stride-server listening on http://localhost:${PORT}`);
});
