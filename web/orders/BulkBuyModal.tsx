import { useState } from "react";
import useSWR from "swr";
import { BulkQuote, Order, createBulkBatch, getBulkBatch } from "@/lib/api";
import { Price } from "@/components/Price";
import { MAX_BULK_ORDERS, totalPrice } from "./bulk";

type Props = {
  orders: Order[];
  quotes: BulkQuote[]; // the rate and price shown for each order; the server buys at exactly these or skips
  matchingTotal: number;
  onDone: () => void;
};

// The merchant sees every order, its price and the total before anything is bought. Orders that already have a
// label, went stale or changed price are skipped and listed afterwards; nothing is ever bought at an unseen price.
export function BulkBuyModal({ orders, quotes, matchingTotal, onDone }: Props) {
  const [batchId, setBatchId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const priceOf = new Map(quotes.map((q) => [q.orderId, q.price]));

  const { data: progress } = useSWR(
    batchId === null ? null : ["bulk", batchId],
    () => getBulkBatch(batchId as number),
    { refreshInterval: (latest) => (latest?.status === "done" ? 0 : 3000) },
  );

  async function confirm() {
    setBusy(true);
    try {
      const created = await createBulkBatch(quotes);
      setBatchId(created.batchId);
    } catch (e) {
      // 4xx explains why nothing was bought: too many orders, not enough labels left this month, not enabled.
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (batchId !== null) {
    return (
      <div role="dialog" className="modal">
        <h2>Buying {orders.length} labels</h2>
        {progress ? (
          <>
            <p>
              {progress.counts.bought} bought · {progress.counts.skipped} skipped · {progress.counts.pending} to go
            </p>
            <ul>
              {progress.items
                .filter((i) => i.status === "skipped")
                .map((i) => (
                  <li key={i.orderId}>
                    #{orders.find((o) => o.id === i.orderId)?.shopifyId ?? i.orderId}: not bought, {i.reason}
                  </li>
                ))}
            </ul>
          </>
        ) : (
          <p>Starting…</p>
        )}
        {progress?.status === "done" && <button onClick={onDone}>Done</button>}
      </div>
    );
  }

  return (
    <div role="dialog" className="modal">
      <h2>Buy {orders.length} labels</h2>
      {matchingTotal > MAX_BULK_ORDERS && (
        <p className="muted">
          You have {matchingTotal} matching orders. Labels cost real money, so bulk buying is limited to{" "}
          {MAX_BULK_ORDERS} orders at a time; buy these first, then come back for the rest.
        </p>
      )}
      <ul>
        {orders.map((o) => (
          <li key={o.id}>
            #{o.shopifyId} · {o.customer} · <Price value={priceOf.get(o.id) ?? "0"} />
          </li>
        ))}
      </ul>
      <p>
        Total <Price value={totalPrice(quotes.map((q) => q.price))} />
      </p>
      {error && <p className="error">{error}</p>}
      <button disabled={busy} onClick={confirm}>
        Buy {orders.length} labels for <Price value={totalPrice(quotes.map((q) => q.price))} />
      </button>
    </div>
  );
}
