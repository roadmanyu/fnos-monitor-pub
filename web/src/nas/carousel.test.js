import assert from 'node:assert/strict'
import test from 'node:test'
import { nextProfileId, noteInteraction, normalizeCarousel, shouldAdvance } from './carousel.js'

const profiles = [{ id: 'local' }, { id: 'nas-a' }, { id: 'nas-b' }]

test('carousel waits for the full interval', () => {
  const base = { enabled: true, count: 3, lastAdvanceAt: 1_000, intervalMs: 20_000, pausedUntil: 0 }
  assert.equal(shouldAdvance({ ...base, now: 20_999 }), false)
  assert.equal(shouldAdvance({ ...base, now: 21_000 }), true)
})

test('interaction pauses the carousel and idle resumes after another full interval', () => {
  const pausedUntil = noteInteraction(5_000, 45_000)
  assert.equal(pausedUntil, 50_000)
  const base = { enabled: true, count: 2, lastAdvanceAt: 0, intervalMs: 20_000, pausedUntil }
  assert.equal(shouldAdvance({ ...base, now: 40_000 }), false)
  assert.equal(shouldAdvance({ ...base, now: 50_000 }), false)
  assert.equal(shouldAdvance({ ...base, now: 69_999 }), false)
  assert.equal(shouldAdvance({ ...base, now: 70_000 }), true)
})

test('a single node or a disabled carousel never advances', () => {
  assert.equal(shouldAdvance({
    enabled: true, count: 1, now: 100_000, lastAdvanceAt: 0, intervalMs: 5_000, pausedUntil: 0
  }), false)
  assert.equal(shouldAdvance({
    enabled: false, count: 4, now: 100_000, lastAdvanceAt: 0, intervalMs: 5_000, pausedUntil: 0
  }), false)
})

test('next node wraps around the logged-in list', () => {
  assert.equal(nextProfileId(profiles, 'local'), 'nas-a')
  assert.equal(nextProfileId(profiles, 'nas-b'), 'local')
  assert.equal(nextProfileId(profiles, 'missing'), 'local')
  assert.equal(nextProfileId([{ id: 'local' }], 'local'), 'local')
})

test('carousel settings clamp to a usable range', () => {
  const next = normalizeCarousel({ enabled: 1, intervalSec: 1, idleSec: 9999, kiosk: 'yes' })
  assert.equal(next.enabled, true)
  assert.equal(next.intervalSec, 5)
  assert.equal(next.idleSec, 600)
  assert.equal(next.kiosk, true)
  assert.deepEqual(normalizeCarousel(null), {
    enabled: false,
    intervalSec: 20,
    idleSec: 45,
    kiosk: false
  })
})
