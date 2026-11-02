// Proportional settlement split — correct largest-remainder (Hamilton) apportionment.
// Conserves the total exactly; leftover pennies go to the largest fractional quotas,
// ties broken toward the lower index.

export function splitProportional(totalPence: number, weights: number[]): number[] {
  const sum = weights.reduce((a, b) => a + b, 0);
  if (!Number.isInteger(totalPence) || totalPence < 0 || sum <= 0 || weights.some((w) => w < 0)) {
    throw new RangeError('splitProportional requires a non-negative integer total and non-negative weights summing > 0');
  }
  const quotas = weights.map((w) => (totalPence * w) / sum);
  const shares = quotas.map((q) => Math.floor(q));
  const remainder = totalPence - shares.reduce((a, b) => a + b, 0);
  const order = quotas
    .map((q, i) => ({ i, frac: q - Math.floor(q) }))
    .sort((a, b) => (b.frac - a.frac) || (a.i - b.i));
  for (let k = 0; k < remainder; k++) shares[order[k].i] += 1;
  return shares;
}
