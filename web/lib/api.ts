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

export type BatchItem = {
  orderId: string;
  status: "queued" | "bought" | "stale" | "failed";
  shownPrice: string;
  trackingNumber: string;
  pdfUrl: string;
  error: string;
};
export type LabelBatch = { id: number; status: "queued" | "running" | "done"; items: BatchItem[] };
export type ConfirmedRate = { order_id: string; rate_id: string; shown_price: string };

// The server buys these one at a time in the order given, each at the price the merchant confirmed.
export const createLabelBatch = (items: ConfirmedRate[]) =>
  call<{ id: number }>("/labels/batches", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ items }),
  });

export const getLabelBatch = (id: number) => call<LabelBatch>(`/labels/batches/${id}`);

// Queues the failed items again, and the stale ones at the new prices in `requoted`.
export const retryLabelBatch = (id: number, requoted: ConfirmedRate[]) =>
  call<{ queued: number }>(`/labels/batches/${id}/retry`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ items: requoted }),
  });

export const searchOrders =(q: string) => call<Order[]>(`/orders/search?q=${encodeURIComponent(q)}`);
