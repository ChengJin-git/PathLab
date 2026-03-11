import * as React from "react"
import { ChevronDown, Check } from "lucide-react"
import { cn } from "../../lib/utils"

export interface SelectOption {
    value: string
    label: string
}

export interface SelectProps {
    value: string
    onChange: (value: string) => void
    options: SelectOption[]
    placeholder?: string
    className?: string
    triggerClassName?: string
    dropdownClassName?: string
    disabled?: boolean
}

export function Select({
    value,
    onChange,
    options,
    placeholder = "Select...",
    className,
    triggerClassName,
    dropdownClassName,
    disabled = false,
}: SelectProps) {
    const [isOpen, setIsOpen] = React.useState(false)
    const containerRef = React.useRef<HTMLDivElement>(null)

    const selectedOption = options.find((opt) => opt.value === value)

    React.useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (
                containerRef.current &&
                !containerRef.current.contains(event.target as Node)
            ) {
                setIsOpen(false)
            }
        }

        document.addEventListener("mousedown", handleClickOutside)
        return () => {
            document.removeEventListener("mousedown", handleClickOutside)
        }
    }, [])

    const handleSelect = (optionValue: string) => {
        onChange(optionValue)
        setIsOpen(false)
    }

    return (
        <div className={cn("relative", className)} ref={containerRef}>
            <button
                type="button"
                onClick={() => !disabled && setIsOpen(!isOpen)}
                disabled={disabled}
                className={cn(
                    "flex h-9 w-full items-center justify-between rounded-lg border border-gray-200 bg-white px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gray-950 disabled:cursor-not-allowed disabled:opacity-50 hover:bg-gray-50",
                    isOpen && "ring-1 ring-gray-950 border-gray-400",
                    triggerClassName
                )}
            >
                <span className={cn("block truncate", !selectedOption && "text-gray-400")}>
                    {selectedOption ? selectedOption.label : placeholder}
                </span>
                <ChevronDown className="h-4 w-4 opacity-50" />
            </button>

            {isOpen && (
                <div className={cn(
                    "absolute z-50 mt-1 max-h-60 w-full overflow-auto rounded-md border border-gray-200 bg-white p-1 shadow-lg animate-in fade-in-0 zoom-in-95 data-[side=bottom]:slide-in-from-top-2",
                    dropdownClassName
                )}>
                    {options.length === 0 ? (
                        <div className="py-2 px-2 text-sm text-gray-500 text-center">
                            No options
                        </div>
                    ) : (
                        options.map((option) => (
                            <div
                                key={option.value}
                                onClick={() => handleSelect(option.value)}
                                className={cn(
                                    "relative flex cursor-default select-none items-center rounded-sm py-1.5 pl-2 pr-8 text-sm outline-none hover:bg-gray-100 hover:text-gray-900 data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
                                    option.value === value && "font-medium bg-gray-50"
                                )}
                            >
                                <span className="truncate">{option.label}</span>
                                {option.value === value && (
                                    <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center text-primary-600">
                                        <Check className="h-4 w-4" />
                                    </span>
                                )}
                            </div>
                        ))
                    )}
                </div>
            )}
        </div>
    )
}
