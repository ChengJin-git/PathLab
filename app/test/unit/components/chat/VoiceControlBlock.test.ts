import { describe, expect, it } from 'vitest'
import { parseVoiceControlBlock, removeVoiceControlBlock } from '@renderer/components/chat/VoiceControlBlock'

const stop = '[VOICE_CONTROL]{"action":"stop"}[/VOICE_CONTROL]'

describe('streamed voice control protocol', () => {
  it('executes only after every part of the leading command has arrived', () => {
    for (let length = 0; length < stop.length; length++) {
      expect(parseVoiceControlBlock(stop.slice(0, length))).toBeNull()
      expect(removeVoiceControlBlock(stop.slice(0, length))).toBe('')
    }
    expect(parseVoiceControlBlock(stop)).toEqual({ action: 'stop' })
    expect(removeVoiceControlBlock(stop + '已关闭语音。')).toBe('已关闭语音。')
  })

  it.each([
    'I will stop the recording now.',
    'Here is an example: ' + stop,
    '```json\n' + stop + '\n```',
    '[VOICE_CONTROL]{"action":"restart"}[/VOICE_CONTROL]',
    '[VOICE_CONTROL]{not json}[/VOICE_CONTROL]',
    '[VOICE_CONTROL]null[/VOICE_CONTROL]',
  ])('does not execute prose, examples, or malformed commands: %s', content => {
    expect(parseVoiceControlBlock(content)).toBeNull()
  })

  it('allows only the first command to control the current response', () => {
    const content = '[VOICE_CONTROL]{"action":"continue"}[/VOICE_CONTROL]\nHere is an example: ' + stop
    expect(parseVoiceControlBlock(content)).toEqual({ action: 'continue' })
  })
})
