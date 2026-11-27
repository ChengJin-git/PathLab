import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { describe, expect, it, vi } from 'vitest'

function processor() {
  let Constructor: any
  const port = { postMessage: vi.fn(), onmessage: undefined as any }
  vm.runInNewContext(readFileSync('src/renderer/public/pcm-processor.js', 'utf8'), {
    AudioWorkletProcessor: class { port = port },
    registerProcessor: (_name: string, value: any) => { Constructor = value },
    ArrayBuffer, DataView, Math,
  })
  return { instance: new Constructor(), port }
}

describe('PCM transport', () => {
  it('sends 80ms frames with clipped signed little-endian 16-bit audio', () => {
    const { instance, port } = processor()
    const samples = new Float32Array(1280)
    samples.set([-2, -1, 0, 1, 2])
    instance.process([[samples]])
    expect(port.postMessage).toHaveBeenCalledTimes(1)
    const data = port.postMessage.mock.calls[0][0].data
    expect(data.byteLength).toBe(2560)
    const values = new DataView(data)
    expect([0, 2, 4, 6, 8].map(i => values.getInt16(i, true))).toEqual([-32768, -32768, 0, 32767, 32767])
  })

  it('discards the buffered tail on pause so it cannot leak into the next turn', () => {
    const { instance, port } = processor()
    instance.process([[new Float32Array(640).fill(1)]])
    port.onmessage({ data: 'PAUSE' })
    instance.process([[new Float32Array(1280).fill(1)]])
    expect(port.postMessage).not.toHaveBeenCalled()
    port.onmessage({ data: 'RESUME' })
    instance.process([[new Float32Array(1280)]])
    expect(port.postMessage).toHaveBeenCalledTimes(1)
    expect([...new Uint8Array(port.postMessage.mock.calls[0][0].data)].every(x => x === 0)).toBe(true)
  })
})
