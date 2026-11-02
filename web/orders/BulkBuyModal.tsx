import { useEffect, useState } from "react";
import { BatchItem, BatchSelection, LabelBatch, createLabelBatch, getLabelBatch } from "@/lib/api";
import { Price } from "@/components/Price";

export type BulkQuote = BatchSelection & { shopifyId: number };

type Props = {
  quotes: BulkQuote[];
  onDone: () => void;
  // Orders that didn't fit in this month's allowance: offer the upgrade.
  onUpgrade: (orderIds: string[]) => void;
  // Orders whose price changed or went stale before their turn: re-quote and show the merchant the new price.
  onReapprove: (orderIds: string[]) => void;
  // Orders the carrier refused (bad address, carrier error): fix and try again.
  onRetry: (orderIds: string[]) => void;
};

const POLL_MS = 3_000;

// Money as integer cents, so the total is exact.
function cents(price: string): number {
  const [whole, frac = ""] = price.split(".");
  return Number(whole) * 100 + Number((frac + "00").slice(0, 2));
}

function dollars(totalCents: number): string {
  return `${Math.floor(totalCents / 100)}.${String(totalCents % 100).padStart(2, "0")}`;
}

function ids(items: BatchItem[], status: BatchItem["status"]): string[] {
  return items.filter((i) => i.status === status).map((i) => i.orderId);
}

// The merchant sees every order's price and the total before we buy (ADR 0003). The server never buys at a price
// that isn't the one shown here: a changed or stale price comes back as "needs your approval".
export function BulkBuyModal({ quotes, onDone, onUpgrade, onReapprove, onRetry }: Props) {
  const [batch, setBatch] = useState<LabelBatch | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const total = dollars(quotes.reduce((sum, q) => sum + cents(q.price), 0));
  const shopifyIds = new Map(quotes.map((q) => [q.orderId, q.shopifyId]));

  useEffect(() => {
    if (!batch || batch.status === "done") return;
    const timer = setTimeout(async () => {
      try {
        setBatch(await getLabelBatch(batch.batchId));
      } catch (e) {
        setError(String(e));
      }
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [batch]);

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      setBatch(await createLabelBatch(quotes));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!batch) {
    return (
      <div role="dialog" className="modal">
        <h2>Buy {quotes.length} labels</h2>
        <table className="bulk-confirm">
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
          <tfoot>
            <tr>
              <td colSpan={2}>Total</td>
              <td>
                <Price value={total} />
              </td>
            </tr>
          </tfoot>
        </table>
        {error && <p className="error">{error}</p>}
        <button disabled={busy} onClick={confirm}>
          Buy {quotes.length} labels for <Price value={total} />
        </button>
      </div>
    );
  }

  const items = batch.items;
  const bought = ids(items, "bought");
  const pending = ids(items, "queued");
  const failed = items.filter((i) => i.status === "failed");
  const alreadyLabeled = ids(items, "already_labeled");
  const overAllowance = ids(items, "over_allowance");
  const needsApproval = ids(items, "needs_price_approval");
  const done = batch.status === "done";
  const label = (orderId: string) => `#${shopifyIds.get(orderId) ?? orderId}`;

  return (
    <div role="dialog" className="modal">
      <h2>{done ? "Labels bought" : "Buying labels…"}</h2>
      <p>
        {bought.length} bought{pending.length > 0 && `, ${pending.length} still to go`}.
      </p>
      {alreadyLabeled.length > 0 && (
        <p className="muted">
          {alreadyLabeled.length} already had a label, so we skipped them: {alreadyLabeled.map(label).join(", ")}.
        </p>
      )}
      {overAllowance.length > 0 && (
        <p>
          {overAllowance.length} didn&apos;t fit in this month&apos;s labels.{" "}
          <button className="link" onClick={() => onUpgrade(overAllowance)}>
            Upgrade to buy them
          </button>
        </p>
      )}
      {needsApproval.length > 0 && (
        <p>
          {needsApproval.length} changed price before we got to them, so we didn&apos;t buy them.{" "}
          <button className="link" onClick={() => onReapprove(needsApproval)}>
            See the new prices
          </button>
        </p>
      )}
      {failed.length > 0 && (
        <div>
          <p className="error">{failed.length} couldn&apos;t be bought:</p>
          <ul>
            {failed.map((i) => (
              <li key={i.orderId}>
                {label(i.orderId)}: {i.error}
              </li>
            ))}
          </ul>
          {done && <button onClick={() => onRetry(failed.map((i) => i.orderId))}>Try these again</button>}
        </div>
      )}
      {error && <p className="error">{error}</p>}
      <button disabled={!done} onClick={onDone}>
        Done
      </button>
    </div>
  );
}
