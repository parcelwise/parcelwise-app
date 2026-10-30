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

export const listUnfulfilledOrderIds = () => call<string[]>("/orders/unfulfilled/ids");

// Each order carries the price the merchant saw. The server buys in the background and skips any order whose
// price changed; a 402 means the batch would go past this month's labels and nothing was bought.
export const buyLabels = (items: { orderId: string; rateId: string; shownPrice: string }[]) =>
  call<{ batchId: string }>("/labels/bulk", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      items: items.map((i) => ({ order_id: i.orderId, rate_id: i.rateId, shown_price: i.shownPrice })),
    }),
  });

export type BulkStatus = {
  status: "queued" | "running" | "done";
  bought: { order_id: string; tracking_number: string }[];
  stale: string[];
  failed: Record<string, string>;
  pending: number;
};

export const getBulkPurchase = (batchId: string) => call<BulkStatus>(`/labels/bulk/${batchId}`);

export const searchOrders =(q: string) => call<Order[]>(`/orders/search?q=${encodeURIComponent(q)}`);
