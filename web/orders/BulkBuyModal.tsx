import { useEffect, useState } from "react";
import { BulkStatus, buyLabels, getBulkPurchase } from "@/lib/api";
import { Price } from "@/components/Price";

type Quote = { orderId: string; shopifyId: number; rateId: string; carrier: string; service: string; price: string };

const POLL_MS = 3000;

// The merchant sees every order and its price before we buy, same as a single label. The batch runs in the label
// worker; orders whose price changed are skipped, not bought, and handed back to re-quote and confirm again.
export function BulkBuyModal({
  quotes,
  onRequote,
  onDone,
}: {
  quotes: Quote[];
  onRequote: (orderIds: string[]) => void;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [batchId, setBatchId] = useState("");
  const [status, setStatus] = useState<BulkStatus | null>(null);
  const total = quotes.reduce((sum, q) => sum + Math.round(Number(q.price) * 100), 0) / 100;
  const byId = new Map(quotes.map((q) => [q.orderId, q]));

  useEffect(() => {
    if (!batchId) return;
    let stopped = false;
    async function poll() {
      const next = await getBulkPurchase(batchId);
      if (stopped) return;
      setStatus(next);
      if (next.status !== "done") setTimeout(poll, POLL_MS);
    }
    poll().catch((e) => setError(String(e)));
    return () => {
      stopped = true;
    };
  }, [batchId]);

  async function confirm() {
    setBusy(true);
    try {
      const { batchId } = await buyLabels(
        quotes.map((q) => ({ orderId: q.orderId, rateId: q.rateId, shownPrice: q.price })),
      );
      setBatchId(batchId);
    } catch (e) {
      // 402: over this month's labels, nothing was bought. The message says how many are left.
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (batchId) {
    const failed = Object.entries(status?.failed ?? {});
    return (
      <div role="dialog" className="modal">
        <h2>
          {status?.status === "done" ? "Done" : "Buying"}: {status?.bought.length ?? 0} of {quotes.length} labels
        </h2>
        {status && status.status !== "done" && <p className="muted">{status.pending} still to buy.</p>}
        {failed.length > 0 && (
          <>
            <h3>No label bought</h3>
            <ul>
              {failed.map(([orderId, reason]) => (
                <li key={orderId}>
                  #{byId.get(orderId)?.shopifyId}: {reason}
                </li>
              ))}
            </ul>
          </>
        )}
        {status && status.stale.length > 0 && (
          <>
            <h3>Price changed, not bought</h3>
            <p>{status.stale.length} orders need a new quote before we buy.</p>
            <button onClick={() => onRequote(status.stale)}>See new prices</button>
          </>
        )}
        {error && <p className="error">{error}</p>}
        {status?.status === "done" && <button onClick={onDone}>Close</button>}
      </div>
    );
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
