import { Order } from "@/lib/api";
import { age } from "@/lib/time";

type Props = {
  order: Order;
  selected: boolean;
  inBulkBuy: boolean;
  onSelect: (order: Order, selected: boolean) => void;
  onBuyLabel: (order: Order) => void;
};

export function OrderRow({ order, selected, inBulkBuy, onSelect, onBuyLabel }: Props) {
  return (
    <tr>
      <td>
        <input
          type="checkbox"
          aria-label={`Select order #${order.shopifyId}`}
          checked={selected}
          onChange={(e) => onSelect(order, e.target.checked)}
        />
      </td>
      <td>#{order.shopifyId}</td>
      <td>{order.customer}</td>
      <td>
        {order.quantity} × {order.sku}
      </td>
      <td>{(order.weightOz / 16).toFixed(1)} lb</td>
      <td className="muted">{age(order.createdAt)}</td>
      <td>
        {/* Blocked while a running bulk buy will buy this order's label (Raven decision 55ebbf4c3071). */}
        <button disabled={inBulkBuy} onClick={() => onBuyLabel(order)}>
          {inBulkBuy ? "In a bulk buy" : "Buy label"}
        </button>
      </td>
    </tr>
  );
}
