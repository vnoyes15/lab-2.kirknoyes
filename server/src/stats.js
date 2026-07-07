export const MIN_RUN_MILES = 2;
export const STRENGTH_GOAL_MIN = 4;
export const STRENGTH_GOAL_MAX = 5;

export function isQualifyingRun(entry) {
  return entry.type === "run" && Number(entry.distanceMiles) >= MIN_RUN_MILES;
}

function parseDateOnly(dateStr) {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function formatDateOnly(date) {
  return date.toISOString().slice(0, 10);
}

function addDays(dateStr, days) {
  const date = parseDateOnly(dateStr);
  date.setUTCDate(date.getUTCDate() + days);
  return formatDateOnly(date);
}

// Monday-start week containing dateStr.
export function startOfWeek(dateStr) {
  const date = parseDateOnly(dateStr);
  const isoDayIndex = (date.getUTCDay() + 6) % 7; // Mon=0 .. Sun=6
  date.setUTCDate(date.getUTCDate() - isoDayIndex);
  return formatDateOnly(date);
}

export function computeRunStreak(entries, todayStr) {
  const runDates = new Set(entries.filter(isQualifyingRun).map((e) => e.date));
  const todayDone = runDates.has(todayStr);

  let streak = 0;
  let cursor = todayDone ? todayStr : addDays(todayStr, -1);
  while (runDates.has(cursor)) {
    streak += 1;
    cursor = addDays(cursor, -1);
  }

  return { streak, todayDone };
}

export function computeWeeklyStrengthCount(entries, todayStr) {
  const weekStart = startOfWeek(todayStr);
  const weekEnd = addDays(weekStart, 6);

  const strengthDaysThisWeek = new Set(
    entries
      .filter((e) => e.type === "strength" && e.date >= weekStart && e.date <= weekEnd)
      .map((e) => e.date)
  );

  return {
    count: strengthDaysThisWeek.size,
    goalMin: STRENGTH_GOAL_MIN,
    goalMax: STRENGTH_GOAL_MAX,
    weekStart,
    weekEnd,
  };
}

export function computeStats(entries, todayStr = formatDateOnly(new Date())) {
  const run = computeRunStreak(entries, todayStr);
  const strength = computeWeeklyStrengthCount(entries, todayStr);
  const todayStrengthDone = entries.some((e) => e.type === "strength" && e.date === todayStr);

  return {
    today: todayStr,
    run,
    strength,
    todayStrengthDone,
  };
}
