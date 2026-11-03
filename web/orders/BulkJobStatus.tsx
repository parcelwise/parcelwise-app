import { useEffect, useState } from "react";
import { BulkJob, BulkOutcome, getBulkJob, latestBulkJob } from "@/lib/api";

const POLL_MS = 5000;

const STATUS_TEXT: Record<BulkOutcome["status"], string> = {
  bought: "Bought",
  reprint: "Already has a label",
  stale: "Not bought",
  failed: "Not bought",
};

// A bulk buy runs in the background, so the merchant can leave and come back to the results (Raven decision
// 5e5e0741c202, Ana Ruiz). Shows the given job, or the merchant's latest one, and reads it again until it is done.
// Afterwards it lists every order that wasn't bought and why (Raven decisions 69b44f8e307c and 73523ae6ecc8).
export function BulkJobStatus({
  jobId,
  nameOf = (orderId) => orderId,
  onDismiss,
}: {
  jobId?: string;
  nameOf?: (orderId: string) => string;
  onDismiss?: () => void;
}) {
  const [job, setJob] = useState<BulkJob | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function load() {
      try {
        const next = jobId ? await getBulkJob(jobId) : await latestBulkJob();
        if (stopped) return;
        setJob(next);
        if (next?.status === "pending") timer = setTimeout(load, POLL_MS);
      } catch (e) {
        if (!stopped) setError(String(e));
      }
    }
    load();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  if (error) return <p className="error">{error}</p>;
  if (!job) return null;

  if (job.status === "pending") {
    return (
      <div className="bulk-status" role="status">
        Buying {job.count} labels in the background. You can leave this page; the results will be here when you come
        back.
      </div>
    );
  }

  if (job.status === "refused") {
    return (
      <div className="bulk-status" role="status">
        {job.reason}
        {onDismiss && <button onClick={onDismiss}>Done</button>}
      </div>
    );
  }

  const outcomes = job.outcomes ?? [];
  const bought = outcomes.filter((o) => o.status === "bought").length;
  return (
    <div className="bulk-status" role="status">
      <h2>
        Bought {bought} of {outcomes.length} labels
      </h2>
      <ul>
        {outcomes
          .filter((o) => o.status !== "bought")
          .map((o) => (
            <li key={o.orderId}>
              {nameOf(o.orderId)}: {STATUS_TEXT[o.status]}. {o.reason}
            </li>
          ))}
      </ul>
      {onDismiss && <button onClick={onDismiss}>Done</button>}
    </div>
  );
}
