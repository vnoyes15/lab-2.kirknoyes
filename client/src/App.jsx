import { useEffect, useState } from "react";
import { createEntry, deleteEntry, getEntries, getStats } from "./api.js";

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

function RunForm({ onSubmit }) {
  const [distance, setDistance] = useState("2.5");
  const [duration, setDuration] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await onSubmit({
        date: todayStr(),
        type: "run",
        distanceMiles: Number(distance),
        durationMinutes: duration ? Number(duration) : null,
      });
      setDuration("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="log-form" onSubmit={handleSubmit}>
      <h3>Log today's walk/run</h3>
      <label>
        Distance (miles)
        <input
          type="number"
          min="0"
          step="0.1"
          value={distance}
          onChange={(e) => setDistance(e.target.value)}
          required
        />
      </label>
      <label>
        Duration (minutes, optional)
        <input
          type="number"
          min="0"
          step="1"
          value={duration}
          onChange={(e) => setDuration(e.target.value)}
        />
      </label>
      <button type="submit" disabled={busy}>
        Log run
      </button>
    </form>
  );
}

function StrengthForm({ onSubmit }) {
  const [duration, setDuration] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await onSubmit({
        date: todayStr(),
        type: "strength",
        durationMinutes: duration ? Number(duration) : null,
        notes,
      });
      setDuration("");
      setNotes("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="log-form" onSubmit={handleSubmit}>
      <h3>Log today's strength session</h3>
      <label>
        Duration (minutes, optional)
        <input
          type="number"
          min="0"
          step="1"
          value={duration}
          onChange={(e) => setDuration(e.target.value)}
        />
      </label>
      <label>
        Notes (optional)
        <input type="text" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="legs, push day..." />
      </label>
      <button type="submit" disabled={busy}>
        Log strength session
      </button>
    </form>
  );
}

function RunStreakTile({ run }) {
  const status = run.todayDone ? "good" : "warning";
  return (
    <div className="stat-tile">
      <div className="stat-label">Run streak</div>
      <div className="stat-value">{run.streak}</div>
      <div className={`stat-status stat-status--${status}`}>
        {run.todayDone ? "Today logged" : "Not logged yet today"}
      </div>
    </div>
  );
}

function StrengthMeter({ strength }) {
  const pct = Math.min(100, (strength.count / strength.goalMax) * 100);
  const met = strength.count >= strength.goalMin;
  return (
    <div className="stat-tile">
      <div className="stat-label">Strength sessions this week</div>
      <div className="stat-value">
        {strength.count}
        <span className="stat-value-goal"> / {strength.goalMin}-{strength.goalMax}</span>
      </div>
      <div className="meter-track">
        <div className={`meter-fill meter-fill--${met ? "good" : "warning"}`} style={{ width: `${pct}%` }} />
      </div>
      <div className={`stat-status stat-status--${met ? "good" : "warning"}`}>
        {met ? "Goal met this week" : `${strength.goalMin - strength.count} more to hit your goal`}
      </div>
    </div>
  );
}

function HistoryList({ entries, onDelete }) {
  if (entries.length === 0) {
    return <p className="muted">No entries yet — log your first run or strength session above.</p>;
  }
  return (
    <table className="history-table">
      <thead>
        <tr>
          <th>Date</th>
          <th>Type</th>
          <th>Details</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {entries.map((entry) => (
          <tr key={entry.id}>
            <td>{entry.date}</td>
            <td>{entry.type === "run" ? "Walk/run" : "Strength"}</td>
            <td>
              {entry.type === "run" ? `${entry.distanceMiles} mi` : entry.notes || "—"}
              {entry.durationMinutes ? ` · ${entry.durationMinutes} min` : ""}
            </td>
            <td>
              <button className="link-button" onClick={() => onDelete(entry.id)}>
                Delete
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function App() {
  const [stats, setStats] = useState(null);
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState(null);

  async function refresh() {
    try {
      const [statsData, entriesData] = await Promise.all([getStats(), getEntries()]);
      setStats(statsData);
      setEntries(entriesData);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleCreate(entry) {
    await createEntry(entry);
    await refresh();
  }

  async function handleDelete(id) {
    await deleteEntry(id);
    await refresh();
  }

  return (
    <div className="page">
      <header>
        <h1>Stride</h1>
        <p className="muted">Every morning, 6am: 2-3 mile walk/run, plus strength training 4-5x/week.</p>
      </header>

      {error && <div className="error-banner">{error}</div>}

      {stats && (
        <section className="stats-row">
          <RunStreakTile run={stats.run} />
          <StrengthMeter strength={stats.strength} />
        </section>
      )}

      <section className="forms-row">
        <RunForm onSubmit={handleCreate} />
        <StrengthForm onSubmit={handleCreate} />
      </section>

      <section>
        <h2>History</h2>
        <HistoryList entries={entries} onDelete={handleDelete} />
      </section>
    </div>
  );
}
