const BASE = "/api";

async function request(path, options) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Request failed: ${res.status}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export function getEntries() {
  return request("/entries");
}

export function getStats() {
  return request("/stats");
}

export function createEntry(entry) {
  return request("/entries", { method: "POST", body: JSON.stringify(entry) });
}

export function deleteEntry(id) {
  return request(`/entries/${id}`, { method: "DELETE" });
}
