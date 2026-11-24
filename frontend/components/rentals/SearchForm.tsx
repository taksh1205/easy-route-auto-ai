"use client";
import type { RentalQuery } from "../../lib/rentals";

type Props = {
  query: RentalQuery | null;
  turn: string;
  busy: boolean;
  onSearch: (query: Omit<RentalQuery, "location">) => void;
};

/** Structured search: the exact SQL filter, editable field by field. */
export default function SearchForm({ query, turn, busy, onSearch }: Props) {
  return (
    <form
      className="panel searchform"
      // Remount whenever the saved query changes so defaults never show a stale filter.
      key={turn + JSON.stringify(query)}
      onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const budget = form.get("budget");
        const seats = form.get("seats");
        onSearch({
          start: String(form.get("start")),
          end: String(form.get("end")),
          period: form.get("period") as RentalQuery["period"],
          body: (form.get("body") as string) || null,
          min_seats: seats ? Number(seats) : null,
          budget_cents: budget ? Math.round(Number(budget) * 100) : null,
        });
      }}
    >
      <h2>Search the fleet</h2>
      <div className="fields">
        <label>
          Pickup date
          <input name="start" defaultValue={query?.start} type="date" required />
        </label>
        <label>
          Return date
          <input name="end" defaultValue={query?.end} type="date" required />
        </label>
        <label>
          Body type
          <select name="body" defaultValue={query ? query.body || "" : "suv"}>
            <option value="">Any type</option>
            <option>suv</option>
            <option>sedan</option>
            <option>truck</option>
            <option>hatchback</option>
          </select>
        </label>
        <label>
          Rate period
          <select name="period" defaultValue={query?.period || "monthly"}>
            <option>monthly</option>
            <option>weekly</option>
            <option>daily</option>
          </select>
        </label>
        <label>
          Maximum USD per selected period
          <input
            name="budget"
            type="number"
            min="0"
            step=".01"
            defaultValue={query ? (query.budget_cents == null ? "" : query.budget_cents / 100) : 950}
          />
        </label>
        <label>
          Minimum seats
          <input name="seats" type="number" min="1" max="100" defaultValue={query?.min_seats || ""} />
        </label>
      </div>
      <button disabled={busy}>Search fleet</button>
    </form>
  );
}
