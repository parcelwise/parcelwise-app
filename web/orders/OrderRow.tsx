import { Order } from "@/lib/api";

export function OrderRow({ order, onBuyLabel }: { order: Order; onBuyLabel: (order: Order) => void }) {
  return (
    <tr>
      <td>#{order.shopifyId}</td>
      <td>{order.customer}</td>
      <td>
        {order.quantity} × {order.sku}
      </td>
      <td>{(order.weightOz / 16).toFixed(1)} lb</td>
      <td>
        <button onClick={() => onBuyLabel(order)}>Buy label</button>
      </td>
    </tr>
  );
}
