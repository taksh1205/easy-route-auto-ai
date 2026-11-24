"use client";
import { useCallback, useEffect, useState } from "react";
import { readSession, request, saveSession, type Session } from "../../lib/api";
import {
  describeOverrides,
  describeReply,
  modeLabel,
  rentals,
  type AssistantReply,
  type Car,
  type RecordRow,
  type RentalQuery,
} from "../../lib/rentals";
import RecordList from "../../components/rentals/RecordList";
import SavedSearch from "../../components/rentals/SavedSearch";
import SearchForm from "../../components/rentals/SearchForm";
import StaffPanel from "../../components/rentals/StaffPanel";
import VehicleResults from "../../components/rentals/VehicleResults";

export default function RentalDesk() {
  const [session, setSession] = useState<Session | null>(null);
  const [mode, setMode] = useState("loading");
  const [model, setModel] = useState<string | null>(null);
  const [query, setQuery] = useState<RentalQuery | null>(null);
  const [turn, setTurn] = useState("");
  const [cars, setCars] = useState<Car[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [records, setRecords] = useState<RecordRow[]>([]);
  const [answer, setAnswer] = useState("");
  const [decisions, setDecisions] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  /** Re-read authoritative state; the server rotates the turn if the display changed. */
  const refresh = useCallback(async (current: Session) => {
    const state = await rentals(current).state();
    setQuery(state.context?.query ?? null);
    setSelected(state.context?.selected ?? null);
    setMode(state.mode);
    setModel(state.model ?? null);
    setRecords(state.records);
    setCars(state.displayed ?? []);
    setTurn(state.context?.turn ?? "");
  }, []);

  useEffect(() => {
    (async () => {
      let current = readSession();
      if (!current) {
        current = (await request("/sessions", "POST")) as Session;
        saveSession(current);
      }
      setSession(current);
      await refresh(current);
    })().catch((e) => setError(e.message));
  }, [refresh]);

  async function run(task: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await task();
      if (session) await refresh(session);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  function show(reply: AssistantReply) {
    setAnswer(describeReply(reply));
    setDecisions(describeOverrides(reply.reconciliation?.overrides));
    if (reply.vehicles) setCars(reply.vehicles);
    if (reply.turn) setTurn(reply.turn);
  }

  const api = session ? rentals(session) : null;

  return (
    <main className="desk">
      <header>
        <strong className="brand">Easy Route Auto · Rental desk</strong>
        <a href="/">Legacy vehicle explorer</a>
      </header>

      <section className="intro">
        <h1>Find a rental in Tempe</h1>
        <p className="badges">
          <span className={"badge " + (mode === "deterministic" ? "offline" : "live")}>
            Rental mode · {modeLabel(mode, model)}
          </span>
          <span className="badge">America/Phoenix</span>
          <span className="badge">Synthetic fleet · USD · pickup inclusive, return exclusive</span>
        </p>
      </section>

      <form
        className="panel discovery"
        onSubmit={(event) => {
          event.preventDefault();
          const message = String(new FormData(event.currentTarget).get("discovery"));
          void run(async () => {
            const reply = await api!.discover(message);
            show(reply);
            if (!reply.clarification && !reply.citations)
              setAnswer(reply.vehicles?.length ? "Results updated." : "No vehicles meet these requirements.");
          });
        }}
      >
        <label>
          Describe your rental
          <input
            name="discovery"
            placeholder="Seven-seat SUV in Tempe 2031-04-01 to 2031-04-08 under $950 monthly"
          />
        </label>
        <button disabled={busy || !session}>Find rentals</button>
      </form>

      <SavedSearch query={query} />

      <div className="layout">
        <SearchForm
          query={query}
          turn={turn}
          busy={busy || !session}
          onSearch={(next) =>
            void run(async () => {
              const reply = await api!.search(next);
              show(reply);
              setAnswer(reply.vehicles?.length ? "" : "No vehicles meet these requirements.");
            })
          }
        />

        <section className="conversation">
          <VehicleResults
            cars={cars}
            turn={turn}
            selected={selected}
            busy={busy}
            onSelect={(position) =>
              void run(async () => {
                const reply = await api!.reference(turn, "select", position);
                setAnswer("Selected " + reply.selection!.name);
              })
            }
            onQuote={(position) =>
              void run(async () => {
                await api!.reference(turn, "quote", position);
              })
            }
          />

          {turn && (
            <form
              className="ask"
              onSubmit={(event) => {
                event.preventDefault();
                const message = String(new FormData(event.currentTarget).get("message"));
                void run(async () => show(await api!.ask(turn, message)));
              }}
            >
              <label>
                Ask about these results
                <input name="message" placeholder="Compare the first two" required />
              </label>
              <button disabled={busy}>Ask</button>
            </form>
          )}

          <p aria-live="polite" className="answer">
            {answer}
          </p>
          {decisions.length > 0 && (
            <ul className="decisions" aria-label="Server decisions">
              {decisions.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
          <p role="alert" className="error">
            {error}
          </p>
        </section>
      </div>

      <button
        className="secondary"
        disabled={busy || !session}
        onClick={() =>
          void run(async () => {
            await api!.clearChat();
            setDecisions([]);
            setAnswer("Chat cleared. Your rental records remain available.");
          })
        }
      >
        Clear chat history
      </button>

      <RecordList
        records={records}
        busy={busy}
        onAccept={(record) =>
          void run(async () => {
            await api!.submit(record);
          })
        }
        onExtend={(record, end) =>
          void run(async () => {
            await api!.extend(record, end);
          })
        }
      />

      <StaffPanel busy={busy} run={run} notify={setError} />
    </main>
  );
}
