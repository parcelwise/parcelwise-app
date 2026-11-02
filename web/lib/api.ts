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

export const searchOrders = (q: string) => call<Order[]>(`/orders/search?q=${encodeURIComponent(q)}`);

// A carrier quote as the merchant saw it. Quotes are good for ten minutes.
export type Quote = { rateId: string; carrier: string; service: string; price: string; quotedAt: string };

export type BulkSelection = { order: Order; quote: Quote };

// Order ids, in the order the merchant saw them.
export type BulkPreview = {
  toBuy: string[];
  alreadyLabelled: string[];
  overAllowance: string[];
  remaining: number | null;
  total: string;
};

export type BulkJobStatus = {
  status: "queued" | "running" | "done";
  counts: { pending: number; bought: number; failed: number; needs_approval: number };
  failed: { orderId: string; error: string }[];
  needsApproval: string[];
};

const bulkBody = (selections: BulkSelection[]) =>
  JSON.stringify({
    selections: selections.map(({ order, quote }) => ({
      order_id: order.id,
      carrier: quote.carrier,
      service: quote.service,
      rate_id: quote.rateId,
      quoted_at: quote.quotedAt,
      shown_price: quote.price,
    })),
  });

export const previewBulk = (selections: BulkSelection[]) =>
  call<BulkPreview>("/labels/bulk/preview", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: bulkBody(selections),
  });

export const startBulk = (selections: BulkSelection[]) =>
  call<BulkPreview & { jobId: number }>("/labels/bulk", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: bulkBody(selections),
  });

export const bulkStatus = (jobId: number) => call<BulkJobStatus>(`/labels/bulk/${jobId}`);
