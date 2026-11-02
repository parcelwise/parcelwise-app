import { useEffect, useState } from "react";
import { BatchOrder, LabelBatch, getLabelBatch } from "@/lib/api";
import { Spinner } from "@/components/Spinner";

type Props = {
  batchId: string;
  // Re-quote these orders, show the merchant the new prices, and call retryLabelBatch with what they approve.
  onRetry: (orderIds: string[]) => void;
  // Orders the carrier didn't answer for: call retryLabelBatch with these as they are, at the price already approved.
  onRetryAtSamePrice: (orders: BatchOrder[]) => void;
  onReprint: (orderIds: string[]) => void;
};

const POLL_MS = 3000;

// Progress of a batch. Labels that bought are kept; anything that didn't is listed with what to do next.
export function BatchResults({ batchId, onRetry, onRetryAtSamePrice, onReprint }: Props) {
  const [batch, setBatch] = useState<LabelBatch | null>(null);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      const next = await getLabelBatch(batchId);
      if (stopped) return;
      setBatch(next);
      if (!next.done) timer = setTimeout(poll, POLL_MS);
    }
    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [batchId]);

  if (!batch) return <Spinner />;

  const by = (status: string) => batch.items.filter((i) => i.status === status);
  const bought = by("bought");
  const queued = by("queued");
  const labeled = by("already_labeled");
  const requote = by("needs_requote");
  // Timed-out orders are retried at their original price (Priya Shah, Raven e270d6d52253).
  const timedOut = by("failed").filter((i) => i.timed_out);
  const failed = by("failed").filter((i) => !i.timed_out);
  const dropped = by("no_longer_unfulfilled");

  return (
    <section className="batch-results">
      <h2>
        {bought.length} of {batch.items.length} labels bought
        {queued.length > 0 && (
          <>
            {" "}
            · {queued.length} to go <Spinner />
          </>
        )}
      </h2>
      {dropped.length > 0 && (
        <>
          <p>{dropped.length} were fulfilled or cancelled after you selected them, so we left them out.</p>
          <ul className="dropped">
            {dropped.map((i) => (
              <li key={i.order_id}>{i.order_id}</li>
            ))}
          </ul>
        </>
      )}
      {labeled.length > 0 && (
        <p>
          {labeled.length} already had a label, so we didn't buy another.{" "}
          <button className="link" onClick={() => onReprint(labeled.map((i) => i.order_id))}>
            Reprint them
          </button>
        </p>
      )}
      {requote.length > 0 && (
        <p>
          {requote.length} changed price before we bought them.{" "}
          <button className="link" onClick={() => onRetry(requote.map((i) => i.order_id))}>
            Review new prices
          </button>
        </p>
      )}
      {timedOut.length > 0 && (
        <p>
          The carrier didn't answer for {timedOut.length}. Trying again won't buy a second label.{" "}
          <button
            className="link"
            onClick={() =>
              onRetryAtSamePrice(timedOut.map((i) => ({ orderId: i.order_id, rateId: i.rate_id, shownPrice: i.price })))
            }
          >
            Try again at the same price
          </button>
        </p>
      )}
      {failed.length > 0 && (
        <>
          <p>
            {failed.length} couldn't be bought.{" "}
            <button className="link" onClick={() => onRetry(failed.map((i) => i.order_id))}>
              Try again
            </button>
          </p>
          <ul className="errors">
            {failed.map((i) => (
              <li key={i.order_id}>
                {i.order_id}: {i.error}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
