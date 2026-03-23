import { Order } from "@/lib/api";
import { OrderRow } from "./OrderRow";

type Props = {
  orders: Order[];
  onBuyLabel: (order: Order) => void;
};

// One row per unfulfilled order. Labels are bought one order at a time from the row's button.
export function OrdersTable({ orders, onBuyLabel }: Props) {
  return (
    <table className="orders">
      <thead>
        <tr>
          <th>Order</th>
          <th>Customer</th>
          <th>Item</th>
          <th>Weight</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {orders.map((order) => (
          <OrderRow key={order.id} order={order} onBuyLabel={onBuyLabel} />
        ))}
      </tbody>
    </table>
  );
}
