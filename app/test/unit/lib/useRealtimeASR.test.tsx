import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ASR_MAX_PENDING_AUDIO_BYTES, ASR_SETUP_DEADLINE_MS, useRealtimeASR } from '@renderer/lib/hooks/useRealtimeASR'
import { useVoiceSession, VOICE_CONTINUATION_WINDOW_MS } from '@renderer/lib/hooks/useVoiceSession'

vi.mock('@renderer/config', () => ({ getApiBase: () => 'http://localhost:6100' }))
vi.mock('@renderer/api/client', () => ({ getAuthToken: () => 'test-token' }))

class Socket {
  static OPEN = 1
  static instances: Socket[] = []
  readyState = 0
  onopen?: () => void
  onmessage?: (event: { data: string }) => void
  onerror?: () => void
  onclose?: () => void
  send = vi.fn()
  close = vi.fn(() => { this.readyState = 3 })
  constructor() { Socket.instances.push(this) }
  open() { this.readyState = 1; this.onopen?.() }
  event(type: string, extra = {}) { this.onmessage?.({ data: JSON.stringify({ type, ...extra }) }) }
}
class Worklet {
  static instances: Worklet[] = []
  port = { postMessage: vi.fn(), onmessage: undefined as undefined | ((event: { data: unknown }) => void) }
  connect = vi.fn()
  disconnect = vi.fn()
  constructor() { Worklet.instances.push(this) }
}
class Audio {
  static instances: Audio[] = []
  state = 'running'
  audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) }
  createMediaStreamSource = () => ({ connect: vi.fn(), disconnect: vi.fn() })
  close = vi.fn(async () => { this.state = 'closed' })
  constructor() { Audio.instances.push(this) }
}
const microphone = () => {
  const track = { enabled: true, stop: vi.fn() }
  return { track, getTracks: () => [track], getAudioTracks: () => [track] }
}
let stream: ReturnType<typeof microphone>
let getUserMedia: ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.useFakeTimers()
  Socket.instances = []; Worklet.instances = []; Audio.instances = []
  vi.stubGlobal('WebSocket', Socket)
  vi.stubGlobal('AudioContext', Audio)
  vi.stubGlobal('AudioWorkletNode', Worklet)
  stream = microphone()
  getUserMedia = vi.fn().mockResolvedValue(stream)
  Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia }, configurable: true })
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.stubGlobal('fetch', vi.fn()) })

async function ready(start: () => unknown) {
  await act(async () => { start() })
  const socket = Socket.instances.at(-1)!
  await act(async () => { socket.open(); socket.event('session.updated') })
  return socket
}

async function finishTurn(socket: Socket, transcript = 'hello', item_id = 'one') {
  act(() => {
    socket.event('input_audio_buffer.speech_stopped', { item_id })
    socket.event('conversation.item.input_audio_transcription.completed', { item_id, transcript })
  })
  await act(async () => { await vi.advanceTimersByTimeAsync(VOICE_CONTINUATION_WINDOW_MS) })
}

