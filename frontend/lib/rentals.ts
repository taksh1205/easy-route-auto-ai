// Typed client for the rental desk API. Every value rendered by the UI comes from these
// server responses; the browser never computes prices, availability or eligibility.
import { request, type Session } from "./api";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Period = "daily" | "weekly" | "monthly";

export type QuoteLine = { count: number; unit: string; unit_cents: number };

export type Terms = {
  vehicle_id: number;
  start: string;
  end: string;
  location: string;
  total_cents: number;
  lines: QuoteLine[];
  extends?: string;
};

export type RentalQuery = {
  start: string;
  end: string;
  location: string;
  period: Period | null;
  body: string | null;
  min_seats: number | null;
  budget_cents: number | null;
};

export type RecordRow = { id: string; status: string; terms: Terms; expires: number };

export type Car = Terms & { name: string; id: number; seats: number };

export type Citation = { text: string; chunk_id: string; doc_id: string };

export type Override = { field: string; planner: unknown; applied: unknown; reason: string };

/** Union of the fields an /ask or /rental-discovery response may carry. */
export type AssistantReply = {
  clarification?: string;
  citations?: Citation[];
  explanation?: string | null;
  vehicles?: Car[];
  turn?: string;
  query?: RentalQuery;
  selection?: Car;
  comparison?: Car[];
  quote?: RecordRow;
  reconciliation?: { overrides: Override[] };
};

export type RentalState = {
  displayed: Car[];
  mode: string;
  model?: string | null;
  context: { query: RentalQuery; turn: string; selected?: number } | null;
  records: RecordRow[];
};

export const money = (cents: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);

export function modeLabel(mode: string, model?: string | null): string {
  if (mode === "loading") return "Connecting…";
  if (mode === "deterministic") return "Offline grammar (no LLM inference)";
  return `Live LLM planner · ${mode}${model ? ` · ${model}` : ""}`;
}

/** Text for the polite live region. Kept deliberately plain for screen readers. */
export function describeReply(reply: AssistantReply): string {
  if (reply.clarification) return reply.clarification;
  const policy = [
    ...(reply.citations ?? []).map((c) => `${c.text} [${c.chunk_id}]`),
    reply.explanation,
  ].filter(Boolean);
  if (policy.length) return policy.join("\n");
  if (reply.selection) return "Selected " + reply.selection.name;
  if (reply.comparison?.length)
    return reply.comparison.map((v) => `${v.name} · ${v.seats} seats · ${money(v.total_cents)}`).join("\n");
  if (reply.quote) return "Quote ready below for vehicle " + reply.quote.terms.vehicle_id;
  return reply.vehicles?.length ? "Search updated." : "No exact matches.";
}

const FIELD_NAMES: Record<string, string> = {
  min_seats: "seat minimum",
  budget_cents: "budget",
  body: "body type",
  dates: "dates",
};

/** Human-readable record of every place the server overrode the planner. */
export function describeOverrides(overrides: Override[] = []): string[] {
  return overrides.map((o) => {
    const name = FIELD_NAMES[o.field] ?? o.field;
    const value =
      o.field === "budget_cents" && typeof o.applied === "number" ? money(o.applied) : String(o.applied);
    return `Kept your ${name} (${value}): ${o.reason}.`;
  });
}

export function rentals(session: Session) {
  const path = `/sessions/${session.id}/rentals`;
  return {
    state: () => request(path, "GET", undefined, session) as Promise<RentalState>,
    discover: (message: string) =>
      request(
        `/sessions/${session.id}/rental-discovery`,
        "POST",
        { message },
        session,
      ) as Promise<AssistantReply>,
    search: (query: Omit<RentalQuery, "location"> & { location?: string }) =>
      request(path + "/search", "POST", query, session) as Promise<AssistantReply>,
    ask: (turn: string, message: string) =>
      request(path + "/ask", "POST", { turn, message }, session) as Promise<AssistantReply>,
    reference: (turn: string, operation: "select" | "quote", position: number) =>
      request(path + "/reference", "POST", { turn, operation, position }, session) as Promise<AssistantReply>,
    submit: (record: RecordRow) =>
      request(`${path}/${record.id}/submit`, "POST", { terms: record.terms }, session, "submit-" + record.id),
    extend: (record: RecordRow, end: string) =>
      request(`${path}/${record.id}/extension`, "POST", { end }, session),
    clearChat: () => request(`/sessions/${session.id}`, "DELETE", undefined, session),
  };
}

export async function staffRequest(
  token: string,
  path: string,
  init: { method?: string; body?: unknown } = {},
) {
  const response = await fetch(API_BASE + "/rental-staff/" + path, {
    method: init.method ?? (init.body ? "POST" : "GET"),
    headers: { "X-Employee-Token": token, "Content-Type": "application/json" },
    body: init.body ? JSON.stringify(init.body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request failed");
  return data;
}
