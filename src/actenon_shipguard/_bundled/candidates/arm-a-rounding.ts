// Settlement allocation service.
// Splits a total amount (in whole pence) across N parties for ledger posting.

export function allocate(totalPence: number, parties: number): number[] {
  const each = Math.round(totalPence / parties);
  return Array.from({ length: parties }, () => each);
}

export function formatPence(pence: number): string {
  return `£${(pence / 100).toFixed(2)}`;
}
