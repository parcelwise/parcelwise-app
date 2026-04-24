import { useState } from "react";
import { Order, buyLabel } from "@/lib/api";
import { Price } from "@/components/Price";

type Quote = { rateId: string; carrier: string; service: string; price: string };

// The merchant always sees the price before we buy. The server refuses a purchase at any other price.
export function BuyLabelModal({ order, quote, onDone }: { order: Order; quote: Quote; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function confirm() {
    setBusy(true);
    try {
      await buyLabel(order.id, quote.rateId, quote.price);
      onDone();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div role="dialog" className="modal">
      <h2>Label for #{order.shopifyId}</h2>
      <p>
        {quote.carrier.toUpperCase()} {quote.service} · <Price value={quote.price} />
      </p>
      {error && <p className="error">{error}</p>}
      <button disabled={busy} onClick={confirm}>
        Buy for <Price value={quote.price} />
      </button>
    </div>
  );
}
