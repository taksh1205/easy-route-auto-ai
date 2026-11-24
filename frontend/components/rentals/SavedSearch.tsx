import { money, type RentalQuery } from "../../lib/rentals";

/** The canonical saved query exactly as the server will filter it. */
export default function SavedSearch({ query }: { query: RentalQuery | null }) {
  if (!query) return null;
  const chips = [
    `${query.location}`,
    `${query.start} → ${query.end}`,
    query.body ? query.body.toUpperCase() : "Any body type",
    query.min_seats ? `≥ ${query.min_seats} seats` : "Any seat count",
    query.budget_cents != null && query.period
      ? `≤ ${money(query.budget_cents)} ${query.period}`
      : "No budget cap",
  ];
  return (
    <section className="saved" aria-label="Saved search">
      <span className="eyebrow">Saved search · enforced in SQL</span>
      <ul>
        {chips.map((chip) => (
          <li key={chip}>{chip}</li>
        ))}
      </ul>
    </section>
  );
}
