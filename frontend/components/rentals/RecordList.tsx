import { money, type RecordRow } from "../../lib/rentals";

type Props = {
  records: RecordRow[];
  busy: boolean;
  onAccept: (record: RecordRow) => void;
  onExtend: (record: RecordRow, end: string) => void;
};

const STATUS_HELP: Record<string, string> = {
  quoted: "Offer only. Nothing is held until you accept the exact terms.",
  pending: "You accepted these terms. Staff must approve before dates are held.",
  confirmed: "Approved by staff. These dates are reserved in the ledger.",
  extended: "Superseded by an approved extension.",
  declined: "Staff declined this request.",
  cancelled: "Cancelled by staff. Dates released.",
};

/** The customer's quote → inquiry → reservation ledger (survives clearing chat). */
export default function RecordList({ records, busy, onAccept, onExtend }: Props) {
  return (
    <section>
      <h2>Your rental records</h2>
      {!records.length && <p className="hint">Quotes and reservations appear here.</p>}
      {records.map((record) => (
        <article className={"panel record " + record.status} key={record.id}>
          <strong>
            {record.status} · {record.id}
          </strong>
          <p className="hint">{STATUS_HELP[record.status]}</p>
          <p>
            Vehicle {record.terms.vehicle_id} · {record.terms.start} to {record.terms.end} ·{" "}
            {record.terms.location}
          </p>
          {record.terms.lines
            .filter((line) => line.count > 0)
            .map((line, index) => (
              <p key={index}>
                {line.count} × {money(line.unit_cents)} ({line.unit})
              </p>
            ))}
          <b>Total {money(record.terms.total_cents)}</b>
          {record.status === "quoted" && (
            <>
              <p>
                Accept by {new Date(record.expires * 1000).toLocaleString()}. Request a fresh quote after
                expiry.
              </p>
              <button disabled={busy} onClick={() => onAccept(record)}>
                Accept these terms and request staff review
              </button>
            </>
          )}
          {record.status === "confirmed" && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                onExtend(record, String(new FormData(event.currentTarget).get("newEnd")));
              }}
            >
              <label>
                New return date
                <input required type="date" name="newEnd" />
              </label>
              <button disabled={busy}>Quote an extension</button>
            </form>
          )}
        </article>
      ))}
    </section>
  );
}
