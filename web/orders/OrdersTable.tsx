import { Order } from "@/lib/api";
import { OrderRow } from "./OrderRow";

export type Selection = {
  selected: Set<string>;
  onToggle: (orderId: string) => void;
  onTogglePage: (checked: boolean) => void;
};

type Props = {
  orders: Order[];
  onBuyLabel: (order: Order) => void;
  selection?: Selection; // set only for merchants who have bulk label buying
};

// One row per unfulfilled order. Labels are bought from the row's button, or in bulk from the checkboxes.
export function OrdersTable({ orders, onBuyLabel, selection }: Props) {
  if (orders.length === 0) {
    return <p className="empty">No unfulfilled orders. New Shopify orders show up here within a minute.</p>;
  }
  const allOnPage = selection !== undefined && orders.every((o) => selection.selected.has(o.id));
  return (
    <table className="orders">
      <thead>
        <tr>
          {selection && (
            <th>
              <input
                type="checkbox"
                aria-label="Select all on this page"
                checked={allOnPage}
                onChange={(e) => selection.onTogglePage(e.target.checked)}
              />
            </th>
          )}
          <th>Order</th>
          <th>Customer</th>
          <th>Item</th>
          <th>Weight</th>
          <th>Waiting</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {orders.map((order) => (
          <OrderRow
            key={order.id}
            order={order}
            onBuyLabel={onBuyLabel}
            checked={selection?.selected.has(order.id)}
            onToggle={selection ? () => selection.onToggle(order.id) : undefined}
          />
        ))}
      </tbody>
    </table>
  );
}
