"use client";

import { useState } from "react";
import type { QuizQuestion } from "@/lib/types";

export interface QuizAnswer {
  concept_node_id: string;
  question: string;
  selected_index: number;
  correct: boolean;
}

interface Props {
  quiz: QuizQuestion[];
  onSubmit: (answers: QuizAnswer[]) => void;
}


export default function QuizPanel({ quiz, onSubmit }: Props) {
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const gradable = quiz.filter((q) => q.options && q.answer_index !== undefined);
  const answeredAll = gradable.every((q) => answers[quiz.indexOf(q)] !== undefined);

  function submit() {
    const result: QuizAnswer[] = gradable.map((q) => {
      const i = quiz.indexOf(q);
      const selected = answers[i];
      return {
        concept_node_id: q.concept_node_id,
        question: q.question,
        selected_index: selected,
        correct: selected === q.answer_index,
      };
    });
    onSubmit(result);
  }

  return (
    <section className="space-y-5 rounded-xl border border-quiz/40 bg-surface p-5">
      <div>
        <h2 className="font-display text-xl">Check what stuck</h2>
        <p className="text-sm text-muted">
          {gradable.length} question{gradable.length === 1 ? "" : "s"} from the concepts this cut
          covered. Answers update your mastery levels.
        </p>
      </div>

      <ol className="space-y-5">
        {quiz.map((q, i) => (
          <li key={`${q.concept_node_id}-${i}`} className="space-y-2">
            <p className="text-text">{q.question}</p>

            {q.options ? (
              <div className="grid gap-2 sm:grid-cols-2">
                {q.options.map((opt, oi) => {
                  const chosen = answers[i] === oi;
                  return (
                    <button
                      key={opt}
                      type="button"
                      onClick={() => setAnswers((a) => ({ ...a, [i]: oi }))}
                      aria-pressed={chosen}
                      className={`rounded-lg border px-3 py-2 text-left text-sm transition ${
                        chosen
                          ? "border-quiz bg-quiz/15 text-text"
                          : "border-line bg-raised text-muted hover:border-quiz/50 hover:text-text"
                      }`}
                    >
                      {opt}
                    </button>
                  );
                })}
              </div>
            ) : (
              <p className="text-xs text-muted">
                No options supplied for this question, so it isn&apos;t graded.
              </p>
            )}
          </li>
        ))}
      </ol>

      <button
        type="button"
        disabled={!answeredAll}
        onClick={submit}
        className="rounded-lg bg-quiz px-4 py-2 font-display text-base font-medium text-black disabled:cursor-not-allowed disabled:opacity-40"
      >
        Submit answers
      </button>
    </section>
  );
}
