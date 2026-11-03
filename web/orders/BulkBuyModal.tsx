import { useState } from "react";
import { BulkLineInput, BulkOutcome, BulkQuote, Order, buyLabelsBulk } from "@/lib/api";
import { Price } from "@/components/Price";

type Line = { order: Order; carrier: string; service: string; rateId: string; price: string };

const STATUS_TEXT: Record<BulkOutcome["status"], string> = {
  bought: "Bought",
  reprint: "Already has a label",
  stale: "Not bought",
  failed: "Not bought",
};

// The confirm step lists every order it will buy with its price, then the total, before anything is bought
// (ADR 0003; Raven decisions 4f27c3207067 and 69b44f8e307c). On a plan that pays per label past its allowance the
// total includes that extra charge (Raven decision da4c0386cf19). Afterwards it lists what bought and what didn't.
export function BulkBuyModal({
  batchId,
  lines,
  quote,
  onDone,
}: {
  batchId: string;
  lines: Line[];
  quote: BulkQuote;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [outcomes, setOutcomes] = useState<BulkOutcome[] | null>(null);

  async function confirm() {
    setBusy(true);
    try {
      const input: BulkLineInput[] = lines.map((l) => ({ orderId: l.order.id, rateId: l.rateId, shownPrice: l.price }));
      setOutcomes(await buyLabelsBulk(batchId, input));
    } catch (e) {
      // e.g. too many orders, a carrier bulk buy doesn't cover yet, or past a Free plan's allowance; nothing was bought.
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (outcomes) {
    const bought = outcomes.filter((o) => o.status === "bought").length;
    return (
      <div role="dialog" className="modal">
        <h2>
          Bought {bought} of {outcomes.length} labels
        </h2>
        <ul>
          {outcomes
            .filter((o) => o.status !== "bought")
            .map((o) => (
              <li key={o.orderId}>
                {lines.find((l) => l.order.id === o.orderId)?.order.shopifyId}: {STATUS_TEXT[o.status]}. {o.reason}
              </li>
            ))}
        </ul>
        <button onClick={onDone}>Done</button>
      </div>
    );
  }

  return (
    <div role="dialog" className="modal">
      <h2>Buy {lines.length} labels</h2>
      <table>
        <tbody>
          {lines.map((l) => (
            <tr key={l.order.id}>
              <td>#{l.order.shopifyId}</td>
              <td>
                {l.carrier.toUpperCase()} {l.service}
              </td>
              <td>
                <Price value={l.price} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {quote.labelsPastAllowance > 0 && (
        <p>
          {quote.labelsPastAllowance} of these go past your plan&apos;s monthly labels: <Price value={quote.extraCharge} />{" "}
          extra on your next invoice.
        </p>
      )}
      {error && <p className="error">{error}</p>}
      <button disabled={busy} onClick={confirm}>
        Buy {lines.length} labels for <Price value={quote.total} />
      </button>
    </div>
  );
}
