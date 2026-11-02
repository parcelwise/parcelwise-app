import useSWR from "swr";
import { usageThisMonth } from "@/lib/api";
import { Price } from "@/components/Price";
import { Spinner } from "@/components/Spinner";

// What the month has used so far: labels and assistant answers against the plan's allowances. Answers are
// completed answers, not attempts. No estimated charge until merchants have seen a real invoice (Priya).
export function PlanUsage() {
  const { data, error } = useSWR("usage-this-month", usageThisMonth);
  if (error) return <p className="error">Could not load this month&apos;s usage.</p>;
  if (!data) return <Spinner label="Loading usage" />;
  const allowance = data.labelsAllowance;
  const answersAllowance = data.assistantAllowance;
  return (
    <dl className="plan-usage">
      <dt>Labels this month</dt>
      <dd>
        {data.labels}
        {allowance !== null ? ` of ${allowance}` : ""}
      </dd>
      <dt>Assistant answers this month</dt>
      <dd>
        {data.assistantAnswers}
        {answersAllowance !== null ? ` of ${answersAllowance}` : ""}
        {answersAllowance !== null && data.assistantPrice !== null ? (
          <p className="plan-usage-note">
            Answers past {answersAllowance} are <Price value={data.assistantPrice} /> each on your next invoice.
          </p>
        ) : null}
      </dd>
    </dl>
  );
}
