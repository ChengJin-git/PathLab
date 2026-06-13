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
    this.buffer = []
    // Buffer size: 16kHz sample rate, collect ~256ms of audio (4096 samples)
    // Each sample is 2 bytes (Int16), so buffer size is 8192 bytes
    this.bufferSize = 4096 * 2

    // Handle messages from main thread
    this.port.onmessage = (event) => {
      if (event.data === 'STOP') {
        this.isRecording = false
        this.flush()
      }
    }
  }

  /**
   * Flush remaining audio data in buffer to main thread
   */
  flush() {
    if (this.buffer.length > 0) {
      const finalBuffer = new Uint8Array(this.buffer)
      this.port.postMessage({
        type: 'audio',
        data: finalBuffer.buffer
      }, [finalBuffer.buffer])
      this.buffer = []
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
      this.buffer.push(intSample & 0xff)
      this.buffer.push((intSample >> 8) & 0xff)

      // When buffer is full, send to main thread
      if (this.buffer.length >= this.bufferSize) {
        const outputBuffer = new Uint8Array(this.buffer)
        this.port.postMessage({
          type: 'audio',
          data: outputBuffer.buffer
        }, [outputBuffer.buffer])
        this.buffer = []
      }
    }

    return true
  }
}

// Register the processor
registerProcessor('pcm-processor', PCMProcessor)

