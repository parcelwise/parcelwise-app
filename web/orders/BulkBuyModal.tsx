import { useState } from "react";
import { BulkLineInput, BulkQuote, Order, buyLabelsBulk } from "@/lib/api";
import { Price } from "@/components/Price";
import { BulkJobStatus } from "./BulkJobStatus";

type Line = { order: Order; carrier: string; service: string; rateId: string; price: string };

// The confirm step lists every order it will buy with its price, then the total, before anything is bought
// (ADR 0003; Raven decisions 4f27c3207067 and 69b44f8e307c). On a plan that pays per label past its allowance the
// total includes that extra charge (Raven decision da4c0386cf19). The buy then runs in the background and this shows
// its progress and results (Raven decision 5e5e0741c202).
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
  const [jobId, setJobId] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    try {
      const input: BulkLineInput[] = lines.map((l) => ({ orderId: l.order.id, rateId: l.rateId, shownPrice: l.price }));
      setJobId((await buyLabelsBulk(batchId, input)).id);
    } catch (e) {
      // e.g. too many orders, past a Free plan's allowance, or a bulk buy is already running; nothing was bought.
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (jobId) {
    const shopifyIdOf = (orderId: string) => `#${lines.find((l) => l.order.id === orderId)?.order.shopifyId ?? orderId}`;
    return (
      <div role="dialog" className="modal">
        <BulkJobStatus jobId={jobId} nameOf={shopifyIdOf} />
        <button onClick={onDone}>Close</button>
      </div>
    );
  }

  // Orders on a carrier bulk buy doesn't cover yet are skipped and named, and the rest are bought (Raven decision
  // af045e508e3d, Jordan Okafor).
  const skipped = new Set(quote.skipped);
  const buying = lines.filter((l) => !skipped.has(l.order.id));
  return (
    <div role="dialog" className="modal">
      <h2>Buy {buying.length} labels</h2>
      <table>
        <tbody>
          {buying.map((l) => (
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
      {skipped.size > 0 && (
        <p>
          Skipping {skipped.size} non-USPS {skipped.size === 1 ? "order" : "orders"}: bulk buy covers USPS only for now. Buy
          {skipped.size === 1 ? " its label" : " their labels"} from the order&apos;s row:{" "}
          {lines
            .filter((l) => skipped.has(l.order.id))
            .map((l) => `#${l.order.shopifyId}`)
            .join(", ")}
        </p>
      )}
      {error && <p className="error">{error}</p>}
      <button disabled={busy || buying.length === 0} onClick={confirm}>
        Buy {buying.length} labels for <Price value={quote.total} />
      </button>
    </div>
  );
}
