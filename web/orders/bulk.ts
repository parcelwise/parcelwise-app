// A batch holds at most 200 orders, so "select all matching" stops there too (Raven decision 86e92e31bc0d).
export const MAX_BULK_ORDERS = 200;

export function capSelection(ids: string[]): string[] {
  return ids.slice(0, MAX_BULK_ORDERS);
}

export function totalPrice(prices: string[]): string {
  // Cents as integers: money is never a float.
  const cents = prices.reduce((sum, p) => sum + Math.round(Number(p) * 100), 0);
  return (cents / 100).toFixed(2);
}
