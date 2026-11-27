/**
 * PCM Audio Processor for AudioWorklet
 * 
 * Processes audio input from microphone, converts Float32 samples to Int16 PCM,
 * and sends them to the main thread via MessagePort.
 * 
 * This replaces the deprecated ScriptProcessorNode with the modern AudioWorklet API.
 */

class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.isRecording = true
    this.isPaused = false
    // 80ms at 16kHz: start streaming promptly instead of batching 256ms.
    this.buffer = new ArrayBuffer(1280 * 2)
    this.view = new DataView(this.buffer)
    this.offset = 0

    // Handle messages from main thread
    this.port.onmessage = (event) => {
      if (event.data === 'STOP') {
        this.isRecording = false
        this.flush()
      } else if (event.data === 'PAUSE' || event.data === 'RESUME') {
        this.isPaused = event.data === 'PAUSE'
        this.offset = 0
      }
    }
  }

  /**
   * Flush remaining audio data in buffer to main thread
   */
  flush() {
    if (this.offset > 0) {
      const finalBuffer = this.buffer.slice(0, this.offset)
      this.port.postMessage({
        type: 'audio',
        data: finalBuffer
      }, [finalBuffer])
      this.offset = 0
    }
  }

  /**
   * Process audio input
   * @param {Float32Array[][]} inputs - Input audio channels
   * @param {Float32Array[][]} outputs - Output audio channels (unused)
   * @param {Object} parameters - Audio parameters (unused)
   * @returns {boolean} - Whether to continue processing
   */
  process(inputs, outputs, parameters) {
    // Stop processing if recording has stopped
    if (!this.isRecording) {
      this.flush()
      return false
    }
    if (this.isPaused) return true

    const input = inputs[0]
    if (!input || input.length === 0) {
      return true
    }

    const inputChannel = input[0]
    if (!inputChannel || inputChannel.length === 0) {
      return true
    }

    // Convert Float32 samples to Int16 PCM and add to buffer
    for (let i = 0; i < inputChannel.length; i++) {
      // Clamp sample to [-1, 1]
      const sample = Math.max(-1, Math.min(1, inputChannel[i]))
      // Convert to Int16
      const intSample = sample < 0 ? sample * 0x8000 : sample * 0x7fff
      // Store as little-endian bytes
      this.view.setInt16(this.offset, intSample, true)
      this.offset += 2

      // When buffer is full, send to main thread
      if (this.offset === this.buffer.byteLength) this.flush()
    }

    return true
  }
}

// Register the processor
registerProcessor('pcm-processor', PCMProcessor)
