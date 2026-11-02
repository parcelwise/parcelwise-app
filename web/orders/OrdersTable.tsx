import { Order } from "@/lib/api";
import { BULK_LABEL_BUYING } from "@/lib/features";
import { OrderRow } from "./OrderRow";

type Props = {
  orders: Order[];
  onBuyLabel: (order: Order) => void;
  // Bulk selection: a checkbox per row, "select all on this page", and "select all N matching".
  selectedIds: Set<string>;
  onSelectionChange: (ids: Set<string>) => void;
  matchingCount: number;
  onSelectAllMatching: () => void;
  onBuySelected: () => void;
};

// One row per unfulfilled order. Buy one label from the row's button, or select orders and buy them together.
export function OrdersTable({
  orders,
  onBuyLabel,
  selectedIds,
  onSelectionChange,
  matchingCount,
  onSelectAllMatching,
  onBuySelected,
  bulk = BULK_LABEL_BUYING,
}: Props & { bulk?: boolean }) {
  if (orders.length === 0) {
    return <p className="empty">No unfulfilled orders. New Shopify orders show up here within a minute.</p>;
  }

  const allOnPage = orders.every((order) => selectedIds.has(order.id));

  function toggle(order: Order) {
    const next = new Set(selectedIds);
    if (next.has(order.id)) next.delete(order.id);
    else next.add(order.id);
    onSelectionChange(next);
  }

  function togglePage() {
    const next = new Set(selectedIds);
    for (const order of orders) {
      if (allOnPage) next.delete(order.id);
      else next.add(order.id);
    }
    onSelectionChange(next);
  }

  return (
    <>
      {bulk && selectedIds.size > 0 && (
        <div className="bulk-bar" role="region" aria-label="Selected orders">
          <span>{selectedIds.size} selected</span>
          {allOnPage && selectedIds.size < matchingCount && (
            <button className="link" onClick={onSelectAllMatching}>
              Select all {matchingCount} matching
            </button>
          )}
          <button onClick={onBuySelected}>Buy {selectedIds.size} labels</button>
          <button className="link" onClick={() => onSelectionChange(new Set())}>
            Clear
          </button>
        </div>
      )}
      <table className="orders">
        <thead>
          <tr>
            {bulk && (
              <th>
                <input
                  type="checkbox"
                  aria-label="Select all on this page"
                  checked={allOnPage}
                  onChange={togglePage}
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
              selected={selectedIds.has(order.id)}
              onToggle={bulk ? toggle : undefined}
              onBuyLabel={onBuyLabel}
            />
          ))}
        </tbody>
      </table>
    </>
  );
}
