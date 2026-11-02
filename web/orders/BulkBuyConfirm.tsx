import { useState } from "react";
import { Order, createLabelBatch } from "@/lib/api";
import { Price } from "@/components/Price";

export type Quote = { rateId: string; carrier: string; service: string; price: string };

type Props = {
  orders: Order[];
  quotes: Record<string, Quote>;
  onQueued: (batchId: string) => void;
  onCancel: () => void;
};

// Sums money as integer cents so the total matches the per-order prices exactly.
function total(prices: string[]): string {
  const cents = prices.reduce((sum, p) => {
    const [whole, frac = ""] = p.split(".");
    return sum + Number(whole) * 100 + Number((frac + "00").slice(0, 2));
  }, 0);
  return `${Math.floor(cents / 100)}.${String(cents % 100).padStart(2, "0")}`;
}

// The merchant sees every order and its price, and the total, before anything is bought (ADR 0003).
// If a quote expires or changes while the batch runs, that order isn't bought; it comes back for approval.
export function BulkBuyConfirm({ orders, quotes, onQueued, onCancel }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const prices = orders.map((o) => quotes[o.id].price);

  async function confirm() {
    setBusy(true);
    try {
      const { id } = await createLabelBatch(
        orders.map((o) => ({ orderId: o.id, rateId: quotes[o.id].rateId, shownPrice: quotes[o.id].price })),
      );
      onQueued(id);
    } catch (e) {
      // 409: nothing was bought. The message says why, including labels left this month.
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div role="dialog" className="modal">
      <h2>
        Buy {orders.length} {orders.length === 1 ? "label" : "labels"}
      </h2>
      <table className="confirm-orders">
        <tbody>
          {orders.map((o) => (
            <tr key={o.id}>
              <td>#{o.shopifyId}</td>
              <td>{o.customer}</td>
              <td>
                {quotes[o.id].carrier.toUpperCase()} {quotes[o.id].service}
              </td>
              <td>
                <Price value={quotes[o.id].price} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">
        Orders that already have a label are skipped; you can reprint those. If a price changes before we get to an
        order, we won't buy it until you approve the new price.
      </p>
      {error && <p className="error">{error}</p>}
      <button className="link" onClick={onCancel} disabled={busy}>
        Cancel
      </button>
      <button disabled={busy} onClick={confirm}>
        Buy {orders.length} for <Price value={total(prices)} />
      </button>
    </div>
  );
}
