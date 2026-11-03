import useSWR from "swr";
import { usageThisMonth } from "@/lib/api";
import { Spinner } from "@/components/Spinner";

// What the month has used so far: labels and assistant answers, each against the plan's allowance.
export function PlanUsage() {
  const { data, error } = useSWR("usage-this-month", usageThisMonth);
  if (error) return <p className="error">Could not load this month&apos;s usage.</p>;
  if (!data) return <Spinner label="Loading usage" />;
  const allowance = data.labelsAllowance;
  const assistantAllowance = data.assistantAllowance;
  return (
    <dl className="plan-usage">
      <dt>Labels this month</dt>
      <dd>
        {data.labels}
        {allowance !== null ? ` of ${allowance}` : ""}
      </dd>
      <dt>Assistant answers this month</dt>
      <dd>
        {data.assistant}
        {assistantAllowance !== null ? ` of ${assistantAllowance}` : ""}
      </dd>
    </dl>
  );
}
