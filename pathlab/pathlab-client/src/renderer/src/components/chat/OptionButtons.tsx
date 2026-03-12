import React from 'react'

import { extractLastChatBlock, stripChatBlocks } from './chatBlockParsing'

interface Option {
  text: string  // The full option text to display and send
}

interface OptionButtonsProps {
  options: Option[]
  onSelect: (text: string) => void
  disabled?: boolean
}

function isDisallowedModelOverflowOption(optionText: string): boolean {
  const normalized = optionText.trim().toLowerCase()
  const mentionsChineseModels = normalized.includes('模型')
  const mentionsEnglishModels = normalized.includes('model')
  const asksForAllChinese = normalized.includes('全部') || normalized.includes('所有')
  const asksForAllEnglish = normalized.includes('show all') || normalized.includes('all models')

  return (mentionsChineseModels && asksForAllChinese) || (mentionsEnglishModels && asksForAllEnglish)
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

  const filteredOptions = options.filter(option => !isDisallowedModelOverflowOption(option.text))

  return filteredOptions.length > 0 ? filteredOptions : null
}

/**
 * Remove [OPTIONS] block from content for display
 */
export function removeOptionsBlock(content: string): string {
  return stripChatBlocks(content, 'OPTIONS').trim()
}

/**
 * Render clickable option buttons
 * Uses flex-wrap for <=5 options, grid layout for >5 options
 */
export function OptionButtons({ options, onSelect, disabled }: OptionButtonsProps) {
  const useGrid = options.length > 5

  if (useGrid) {
    // Grid layout for many options - 2 columns on mobile, 3 on larger screens
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-3">
        {options.map((option, index) => (
          <button
            key={index}
            onClick={() => onSelect(option.text)}
            disabled={disabled}
            className="px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm font-medium text-gray-700
                       hover:bg-blue-50 hover:border-blue-300 hover:text-blue-700
                       active:bg-blue-100 active:scale-[0.98]
                       disabled:opacity-50 disabled:cursor-not-allowed
                       transition-all duration-150 text-left truncate"
            title={option.text}
          >
            {option.text}
          </button>
        ))}
      </div>
    )
  }

  // Flex layout for few options
  return (
    <div className="flex flex-wrap gap-2 mt-3">
      {options.map((option, index) => (
        <button
          key={index}
          onClick={() => onSelect(option.text)}
          disabled={disabled}
          className="px-4 py-2.5 bg-white border border-gray-200 rounded-xl text-sm font-medium text-gray-700
                     hover:bg-blue-50 hover:border-blue-300 hover:text-blue-700
                     active:bg-blue-100 active:scale-[0.98]
                     disabled:opacity-50 disabled:cursor-not-allowed
                     transition-all duration-150"
        >
          {option.text}
        </button>
      ))}
    </div>
  )
}

