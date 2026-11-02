import { useEffect, useState } from "react";
import useSWR from "swr";
import { BulkPreview, BulkSelection, bulkStatus, previewBulk, startBulk } from "@/lib/api";
import { Price } from "@/components/Price";

type Props = {
  selections: BulkSelection[];
  onUpgrade: () => void;
  onDone: () => void;
};

// The merchant sees every order and its price before we buy anything (ADR 0003). Orders that already have a
// label are left out and listed; orders past the monthly allowance are listed with an upgrade offer.
export function BulkBuyModal({ selections, onUpgrade, onDone }: Props) {
  const [preview, setPreview] = useState<BulkPreview | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    previewBulk(selections).then(setPreview, (e) => setError(String(e)));
  }, [selections]);

  async function confirm() {
    setBusy(true);
    try {
      const started = await startBulk(selections);
      setPreview(started);
      setJobId(started.jobId);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (jobId !== null) return <BulkProgress jobId={jobId} selections={selections} onDone={onDone} />;

  const byId = new Map(selections.map((s) => [s.order.id, s]));
  const label = (id: string) => `#${byId.get(id)?.order.shopifyId ?? id}`;

  return (
    <div role="dialog" className="modal">
      <h2>Buy labels for {selections.length} orders</h2>
      {error && <p className="error">{error}</p>}
      {!preview ? (
        <p className="muted">Checking prices and your monthly allowance…</p>
      ) : (
        <>
          <table className="bulk-confirm">
            <tbody>
              {preview.toBuy.map((id) => {
                const quote = byId.get(id)?.quote;
                return (
                  <tr key={id}>
                    <td>{label(id)}</td>
                    <td>
                      {quote?.carrier.toUpperCase()} {quote?.service}
                    </td>
                    <td>{quote && <Price value={quote.price} />}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {preview.alreadyLabelled.length > 0 && (
            <p className="muted">
              Already labelled, so we won&apos;t buy another: {preview.alreadyLabelled.map(label).join(", ")}. Void
              the old label first if you need a new one.
            </p>
          )}

          {preview.overAllowance.length > 0 && (
            <p className="warning">
              You have {preview.remaining} labels left this month, so we&apos;ll buy the first{" "}
              {preview.toBuy.length}. Not bought: {preview.overAllowance.map(label).join(", ")}.{" "}
              <button className="link" onClick={onUpgrade}>
                Upgrade to buy the rest
              </button>
            </p>
          )}

          <button disabled={busy || preview.toBuy.length === 0} onClick={confirm}>
            Buy {preview.toBuy.length} labels for <Price value={preview.total} />
          </button>
        </>
      )}
    </div>
  );
}

function BulkProgress({ jobId, selections, onDone }: { jobId: number; selections: BulkSelection[]; onDone: () => void }) {
  const { data } = useSWR(["bulk", jobId], () => bulkStatus(jobId), {
    refreshInterval: (latest) => (latest?.status === "done" ? 0 : 2000),
  });
  const byId = new Map(selections.map((s) => [s.order.id, s.order.shopifyId]));
  const label = (id: string) => `#${byId.get(id) ?? id}`;

  if (!data) return <div className="modal">Starting…</div>;
  const { counts } = data;
  const total = counts.pending + counts.bought + counts.failed + counts.needs_approval + counts.already_labelled;

  return (
    <div role="dialog" className="modal">
      <h2>{data.status === "done" ? "Labels bought" : "Buying labels…"}</h2>
      <p>
        {counts.bought} of {total} bought
        {data.status !== "done" && " — you can close this; we'll keep going."}
      </p>
      {data.needsApproval.length > 0 && (
        <p className="warning">
          The price changed or the quote expired for {data.needsApproval.map(label).join(", ")}. We didn&apos;t buy
          these. Select them again to see the new price.
        </p>
      )}
      {data.alreadyLabelled.length > 0 && (
        <p className="muted">
          {data.alreadyLabelled.map(label).join(", ")} got a label some other way while this was running, so we
          didn&apos;t buy another.
        </p>
      )}
      {data.failed.length > 0 && (
        <div className="error">
          <p>These failed and weren&apos;t bought:</p>
          <ul>
            {data.failed.map((f) => (
              <li key={f.orderId}>
                {label(f.orderId)}: {f.error}
              </li>
            ))}
          </ul>
        </div>
      )}
      <button onClick={onDone}>{data.status === "done" ? "Done" : "Close"}</button>
    </div>
  );
}
