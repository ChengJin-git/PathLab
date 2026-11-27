import React, { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { extractLastChatBlock, stripChatBlocks } from './chatBlockParsing'

interface Option {
  text: string  // The full option text to display and send
}

interface OptionButtonsProps {
  options: Option[]
  onSelect: (text: string) => void
  disabled?: boolean
}

/**
 * Parse [OPTIONS] block from message content
 * Format:
 * [OPTIONS]
 * - Option text 1
 * - Option text 2
 * [/OPTIONS]
 *
 * Each line starting with "- " is treated as an option.
 * The entire text after "- " is used as the option.
 */
export function parseOptions(content: string): Option[] | null {
  const match = extractLastChatBlock(content, 'OPTIONS', { allowIncompleteLast: true })
  if (!match) return null

  const optionsText = match.body
  const options: Option[] = []

  const lines = optionsText.split('\n')
  const plainFallbackLines: string[] = []
  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed) continue

    // Support multiple list formats: "- text", "* text", "1. text", "1) text"
    let optionText: string | null = null
    const bulletMatch = trimmed.match(/^(?:[-*•·▪◦]|\[[ xX]?\])\s*(.+)$/)
    if (bulletMatch) {
      optionText = bulletMatch[1].trim()
    } else {
      // Match numbered list: "1. text", "1) text", "1、text", "A. text", "一、text"
      const numberedMatch = trimmed.match(/^(?:[0-9]+|[A-Za-z]|[一二三四五六七八九十]+)[.)、]\s*(.+)$/)
      if (numberedMatch) {
        optionText = numberedMatch[1].trim()
      }
    }

    if (optionText && optionText.length > 0) {
      options.push({ text: optionText })
      continue
    }

    if (!/^[\[{]/.test(trimmed) && !trimmed.endsWith(':')) {
      plainFallbackLines.push(trimmed)
    }
  }

  if (options.length === 0 && plainFallbackLines.length > 0) {
    plainFallbackLines.forEach(text => options.push({ text }))
  }

  return options.length > 0 ? options : null
}

/**
 * Remove [OPTIONS] block from content for display
 */
export function removeOptionsBlock(content: string): string {
  return stripChatBlocks(content, 'OPTIONS').trim()
}

/**
 * Render clickable option buttons
 * Every choice group has a free-text escape, including historical/model responses
 * that omitted one. Only the user's actual request is sent to the conversation.
 */
export function OptionButtons({ options, onSelect, disabled }: OptionButtonsProps) {
  const { t } = useTranslation()
  const [isCustomOpen, setIsCustomOpen] = useState(false)
  const [customText, setCustomText] = useState('')
  const customId = useId()
  const useGrid = options.length + 1 > 5
  const buttonClassName = `bg-white border border-gray-200 text-sm font-medium text-gray-700
    hover:bg-blue-50 hover:border-blue-300 hover:text-blue-700
    active:bg-blue-100 active:scale-[0.98]
    disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-150
    ${useGrid ? 'px-3 py-2 rounded-lg text-left break-words' : 'px-4 py-2.5 rounded-xl'}`

  const sendCustomRequest = () => {
    const text = customText.trim()
    if (disabled || !text) return
    onSelect(text)
    setCustomText('')
    setIsCustomOpen(false)
  }

  return (
    <div className="mt-3">
      <div className={useGrid ? 'grid grid-cols-2 sm:grid-cols-3 gap-2' : 'flex flex-wrap gap-2'}>
        {options.map((option, index) => (
          <button
            key={index}
            type="button"
            onClick={() => onSelect(option.text)}
            disabled={disabled}
            className={buttonClassName}
            title={option.text}
          >
            {option.text}
          </button>
        ))}
        <button
          type="button"
          onClick={() => setIsCustomOpen(open => !open)}
          disabled={disabled}
          className={`${buttonClassName} border-dashed`}
          aria-expanded={isCustomOpen}
          aria-controls={customId}
        >
          {t('chatComponents.options.otherRequest')}
        </button>
      </div>
      {isCustomOpen && (
        <div id={customId} className="mt-3 space-y-2">
          <label htmlFor={`${customId}-input`} className="block text-sm text-gray-600">
            {t('chatComponents.options.customLabel')}
          </label>
          <input
            id={`${customId}-input`}
            autoFocus
            type="text"
            value={customText}
            onChange={event => setCustomText(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter' && !event.nativeEvent.isComposing && event.keyCode !== 229) {
                event.preventDefault()
                sendCustomRequest()
              }
            }}
            placeholder={t('chatComponents.options.customPlaceholder')}
            disabled={disabled}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100 disabled:opacity-50"
          />
          <div className="flex gap-2">
            <button type="button" onClick={sendCustomRequest} disabled={disabled || !customText.trim()} className={buttonClassName}>
              {t('chatComponents.options.sendRequest')}
            </button>
            <button type="button" onClick={() => setIsCustomOpen(false)} disabled={disabled} className={buttonClassName}>
              {t('common.cancel')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
