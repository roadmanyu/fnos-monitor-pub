import assert from 'node:assert/strict'
import test from 'node:test'
import { TREND_WINDOW_MS, linePathTimed, mergeSeries } from './trendWindow.js'

test('merge keeps only the last 3 minutes and drops empty values', () => {
  const now = 1_800_000
  const series = mergeSeries(
    [
      { ts: new Date(now - TREND_WINDOW_MS - 1000).toISOString(), value: 1 },
      { ts: new Date(now - 2000).toISOString(), value: 2 }
    ],
    [
      { ts: new Date(now - 2000).toISOString(), value: 9 },
      { ts: new Date(now).toISOString(), value: 4 },
      { ts: new Date(now).toISOString(), value: null }
    ],
    now
  )
  assert.equal(series.length, 2)
  assert.equal(series[0].value, 9)
  assert.equal(series[1].value, 4)
})

test('cold start draws a short segment on the right instead of stretching the window', () => {
  const now = 10_000_000
  const points = [
    { t: now - 1000, value: 10 },
    { t: now, value: 20 }
  ]
  const d = linePathTimed(points, 300, 100, 100, now)
  const xs = [...d.matchAll(/[ML](\d+(?:\.\d+)?)/g)].map((match) => Number(match[1]))
  assert.equal(xs.length, 2)
  assert.ok(xs[0] > 300 * 0.9)
  assert.ok(xs[1] >= xs[0])
})

test('one sample does not invent a line', () => {
  const now = 5_000
  assert.equal(linePathTimed([{ t: now, value: 40 }], 300, 100, 100, now), '')
})
