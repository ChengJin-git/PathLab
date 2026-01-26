import React from 'react'

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
  const match = content.match(/\[OPTIONS\]([\s\S]*?)\[\/OPTIONS\]/)
  if (!match) return null

  const optionsText = match[1]
  const options: Option[] = []

  const lines = optionsText.split('\n')
  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed.startsWith('-')) {
      const optionText = trimmed.slice(1).trim()
      if (optionText.length > 0) {
        options.push({ text: optionText })
      }
    }
  }

  return options.length > 0 ? options : null
}

/**
 * Remove [OPTIONS] block from content for display
 */
export function removeOptionsBlock(content: string): string {
  return content.replace(/\[OPTIONS\][\s\S]*?\[\/OPTIONS\]/g, '').trim()
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

