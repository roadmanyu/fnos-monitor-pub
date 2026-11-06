import assert from 'node:assert/strict'
import test from 'node:test'
import { shouldRefresh } from './refreshGate.js'

test('slow panels refresh on the first sample and then wait', () => {
  assert.equal(shouldRefresh(null, 1_000, 60_000, false), true)
  assert.equal(shouldRefresh(1_000, 30_000, 60_000, false), false)
  assert.equal(shouldRefresh(1_000, 61_000, 60_000, false), true)
  assert.equal(shouldRefresh(1_000, 2_000, 60_000, true), true)
})
