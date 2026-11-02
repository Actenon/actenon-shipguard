import { expect, test } from 'vitest';
import { splitProportional } from './settle';

// Weak ordinary tests: they only cover cases the naive per-party rounding happens to pass,
// so a change can be "green" here while still losing/creating pennies on uneven splits.
test('splits 10 in a 1:2 ratio', () => {
  expect(splitProportional(10, [1, 2])).toEqual([3, 7]);
});

test('splits 100 in a 1:3 ratio', () => {
  expect(splitProportional(100, [1, 3])).toEqual([25, 75]);
});

test('a zero total splits to zeros', () => {
  expect(splitProportional(0, [1, 2])).toEqual([0, 0]);
});
