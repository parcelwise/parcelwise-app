import { useState } from "react";
import { BulkResult, Order, buyLabelsBulk } from "@/lib/api";
import { Price } from "@/components/Price";

export type BulkQuote = { rateId: string; price: string };

// Prices are decimal strings; add them in cents so the total never picks up float error.
const cents = (price: string) => Math.round(Number(price) * 100);
const total = (quotes: BulkQuote[]) => (quotes.reduce((sum, q) => sum + cents(q.price), 0) / 100).toFixed(2);

// Lists every order it will touch with its price and one total. Nothing is bought until the merchant confirms.
export function BulkBuyModal({
  orders,
  quotes,
  onDone,
}: {
  orders: Order[];
  quotes: Record<string, BulkQuote>;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [results, setResults] = useState<BulkResult[] | null>(null);
  const sum = total(orders.map((o) => quotes[o.id]));

  async function confirm() {
    setBusy(true);
    try {
      setResults(
        await buyLabelsBulk(orders.map((o) => ({ orderId: o.id, rateId: quotes[o.id].rateId, shownPrice: quotes[o.id].price }))),
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (results) {
    const by = (status: string) => results.filter((r) => r.status === status);
    return (
      <div role="dialog" className="modal">
        <h2>
          Bought {by("bought").length} of {results.length}
        </h2>
        {[...by("skipped"), ...by("failed")].map((r) => (
          <p key={r.orderId} className="error">
            #{orders.find((o) => o.id === r.orderId)?.shopifyId}: {r.status}, {r.reason}
          </p>
        ))}
        <button onClick={onDone}>Done</button>
      </div>
    );
  }

  return (
    <div role="dialog" className="modal">
      <h2>Buy {orders.length} labels</h2>
      <ul>
        {orders.map((o) => (
          <li key={o.id}>
            #{o.shopifyId} · {o.customer} · <Price value={quotes[o.id].price} />
          </li>
        ))}
      </ul>
      {error && <p className="error">{error}</p>}
      <button disabled={busy} onClick={confirm}>
        Buy {orders.length} labels for <Price value={sum} />
      </button>
    </div>
  );
}
