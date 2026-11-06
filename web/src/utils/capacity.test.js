import assert from 'node:assert/strict'
import test from 'node:test'
import { formatCapacity } from './capacity.js'

const DRIVE = 4000787030016
const LABEL = 4_000_000_000_000

test('GiB uses 1024 and TiB suffix', () => {
  assert.equal(formatCapacity(DRIVE, { unit: 'gib', decimals: 1 }), '3.6 TiB')
  assert.equal(formatCapacity(64 * 1024 ** 3, { unit: 'gib', decimals: 1 }), '64.0 GiB')
  assert.equal(formatCapacity(18 * 1024 ** 4, { unit: 'gib', decimals: 0 }), '18 TiB')
})

test('GB uses 1000', () => {
  assert.equal(formatCapacity(DRIVE, { unit: 'gb', decimals: 2 }), '4.00 TB')
  assert.equal(formatCapacity(500 * 1000 ** 3, { unit: 'gb', decimals: 0 }), '500 GB')
})

test('label capacity prefers vendor bytes and otherwise falls back to GiB', () => {
  assert.equal(formatCapacity(DRIVE, { unit: 'label', decimals: 0 }, LABEL), '4 TB')
  assert.equal(formatCapacity(DRIVE, { unit: 'label', decimals: 1 }, null), '3.6 TiB')
  assert.equal(formatCapacity(DRIVE, { unit: 'label', decimals: 1 }, 0), '3.6 TiB')
})

test('decimal places are shared and missing values stay an em dash', () => {
  assert.equal(formatCapacity(1.5 * 1024 ** 3, { unit: 'gib', decimals: 2 }), '1.50 GiB')
  assert.equal(formatCapacity(1.5 * 1024 ** 3, { unit: 'gib', decimals: 0 }), '2 GiB')
  assert.equal(formatCapacity(null, { unit: 'gb', decimals: 1 }), '—')
  assert.equal(formatCapacity(undefined, { unit: 'gib', decimals: 3 }), '—')
})

test('bytes under one KiB do not take decimals', () => {
  assert.equal(formatCapacity(512, { unit: 'gib', decimals: 2 }), '512 B')
  assert.equal(formatCapacity(0, { unit: 'gb', decimals: 2 }), '0 B')
})
