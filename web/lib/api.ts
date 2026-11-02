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

// One order in a batch, at the price the merchant approved on the confirm screen.
export type BatchOrder = { orderId: string; rateId: string; shownPrice: string };

export type BatchItemStatus =
  | "queued"
  | "bought"
  | "already_labeled"
  | "needs_requote"
  | "failed"
  // Fulfilled or cancelled after the merchant selected it; dropped from the batch.
  | "no_longer_unfulfilled";

export type LabelBatch = {
  id: string;
  done: boolean;
  items: {
    order_id: string;
    status: BatchItemStatus;
    carrier: string;
    service: string;
    rate_id: string;
    price: string;
    tracking_number: string | null;
    error: string | null;
    // The carrier didn't answer. A retry keeps this price and rate; the server ignores any new one.
    timed_out: boolean;
  }[];
};

const batchBody = (orders: BatchOrder[]) =>
  JSON.stringify({
    orders: orders.map((o) => ({ order_id: o.orderId, rate_id: o.rateId, shown_price: o.shownPrice })),
  });

// Queues the batch. A 409 means nothing was bought (over the monthly allowance, too many orders, or unknown orders).
export const createLabelBatch = (orders: BatchOrder[]) =>
  call<{ id: string }>("/label-batches", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: batchBody(orders),
  });

export const getLabelBatch = (batchId: string) => call<LabelBatch>(`/label-batches/${batchId}`);

// Retry failed orders, or buy re-priced ones, at the fresh prices the merchant just approved.
export const retryLabelBatch = (batchId: string, orders: BatchOrder[]) =>
  call<void>(`/label-batches/${batchId}/retry`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: batchBody(orders),
  });

export const searchOrders = (q: string) => call<Order[]>(`/orders/search?q=${encodeURIComponent(q)}`);
