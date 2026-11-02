// Proportional settlement split.
// Splits a whole-pence total across parties in proportion to integer weights.
// BUG: naive per-party rounding loses or creates pennies (shares need not sum to the total).

export function splitProportional(totalPence: number, weights: number[]): number[] {
  const sum = weights.reduce((a, b) => a + b, 0);
  return weights.map((w) => Math.round((totalPence * w) / sum));
}
