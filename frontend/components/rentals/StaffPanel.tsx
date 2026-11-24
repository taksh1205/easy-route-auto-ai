"use client";
import { useState } from "react";
import { API_BASE, money, staffRequest, type RecordRow } from "../../lib/rentals";

type Props = {
  busy: boolean;
  run: (task: () => Promise<void>) => Promise<void>;
  notify: (message: string) => void;
};

/** Staff decisions. Every action is authorized server-side by an individual role token. */
export default function StaffPanel({ busy, run, notify }: Props) {
  const [token, setToken] = useState("");
  const [queue, setQueue] = useState<RecordRow[]>([]);
  const reload = async () => setQueue(await staffRequest(token, "queue"));

  return (
    <details className="panel staff">
      <summary>Staff review</summary>
      <label>
        Individual employee token
        <input type="password" value={token} onChange={(event) => setToken(event.target.value)} />
      </label>
      <button onClick={() => void run(reload)}>Load requests</button>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          void run(async () => {
            const response = await fetch(
              `${API_BASE}/rental-staff/fleet/${Number(form.get("vehicle"))}?active=${form.get("active")}`,
              { method: "PATCH", headers: { "X-Employee-Token": token } },
            );
            if (!response.ok) throw new Error((await response.json()).detail);
            notify("Fleet availability updated.");
          });
        }}
      >
        <label>
          Fleet vehicle ID
          <input name="vehicle" type="number" min="1" required />
        </label>
        <select name="active" aria-label="Fleet status">
          <option value="true">Available</option>
          <option value="false">Out of service</option>
        </select>
        <button disabled={busy}>Update fleet (manager)</button>
      </form>
      {queue.map((record) => (
        <article key={record.id}>
          <p>
            {record.id} · {record.status} · {record.terms.start} to {record.terms.end} ·{" "}
            {money(record.terms.total_cents)}
            {record.terms.extends ? " · extension" : ""}
          </p>
          {(record.status === "pending" ? ["approve", "decline"] : ["cancel"]).map((action) => (
            <button
              key={action}
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  await staffRequest(token, `${record.id}/decision`, { body: { action } });
                  await reload();
                })
              }
            >
              {action}
            </button>
          ))}
        </article>
      ))}
    </details>
  );
}
