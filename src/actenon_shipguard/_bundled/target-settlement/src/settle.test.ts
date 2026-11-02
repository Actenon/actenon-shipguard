import { expect, test } from 'vitest';
import { allocate, formatPence } from './settle';

test('splits an even total across four parties', () => {
  expect(allocate(100, 4)).toEqual([25, 25, 25, 25]);
});

test('splits an even total across two parties', () => {
  expect(allocate(100, 2)).toEqual([50, 50]);
});

test('a single party receives the whole total', () => {
  expect(allocate(50, 1)).toEqual([50]);
});

test('formats pence as pounds', () => {
  expect(formatPence(1234)).toBe('£12.34');
});
