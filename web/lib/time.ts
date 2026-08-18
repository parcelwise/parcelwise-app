// "3h", "2d": how long an order has waited. Merchants sort their morning by this.
export function age(iso: string, now: Date = new Date()): string {
  const hours = Math.floor((now.getTime() - new Date(iso).getTime()) / 3_600_000);
  return hours < 24 ? `${hours}h` : `${Math.floor(hours / 24)}d`;
}
