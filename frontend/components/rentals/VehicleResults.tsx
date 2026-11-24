import { money, type Car } from "../../lib/rentals";

type Props = {
  cars: Car[];
  turn: string;
  selected: number | null;
  busy: boolean;
  onSelect: (position: number) => void;
  onQuote: (position: number) => void;
};

/** Eligible vehicles in the server's display order; positions bind to this turn. */
export default function VehicleResults({ cars, turn, selected, busy, onSelect, onQuote }: Props) {
  if (turn && !cars.length) return <p className="empty">No exact matches for the current search.</p>;
  return (
    <div className="results">
      {cars.map((car, index) => (
        <article className={"card" + (selected === car.id ? " chosen" : "")} key={car.id}>
          <h3>
            {index + 1}. {car.name}
          </h3>
          <p>
            {car.seats} seats · {money(car.lines[0].unit_cents)} {car.lines[0].unit} rate ·{" "}
            {money(car.total_cents)} for selected dates
          </p>
          <div className="actions">
            <button disabled={busy} onClick={() => onSelect(index + 1)}>
              {selected === car.id ? "Selected vehicle" : "Select vehicle"}
            </button>
            <button className="secondary" disabled={busy} onClick={() => onQuote(index + 1)}>
              Get itemized quote
            </button>
          </div>
        </article>
      ))}
    </div>
  );
}
