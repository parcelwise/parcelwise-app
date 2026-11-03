// Thin client for the merchant API. Every call goes through here so auth and errors stay in one place.
export type Order = {
  id: string;
  shopifyId: number;
  customer: string;
  sku: string;
  quantity: number;
  weightOz: number;
  status: "unfulfilled" | "fulfilled" | "cancelled";
  createdAt: string;
};

export type Label = { orderId: string; carrier: string; trackingNumber: string; price: string; pdfUrl: string };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { credentials: "include", ...init });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const listOrders = () => call<Order[]>("/orders");

export const buyLabel = (orderId: string, rateId: string, shownPrice: string) =>
  call<Label>(`/orders/${orderId}/label`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ rate_id: rateId, shown_price: shownPrice }),
  });

export type BulkLineInput = { orderId: string; rateId: string; shownPrice: string };

export type BulkQuote = { carrierTotal: string; labelsPastAllowance: number; extraCharge: string; total: string };

export type BulkOutcome = {
  orderId: string;
  status: "bought" | "reprint" | "stale" | "failed";
  label: Label | null;
  reason: string;
};

const bulkBody = (lines: BulkLineInput[]) =>
  lines.map((l) => ({ order_id: l.orderId, rate_id: l.rateId, shown_price: l.shownPrice }));

export const quoteBulk = (lines: BulkLineInput[]) =>
  call<BulkQuote>("/labels/bulk/quote", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ lines: bulkBody(lines) }),
  });

// A bulk buy runs in the background (Raven decision 5e5e0741c202): starting one returns the job, and the page reads
// it back until it is done. "pending" while it runs; "refused" means nothing was bought and `reason` says why.
export type BulkJob = {
  id: string;
  status: "pending" | "done" | "refused";
  outcomes: BulkOutcome[] | null;
  reason: string;
  count: number;
};

export const buyLabelsBulk = (batchId: string, lines: BulkLineInput[]) =>
  call<BulkJob>("/labels/bulk", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ batch_id: batchId, lines: bulkBody(lines) }),
  });

export const getBulkJob = (jobId: string) => call<BulkJob>(`/labels/bulk/${encodeURIComponent(jobId)}`);

export const latestBulkJob = () => call<BulkJob | null>("/labels/bulk/latest");

export const searchOrders = (q: string) => call<Order[]>(`/orders/search?q=${encodeURIComponent(q)}`);

export type AssistantAnswer = {
  requestId: string;
  question: string;
  text: string;
  status: "completed" | "failed" | "timed_out";
};

export const askAssistant = (question: string) =>
  call<AssistantAnswer>("/assistant/ask", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ question }),
  });

export type UsageThisMonth = { labels: number; assistant: number; labelsAllowance: number | null };

export const usageThisMonth = () => call<UsageThisMonth>("/usage");
