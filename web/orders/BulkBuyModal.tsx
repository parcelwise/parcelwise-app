import { useState } from "react";
import { buyLabels } from "@/lib/api";
import { Price } from "@/components/Price";

type Quote = { orderId: string; shopifyId: number; rateId: string; carrier: string; service: string; price: string };

// The merchant sees every order and its price before we buy, same as a single label. Orders whose price changes
// while the batch runs are skipped, not bought, and come back here with their new price.
export function BulkBuyModal({ quotes, onDone }: { quotes: Quote[]; onDone: (batchId: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const total = quotes.reduce((sum, q) => sum + Math.round(Number(q.price) * 100), 0) / 100;

  async function confirm() {
    setBusy(true);
    try {
      const { batchId } = await buyLabels(
        quotes.map((q) => ({ orderId: q.orderId, rateId: q.rateId, shownPrice: q.price })),
      );
      onDone(batchId);
    } catch (e) {
      // 402: over this month's labels, nothing was bought. The message says how many are left.
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div role="dialog" className="modal">
      <h2>Labels for {quotes.length} orders</h2>
      <table className="quotes">
        <tbody>
          {quotes.map((q) => (
            <tr key={q.orderId}>
              <td>#{q.shopifyId}</td>
              <td>
                {q.carrier.toUpperCase()} {q.service}
              </td>
              <td>
                <Price value={q.price} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {error && <p className="error">{error}</p>}
      <button disabled={busy} onClick={confirm}>
        Buy {quotes.length} labels for <Price value={total.toFixed(2)} />
      </button>
    </div>
  );
}