describe('realtime voice lifecycle', () => {
  it('starts actual capture before ASR is ready and flushes initial audio in order', async () => {
    const { result } = renderHook(() => useRealtimeASR({ onTranscriptComplete: vi.fn() }))
    await act(async () => { void result.current.startRecording() })
    expect(getUserMedia).toHaveBeenCalledTimes(1)
    expect(Audio.instances[0].audioWorklet.addModule).toHaveBeenCalled()
    expect(result.current.isRecording).toBe(true)
    expect(result.current.isConnecting).toBe(false)
    expect(result.current.mediaStream).toBe(stream)
    const socket = Socket.instances[0]
    const first = new ArrayBuffer(2560)
    const second = new ArrayBuffer(2560)
    act(() => {
      Worklet.instances[0].port.onmessage?.({ data: { type: 'audio', data: first } })
      Worklet.instances[0].port.onmessage?.({ data: { type: 'audio', data: second } })
    })
    expect(socket.send).not.toHaveBeenCalled()
    await act(async () => { socket.open(); socket.event('session.updated') })
    expect(JSON.parse(socket.send.mock.calls[0][0]).session.turn_detection.silence_duration_ms).toBe(1200)
    expect(result.current.isRecording).toBe(true)
    expect(socket.send.mock.calls.slice(1).map(([data]) => data)).toEqual([first, second])
    const third = new ArrayBuffer(2560)
    act(() => Worklet.instances[0].port.onmessage?.({ data: { type: 'audio', data: third } }))
    expect(socket.send).toHaveBeenLastCalledWith(third)
  })

  it('shows connecting until the microphone really becomes available', async () => {
    let grant!: (value: ReturnType<typeof microphone>) => void
    getUserMedia.mockImplementationOnce(() => new Promise(resolve => { grant = resolve }))
    const { result } = renderHook(() => useVoiceSession({ onTranscript: vi.fn() }))
    await ready(result.current.toggle)
    expect(result.current.voiceState).toBe('connecting')
    expect(result.current.mediaStream).toBeNull()
    await act(async () => { grant(stream) })
    expect(result.current.voiceState).toBe('recording')
  })

  it('discards queued startup audio when stopped before the cloud is ready', async () => {
    const { result } = renderHook(() => useVoiceSession({ onTranscript: vi.fn() }))
    await act(async () => result.current.toggle())
    const socket = Socket.instances[0]
    act(() => {
      Worklet.instances[0].port.onmessage?.({ data: { type: 'audio', data: new ArrayBuffer(2560) } })
      result.current.stop()
      socket.event('session.updated')
    })
    expect(socket.send).not.toHaveBeenCalled()
    expect(result.current.voiceState).toBe('idle')
    expect(stream.track.stop).toHaveBeenCalledTimes(1)
  })

  it('bounds startup buffering and closes resources rather than losing the beginning', async () => {
    const onError = vi.fn()
    const { result } = renderHook(() => useRealtimeASR({ onTranscriptComplete: vi.fn(), onError }))
    await act(async () => { void result.current.startRecording() })
    await act(async () => {
      for (let i = 0; i <= ASR_MAX_PENDING_AUDIO_BYTES / 2560; i++) Worklet.instances[0].port.onmessage?.({ data: { type: 'audio', data: new ArrayBuffer(2560) } })
    })
    expect(onError).toHaveBeenCalledTimes(1)
    expect(result.current.isRecording).toBe(false)
    expect(result.current.mediaStream).toBeNull()
    expect(stream.track.stop).toHaveBeenCalledTimes(1)
    expect(Socket.instances[0].send).not.toHaveBeenCalled()
  })

  it('keeps all opening audio through a slow handshake and gateway retry', async () => {
    const onError = vi.fn()
    const { result } = renderHook(() => useRealtimeASR({ onTranscriptComplete: vi.fn(), onError }))
    await act(async () => { void result.current.startRecording() })
    const socket = Socket.instances[0]
    act(() => socket.open())
    const frames: ArrayBuffer[] = []
    // First gateway attempt takes 10s, then its retry succeeds at 12s.
    for (let i = 0; i < 150; i++) {
      const audio = new ArrayBuffer(2560)
      new DataView(audio).setInt16(0, i, true)
      frames.push(audio)
      await act(async () => {
        await vi.advanceTimersByTimeAsync(80)
        if (i === 124) socket.event('session.progress', { step: 'connecting_upstream', attempt: 2 })
        Worklet.instances[0].port.onmessage?.({ data: { type: 'audio', data: audio } })
      })
    }
    expect(onError).not.toHaveBeenCalled()
    expect(result.current.isRecording).toBe(true)
    expect(socket.send.mock.calls).toHaveLength(1) // configuration only
    act(() => socket.event('session.updated'))
    expect(socket.send.mock.calls.slice(1).map(([data]) => data)).toEqual(frames)
    expect(getUserMedia).toHaveBeenCalledTimes(1)
    // Successful setup cancels both timeout clocks.
    await act(async () => { await vi.advanceTimersByTimeAsync(ASR_SETUP_DEADLINE_MS) })
    expect(onError).not.toHaveBeenCalled()
    expect(result.current.isRecording).toBe(true)
  })

  it('times out a silent service once and ignores late setup events', async () => {
    const onError = vi.fn()
    const { result } = renderHook(() => useRealtimeASR({ onTranscriptComplete: vi.fn(), onError }))
    await act(async () => { void result.current.startRecording() })
    const socket = Socket.instances[0]
    act(() => socket.open())
    await act(async () => { await vi.advanceTimersByTimeAsync(15000) })
    expect(onError).toHaveBeenCalledTimes(1)
    expect(onError).toHaveBeenCalledWith('Voice service setup timed out. Please try again.')
    expect(result.current.mediaStream).toBeNull()
    expect(result.current.isRecording).toBe(false)
    act(() => socket.event('session.updated'))
    expect(socket.send.mock.calls).toHaveLength(2) // configuration + finish, no PCM
    await act(async () => { await vi.advanceTimersByTimeAsync(ASR_SETUP_DEADLINE_MS) })
    expect(onError).toHaveBeenCalledTimes(1)
    expect(stream.track.stop).toHaveBeenCalledTimes(1)
  })

  it('enforces an overall setup deadline even when progress keeps arriving', async () => {
    const onError = vi.fn()
    const { result } = renderHook(() => useRealtimeASR({ onTranscriptComplete: vi.fn(), onError }))
    await act(async () => { void result.current.startRecording() })
    const socket = Socket.instances[0]
    act(() => socket.open())
    for (let i = 0; i < 4; i++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10000)
        socket.event('session.progress', { step: 'connecting_upstream' })
      })
    }
    expect(onError).not.toHaveBeenCalled()
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(onError).toHaveBeenCalledTimes(1)
    expect(result.current.isRecording).toBe(false)
    expect(stream.track.stop).toHaveBeenCalledTimes(1)
    expect(socket.close).toHaveBeenCalledTimes(1)
  })

  it('reuses capture and connection across turns, mutes while thinking, and deduplicates finals', async () => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useVoiceSession({ onTranscript }))
    const socket = await ready(result.current.toggle)
    await finishTurn(socket)
    expect(result.current.voiceState).toBe('processing')
    expect(stream.track.enabled).toBe(false)
    const audio = new ArrayBuffer(2560)
    const sent = socket.send.mock.calls.length
    act(() => { Worklet.instances[0].port.onmessage?.({ data: { type: 'audio', data: audio } }) })
    expect(socket.send).toHaveBeenCalledTimes(sent)
    await act(async () => { result.current.notifyResponseComplete('[VOICE_CONTROL]{"action":"continue"}[/VOICE_CONTROL]') })
    expect(result.current.voiceState).toBe('recording')
    expect(stream.track.enabled).toBe(true)
    expect(Socket.instances).toHaveLength(1)
    expect(getUserMedia).toHaveBeenCalledTimes(1)
    act(() => {
      socket.event('conversation.item.input_audio_transcription.completed', { item_id: 'one', transcript: 'duplicate' })
      Worklet.instances[0].port.onmessage?.({ data: { type: 'audio', data: audio } })
    })
    expect(onTranscript).toHaveBeenCalledTimes(1)
    expect(socket.send).toHaveBeenLastCalledWith(audio)
  })

  it('does not let a cancelled permission request disrupt a newer recording', async () => {
    let grant!: (value: ReturnType<typeof microphone>) => void
    const stale = microphone()
    getUserMedia.mockImplementationOnce(() => new Promise(resolve => { grant = resolve }))
    const onError = vi.fn()
    const { result } = renderHook(() => useRealtimeASR({ onTranscriptComplete: vi.fn(), onError }))
    await act(async () => { void result.current.startRecording() })
    act(() => result.current.stopRecording())
    await ready(result.current.startRecording)
    await act(async () => { grant(stale) })
    expect(stale.track.stop).toHaveBeenCalledTimes(1)
    expect(result.current.isRecording).toBe(true)
    expect(stream.track.stop).not.toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
  })

  it('guards two simultaneous starts before async initialization', async () => {
    const { result } = renderHook(() => useRealtimeASR({ onTranscriptComplete: vi.fn() }))
    await act(async () => { void result.current.startRecording(); void result.current.startRecording() })
    expect(Socket.instances).toHaveLength(1)
    expect(getUserMedia).toHaveBeenCalledTimes(1)
  })

  it('releases paused resources and reconnects after the idle bound', async () => {
    const { result } = renderHook(() => useVoiceSession({ onTranscript: vi.fn() }))
    const socket = await ready(result.current.toggle)
    await finishTurn(socket)
    await act(async () => { await vi.advanceTimersByTimeAsync(45000) })
    expect(stream.track.stop).toHaveBeenCalled()
    expect(result.current.voiceState).toBe('processing')
    await ready(() => result.current.notifyResponseComplete('[VOICE_CONTROL]{"action":"continue"}[/VOICE_CONTROL]'))
    expect(Socket.instances).toHaveLength(2)
    expect(result.current.voiceState).toBe('recording')
  })

  it('ends resources on final answer and ignores duplicate response completion', async () => {
    const { result } = renderHook(() => useVoiceSession({ onTranscript: vi.fn() }))
    const socket = await ready(result.current.toggle)
    await finishTurn(socket, 'bye')
    act(() => result.current.notifyResponseComplete('[VOICE_CONTROL]{"action":"stop"}[/VOICE_CONTROL]'))
    act(() => result.current.notifyResponseComplete('[VOICE_CONTROL]{"action":"continue"}[/VOICE_CONTROL]'))
    expect(result.current.voiceState).toBe('idle')
    expect(socket.close).toHaveBeenCalledTimes(1)
    expect(Socket.instances).toHaveLength(1)
    expect(stream.track.stop).toHaveBeenCalledTimes(1)
  })

  it.each([
    'O K，然后我现在测试完了，我想把这个语音给它关掉。',
    'OK，我现在要关掉这个测试，我不要这个录音了。',
    '我不想继续录音了。',
  ])('executes a streamed semantic stop without reclassifying the user text: %s', async (text) => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useVoiceSession({ onTranscript }))
    const socket = await ready(result.current.toggle)
    await finishTurn(socket, text)
    expect(onTranscript).toHaveBeenCalledTimes(1)
    expect(onTranscript).toHaveBeenCalledWith(text)
    expect(result.current.voiceState).toBe('processing')
    const command = '[VOICE_CONTROL]{"action":"stop"}[/VOICE_CONTROL]'
    act(() => result.current.notifyResponseProgress(command.slice(0, -1)))
    expect(result.current.voiceState).toBe('processing')
    expect(stream.track.stop).not.toHaveBeenCalled()
    act(() => result.current.notifyResponseProgress(command))
    expect(result.current.voiceState).toBe('idle')
    expect(result.current.mediaStream).toBeNull()
    expect(stream.track.stop).toHaveBeenCalledTimes(1)
    expect(socket.close).toHaveBeenCalledTimes(1)
    expect(Audio.instances[0].close).toHaveBeenCalledTimes(1)
    const sent = socket.send.mock.calls.length
    act(() => Worklet.instances[0].port.onmessage?.({ data: { type: 'audio', data: new ArrayBuffer(2560) } }))
    expect(socket.send).toHaveBeenCalledTimes(sent)
    await act(async () => {
      result.current.notifyResponseComplete('好的，已停止连续语音会话。')
      result.current.notifyResponseComplete('[VOICE_CONTROL]{"action":"continue"}[/VOICE_CONTROL]')
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(result.current.voiceState).toBe('idle')
    expect(Socket.instances).toHaveLength(1)
  })

  it('manual submission can be stopped by the same streaming command', async () => {
    const { result } = renderHook(() => useVoiceSession({ onTranscript: vi.fn() }))
    const socket = await ready(result.current.toggle)
    act(() => result.current.forceSend('帮我把麦克风关掉。'))
    expect(result.current.voiceState).toBe('processing')
    act(() => result.current.notifyResponseProgress('[VOICE_CONTROL]{"action":"stop"}[/VOICE_CONTROL]'))
    expect(result.current.voiceState).toBe('idle')
    expect(result.current.mediaStream).toBeNull()
    expect(socket.close).toHaveBeenCalledTimes(1)
    expect(stream.track.stop).toHaveBeenCalledTimes(1)
  })

  it('reconnects quietly if the provider closes a paused session', async () => {
    const onError = vi.fn()
    const { result } = renderHook(() => useVoiceSession({ onTranscript: vi.fn(), onError }))
    const socket = await ready(result.current.toggle)
    await finishTurn(socket)
    await act(async () => { socket.onclose?.() })
    expect(result.current.voiceState).toBe('processing')
    expect(onError).not.toHaveBeenCalled()
    await ready(() => result.current.notifyResponseComplete('[VOICE_CONTROL]{"action":"continue"}[/VOICE_CONTROL]'))
    expect(result.current.voiceState).toBe('recording')
    expect(Socket.instances).toHaveLength(2)
  })

  it('manual send ignores a late final from the discarded connection', async () => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useVoiceSession({ onTranscript }))
    const socket = await ready(result.current.toggle)
    act(() => result.current.forceSend('chosen preview'))
    act(() => socket.event('conversation.item.input_audio_transcription.completed', { transcript: 'late final' }))
    expect(onTranscript).toHaveBeenCalledTimes(1)
    expect(onTranscript).toHaveBeenCalledWith('chosen preview')
    expect(socket.close).toHaveBeenCalledTimes(1)
  })

  it('merges resumed speech into one turn instead of submitting the first ASR segment', async () => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useVoiceSession({ onTranscript }))
    const socket = await ready(result.current.toggle)
    act(() => {
      socket.event('input_audio_buffer.speech_started', { item_id: 'first' })
      socket.event('input_audio_buffer.speech_stopped', { item_id: 'first' })
      socket.event('conversation.item.input_audio_transcription.completed', { item_id: 'first', transcript: '帮我看看数据。' })
    })
    expect(result.current.partialText).toBe('帮我看看数据。')
    expect(result.current.voiceState).toBe('recording')
    await act(async () => { await vi.advanceTimersByTimeAsync(250) })
    act(() => {
      socket.event('input_audio_buffer.speech_started', { item_id: 'second' })
      socket.event('conversation.item.input_audio_transcription.text', { item_id: 'second', text: '', stash: '先看胃癌' })
    })
    expect(result.current.partialText).toBe('帮我看看数据。 先看胃癌')
    await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
    expect(onTranscript).not.toHaveBeenCalled()
    await finishTurn(socket, '先看胃癌那一组。', 'second')
    expect(onTranscript).toHaveBeenCalledTimes(1)
    expect(onTranscript).toHaveBeenCalledWith('帮我看看数据。 先看胃癌那一组。')
  })

  it('waits for the second final when it starts before the first final arrives', async () => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useVoiceSession({ onTranscript }))
    const socket = await ready(result.current.toggle)
    act(() => {
      socket.event('input_audio_buffer.speech_started', { item_id: 'first' })
      socket.event('input_audio_buffer.speech_stopped', { item_id: 'first' })
      socket.event('input_audio_buffer.speech_started', { item_id: 'second' })
      socket.event('conversation.item.input_audio_transcription.completed', { item_id: 'first', transcript: 'Show my data.' })
      socket.event('input_audio_buffer.speech_stopped', { item_id: 'second' })
    })
    await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
    expect(onTranscript).not.toHaveBeenCalled()
    await finishTurn(socket, 'Start with the gastric cohort.', 'second')
    expect(onTranscript).toHaveBeenCalledWith('Show my data. Start with the gastric cohort.')
  })

  it('keeps recording through answers and cards when the model requests continuation', async () => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useVoiceSession({ onTranscript }))
    const socket = await ready(result.current.toggle)
    await finishTurn(socket, '我有哪些数据？', 'first')
    await act(async () => { result.current.notifyResponseComplete('[VOICE_CONTROL]{"action":"continue"}[/VOICE_CONTROL]你有21个数据集。') })
    expect(result.current.voiceState).toBe('recording')
    await finishTurn(socket, '帮我配置训练。', 'second')
    await act(async () => { result.current.notifyResponseComplete('[VOICE_CONTROL]{"action":"continue"}[/VOICE_CONTROL][TASK_CONFIG]{}[/TASK_CONFIG]') })
    expect(result.current.voiceState).toBe('recording')
    await finishTurn(socket, '把训练轮数改为20。', 'third')
    await act(async () => { result.current.notifyResponseComplete('配置已更新。') })
    expect(result.current.voiceState).toBe('recording')
    expect(onTranscript.mock.calls.map(([text]) => text)).toEqual(['我有哪些数据？', '帮我配置训练。', '把训练轮数改为20。'])
    expect(Socket.instances).toHaveLength(1)
    expect(getUserMedia).toHaveBeenCalledTimes(1)
  })

  it('does not execute a control from an old response after a manual stop and restart', async () => {
    const { result } = renderHook(() => useVoiceSession({ onTranscript: vi.fn() }))
    const first = await ready(result.current.toggle)
    await finishTurn(first, 'hello')
    act(() => result.current.stop())
    await ready(result.current.toggle)
    act(() => result.current.notifyResponseProgress('[VOICE_CONTROL]{"action":"stop"}[/VOICE_CONTROL]'))
    expect(result.current.voiceState).toBe('recording')
    expect(Socket.instances[1].close).not.toHaveBeenCalled()
  })

  it('waits until reply completion before resuming on continue', async () => {
    const { result } = renderHook(() => useVoiceSession({ onTranscript: vi.fn() }))
    const socket = await ready(result.current.toggle)
    await finishTurn(socket)
    const content = '[VOICE_CONTROL]{"action":"continue"}[/VOICE_CONTROL]'
    act(() => result.current.notifyResponseProgress(content))
    expect(result.current.voiceState).toBe('processing')
    expect(stream.track.enabled).toBe(false)
    await act(async () => result.current.notifyResponseComplete(content + '完成。'))
    expect(result.current.voiceState).toBe('recording')
  })

  it('cancels pending submission on stop and unmount', async () => {
    const onTranscript = vi.fn()
    const { result, unmount } = renderHook(() => useVoiceSession({ onTranscript }))
    const socket = await ready(result.current.toggle)
    act(() => socket.event('conversation.item.input_audio_transcription.completed', { item_id: 'one', transcript: 'Do not send yet' }))
    act(() => result.current.stop())
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(onTranscript).not.toHaveBeenCalled()
    const next = await ready(result.current.toggle)
    act(() => next.event('conversation.item.input_audio_transcription.completed', { item_id: 'two', transcript: 'Still pending' }))
    unmount()
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(onTranscript).not.toHaveBeenCalled()
  })

  it('manual send includes finalized and partial segments once', async () => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useVoiceSession({ onTranscript }))
    const socket = await ready(result.current.toggle)
    act(() => {
      socket.event('conversation.item.input_audio_transcription.completed', { item_id: 'first', transcript: 'First sentence.' })
      socket.event('input_audio_buffer.speech_started', { item_id: 'second' })
      socket.event('conversation.item.input_audio_transcription.text', { item_id: 'second', stash: 'Second sentence' })
    })
    act(() => result.current.forceSend(result.current.partialText))
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(onTranscript).toHaveBeenCalledTimes(1)
    expect(onTranscript).toHaveBeenCalledWith('First sentence. Second sentence')
  })

  it('settles an empty continuation final without losing the previous sentence', async () => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useVoiceSession({ onTranscript }))
    const socket = await ready(result.current.toggle)
    act(() => {
      socket.event('conversation.item.input_audio_transcription.completed', { item_id: 'first', transcript: 'Keep this sentence.' })
      socket.event('input_audio_buffer.speech_started', { item_id: 'noise' })
    })
    await finishTurn(socket, '', 'noise')
    expect(onTranscript).toHaveBeenCalledTimes(1)
    expect(onTranscript).toHaveBeenCalledWith('Keep this sentence.')
  })

  it('fails immediately on server error rather than waiting for setup timeout', async () => {
    const onError = vi.fn()
    const { result } = renderHook(() => useRealtimeASR({ onTranscriptComplete: vi.fn(), onError }))
    await act(async () => { void result.current.startRecording() })
    await act(async () => { Socket.instances[0].event('error', { error: { message: 'Unavailable' } }) })
    expect(onError).toHaveBeenCalledTimes(1)
    expect(onError).toHaveBeenCalledWith('Unavailable')
    expect(result.current.isConnecting).toBe(false)
    await act(async () => { await vi.advanceTimersByTimeAsync(16000) })
    expect(onError).toHaveBeenCalledTimes(1)
  })
})
