import { FormEvent, useState } from "react";
import { askAssistant, AssistantAnswer } from "@/lib/api";
import { Spinner } from "@/components/Spinner";

// A question box under the orders table. One question, one answer; nothing is kept between questions.
export function AssistantPanel() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AssistantAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setAnswer(await askAssistant(question));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="assistant">
      <form onSubmit={submit}>
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about your orders, labels or plan"
          aria-label="Ask the assistant"
        />
        <button type="submit" disabled={busy}>
          Ask
        </button>
      </form>
      {busy && <Spinner label="Thinking" />}
      {error && <p className="error">{error}</p>}
      {answer && answer.status === "completed" && <p className="answer">{answer.text}</p>}
      {answer && answer.status !== "completed" && (
        <p className="muted">No answer this time. Try again in a moment.</p>
      )}
    </section>
  );
}
