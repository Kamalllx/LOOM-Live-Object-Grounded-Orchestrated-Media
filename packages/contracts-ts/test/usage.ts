// Compile-time check that the generated types are usable the way the player will use them.
import type { PlayerQuizItem, VerifiedCut } from "../src/index";

export function questionCount(cut: VerifiedCut): number {
  return cut.quiz?.length ?? 0;
}

export const sample: PlayerQuizItem = {
  question_id: "q_c04_b_1",
  stem: "What two products form when an acid neutralizes a base?",
  options: ["Salt and water", "Gas and heat", "Acid and oxygen", "Only water"],
};

// @ts-expect-error - the player quiz item carries no answer (B9): adding one must not type-check.
export const leaked: PlayerQuizItem = { ...sample, answer_index: 0 };
