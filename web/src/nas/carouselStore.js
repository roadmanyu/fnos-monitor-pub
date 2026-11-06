import { reactive, watch } from 'vue'
import { normalizeCarousel } from './carousel.js'

const KEY = 'fnos_carousel_v1'

function load() {
  try {
    return normalizeCarousel(JSON.parse(localStorage.getItem(KEY) || 'null'))
  } catch {
    return normalizeCarousel(null)
  }
}

export const carousel = reactive(load())

watch(carousel, () => {
  localStorage.setItem(KEY, JSON.stringify({
    enabled: !!carousel.enabled,
    intervalSec: carousel.intervalSec,
    idleSec: carousel.idleSec,
    kiosk: !!carousel.kiosk
  }))
}, { deep: true })

export function patchCarousel(patch) {
  const next = normalizeCarousel({ ...carousel, ...patch })
  carousel.enabled = next.enabled
  carousel.intervalSec = next.intervalSec
  carousel.idleSec = next.idleSec
  carousel.kiosk = next.kiosk
}
