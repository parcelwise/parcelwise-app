import { Order } from "@/lib/api";
import { OrderRow } from "./OrderRow";

type Props = {
  orders: Order[];
  totalUnfulfilled: number;
  selectedIds: Set<string>;
  onToggle: (order: Order) => void;
  onSelectPage: (selected: boolean) => void;
  onSelectAll: () => void;
  onBuySelected: () => void;
  onBuyLabel: (order: Order) => void;
};

// One row per unfulfilled order. Buy one label from the row's button, or select orders (across pages) and buy
// them all at once.
export function OrdersTable({
  orders,
  totalUnfulfilled,
  selectedIds,
  onToggle,
  onSelectPage,
  onSelectAll,
  onBuySelected,
  onBuyLabel,
}: Props) {
  if (orders.length === 0) {
    return <p className="empty">No unfulfilled orders. New Shopify orders show up here within a minute.</p>;
  }
  const pageSelected = orders.every((order) => selectedIds.has(order.id));
  return (
    <>
      {selectedIds.size > 0 && (
        <div className="bulk-bar">
          <span>{selectedIds.size} selected</span>
          {selectedIds.size < totalUnfulfilled && (
            <button className="link" onClick={onSelectAll}>
              Select all {totalUnfulfilled} unfulfilled orders
            </button>
          )}
          <button onClick={onBuySelected}>Buy {selectedIds.size} labels</button>
        </div>
      )}
      <table className="orders">
        <thead>
          <tr>
            <th>
              <input
                type="checkbox"
                aria-label="Select every order on this page"
                checked={pageSelected}
                onChange={() => onSelectPage(!pageSelected)}
              />
            </th>
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
              selected={selectedIds.has(order.id)}
              onToggle={onToggle}
              onBuyLabel={onBuyLabel}
            />
          ))}
        </tbody>
      </table>
    </>
  );
}
