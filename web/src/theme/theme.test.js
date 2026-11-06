import assert from 'node:assert/strict'
import test from 'node:test'
import { applyTheme, readTheme, resolvedTheme, writeTheme } from './theme.js'

function memoryStorage(initial = {}) {
  const data = { ...initial }
  return {
    getItem(key) { return Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null },
    setItem(key, value) { data[key] = String(value) },
    dump: data
  }
}

test('theme preference round-trips through storage', () => {
  const storage = memoryStorage()
  assert.equal(writeTheme('dark', storage), 'dark')
  assert.equal(readTheme(storage), 'dark')
  assert.equal(storage.dump.fnos_theme, 'dark')
  writeTheme('auto', storage)
  assert.equal(readTheme(storage), 'auto')
})

test('unknown theme values fall back to auto and still persist as auto', () => {
  const storage = memoryStorage({ fnos_theme: 'purple' })
  assert.equal(readTheme(storage), 'auto')
  assert.equal(writeTheme('nope', storage), 'auto')
  assert.equal(readTheme(storage), 'auto')
})

test('auto follows the system, manual choice does not', () => {
  assert.equal(resolvedTheme('auto', true), 'dark')
  assert.equal(resolvedTheme('auto', false), 'light')
  assert.equal(resolvedTheme('light', true), 'light')
  assert.equal(resolvedTheme('dark', false), 'dark')
  assert.equal(resolvedTheme('junk', true), 'dark')
})

test('applyTheme writes the resolved mode onto the document', () => {
  const storage = memoryStorage()
  writeTheme('dark', storage)
  const doc = { documentElement: { setAttribute() {}, getAttribute() { return this.value }, value: '' } }
  doc.documentElement.setAttribute = function setAttribute(_name, value) { this.value = value }
  const applied = applyTheme(doc, storage, false)
  assert.equal(applied.pref, 'dark')
  assert.equal(applied.resolved, 'dark')
  assert.equal(doc.documentElement.value, 'dark')

  writeTheme('auto', storage)
  const again = applyTheme(doc, storage, true)
  assert.equal(again.pref, 'auto')
  assert.equal(again.resolved, 'dark')
  assert.equal(readTheme(storage), 'auto')
})
