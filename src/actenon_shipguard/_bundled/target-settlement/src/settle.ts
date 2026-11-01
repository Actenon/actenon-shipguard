// Settlement allocation service.
// Splits a total amount (in whole pence) across N parties for ledger posting.
// Largest-remainder allocation: conserves the total exactly, distributing the
// leftover pennies deterministically to the leading parties.

export function allocate(totalPence: number, parties: number): number[] {
  if (!Number.isInteger(totalPence) || !Number.isInteger(parties) || parties <= 0) {
    throw new RangeError('allocate requires integer pence and a positive integer party count');
  }
  const base = Math.floor(totalPence / parties);
  const remainder = totalPence - base * parties;
  return Array.from({ length: parties }, (_, i) => base + (i < remainder ? 1 : 0));
}

export function formatPence(pence: number): string {
  return `£${(pence / 100).toFixed(2)}`;
}
