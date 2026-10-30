import { useEffect, useState } from "react";
import { LabelBatch, Order, createLabelBatch, getLabelBatch, retryLabelBatch } from "@/lib/api";
import { Price } from "@/components/Price";

type Quote = { rateId: string; carrier: string; service: string; price: string };

type Props = {
  orders: Order[];
  quotes: Record<string, Quote>;
  // Fresh quotes for these orders, for when a price went stale partway through.
  requote: (orderIds: string[]) => Promise<Record<string, Quote>>;
  onDone: () => void;
};

const POLL_MS = 2000;

// Prices are decimal strings; add them in cents so the total is exact.
function total(prices: string[]): string {
  const cents = prices.reduce((sum, p) => sum + Math.round(Number(p) * 100), 0);
  return (cents / 100).toFixed(2);
}

// The merchant sees every price and the total before anything is bought. The server buys one label at a time
// and stops at the first stale price; the rest come back here with new prices to confirm.
export function BulkBuyModal({ orders, quotes, requote, onDone }: Props) {
  const [batch, setBatch] = useState<LabelBatch | null>(null);
  const [newQuotes, setNewQuotes] = useState<Record<string, Quote> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const running = batch !== null && batch.status !== "done";
  const batchId = batch?.id;
  useEffect(() => {
    if (!running || batchId === undefined) return;
    const timer = setInterval(() => getLabelBatch(batchId).then(setBatch, (e) => setError(String(e))), POLL_MS);
    return () => clearInterval(timer);
  }, [running, batchId]);

  async function act(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      // 402 means the batch would go past this month's labels; the message says how many are left.
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const missing = orders.filter((o) => !quotes[o.id]);

  if (batch === null) {
    return (
      <div role="dialog" className="modal">
        <h2>Buy {orders.length} labels</h2>
        <ul className="bulk-prices">
          {orders.map((o) => (
            <li key={o.id}>
              #{o.shopifyId} ·{" "}
              {quotes[o.id] ? (
                <>
                  {quotes[o.id].carrier.toUpperCase()} {quotes[o.id].service} · <Price value={quotes[o.id].price} />
                </>
              ) : (
                "No price yet"
              )}
            </li>
          ))}
        </ul>
        {error && <p className="error">{error}</p>}
        <button
          disabled={busy || missing.length > 0}
          onClick={() =>
            act(async () => {
              const { id } = await createLabelBatch(
                orders.map((o) => ({ order_id: o.id, rate_id: quotes[o.id].rateId, shown_price: quotes[o.id].price })),
              );
              setBatch(await getLabelBatch(id));
            })
          }
        >
          Buy all for <Price value={total(orders.map((o) => quotes[o.id]?.price ?? "0"))} />
        </button>
      </div>
    );
  }

  const byStatus = (s: string) => batch.items.filter((i) => i.status === s);
  const bought = byStatus("bought");
  const failed = byStatus("failed");
  const stale = byStatus("stale");
  const number = (orderId: string) => orders.find((o) => o.id === orderId)?.shopifyId ?? orderId;

  return (
    <div role="dialog" className="modal">
      <h2>
        {running ? `Buying labels… ${bought.length} of ${batch.items.length}` : `${bought.length} labels bought`}
      </h2>
      {!running && failed.length > 0 && (
        <>
          <h3>{failed.length} failed</h3>
          <ul>
            {failed.map((i) => (
              <li key={i.orderId}>
                #{number(i.orderId)} · {i.error}
              </li>
            ))}
          </ul>
        </>
      )}
      {!running && stale.length > 0 && (
        <>
          <h3>{stale.length} not bought: the price changed or expired</h3>
          {newQuotes ? (
            <ul className="bulk-prices">
              {stale.map((i) => (
                <li key={i.orderId}>
                  #{number(i.orderId)} · <Price value={i.shownPrice} /> → <Price value={newQuotes[i.orderId].price} />
                </li>
              ))}
            </ul>
          ) : (
            <button
              disabled={busy}
              onClick={() => act(async () => setNewQuotes(await requote(stale.map((i) => i.orderId))))}
            >
              Get new prices
            </button>
          )}
        </>
      )}
      {error && <p className="error">{error}</p>}
      {!running && (failed.length > 0 || newQuotes) && (
        <button
          disabled={busy}
          onClick={() =>
            act(async () => {
              const requoted = newQuotes
                ? stale.map((i) => ({
                    order_id: i.orderId,
                    rate_id: newQuotes[i.orderId].rateId,
                    shown_price: newQuotes[i.orderId].price,
                  }))
                : [];
              await retryLabelBatch(batch.id, requoted);
              setNewQuotes(null);
              setBatch(await getLabelBatch(batch.id));
            })
          }
        >
          {newQuotes ? (
            <>
              {failed.length > 0 ? "Retry failed and buy" : "Buy"} the rest for{" "}
              <Price value={total(stale.map((i) => newQuotes[i.orderId].price))} />
            </>
          ) : (
            "Retry failed"
          )}
        </button>
      )}
      {!running && <button onClick={onDone}>Done</button>}
    </div>
  );
}
