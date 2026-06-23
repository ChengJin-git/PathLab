import * as React from "react"
import * as ReactDOM from "react-dom"
import { ChevronDown, Check } from "lucide-react"
import { cn } from "../../lib/utils"

export interface SelectOption {
    value: string
    label: string
    disabled?: boolean
}

export interface SelectOptionGroup {
    group: string
    options: SelectOption[]
}

export interface SelectProps {
    value: string
    onChange: (value: string) => void
    options: readonly SelectOption[] | readonly SelectOptionGroup[]
    placeholder?: string
    className?: string
    triggerClassName?: string
    dropdownClassName?: string
    disabled?: boolean
    ariaLabel?: string
}

function isGroupedOptions(
    opts: readonly SelectOption[] | readonly SelectOptionGroup[]
): opts is readonly SelectOptionGroup[] {
    return opts.length > 0 && "group" in opts[0]
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
    ariaLabel,
}: SelectProps) {
    const [isOpen, setIsOpen] = React.useState(false)
    const [dropdownStyle, setDropdownStyle] = React.useState<React.CSSProperties>({})
    const triggerRef = React.useRef<HTMLButtonElement>(null)
    const dropdownRef = React.useRef<HTMLDivElement>(null)

    const flatOptions: SelectOption[] = isGroupedOptions(options)
        ? options.flatMap((g) => [...g.options])
        : [...options]

    const selectedOption = flatOptions.find((opt) => opt.value === value)
    const listboxId = React.useId()

    React.useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as Node
            if (
                triggerRef.current && !triggerRef.current.contains(target) &&
                dropdownRef.current && !dropdownRef.current.contains(target)
            ) {
                setIsOpen(false)
            }
        }

        document.addEventListener("mousedown", handleClickOutside)
        return () => document.removeEventListener("mousedown", handleClickOutside)
    }, [])

    React.useEffect(() => {
        if (!isOpen) return
        const updatePosition = () => {
            if (triggerRef.current) {
                const rect = triggerRef.current.getBoundingClientRect()
                setDropdownStyle({
                    position: "fixed",
                    top: rect.bottom + 4,
                    left: rect.left,
                    width: rect.width,
                    zIndex: 9999,
                })
            }
        }
        // capture:true catches scroll on any ancestor, not just window
        window.addEventListener("scroll", updatePosition, true)
        return () => window.removeEventListener("scroll", updatePosition, true)
    }, [isOpen])

    const handleOpen = () => {
        if (disabled) return
        if (!isOpen && triggerRef.current) {
            const rect = triggerRef.current.getBoundingClientRect()
            setDropdownStyle({
                position: "fixed",
                top: rect.bottom + 4,
                left: rect.left,
                width: rect.width,
                zIndex: 9999,
            })
        }
        setIsOpen((prev) => !prev)
    }

    const handleSelect = (optionValue: string) => {
        onChange(optionValue)
        setIsOpen(false)
    }

    const renderOption = (option: SelectOption) => (
        <button
            key={option.value}
            type="button"
            onClick={() => handleSelect(option.value)}
            disabled={option.disabled}
            role="option"
            aria-selected={option.value === value}
            className={cn(
                "relative flex w-full cursor-default select-none items-center rounded-sm py-1.5 pl-2 pr-8 text-sm outline-none hover:bg-gray-100 hover:text-gray-900 disabled:pointer-events-none disabled:opacity-50",
                option.value === value && "font-medium bg-gray-50"
            )}
        >
            <span className="truncate">{option.label}</span>
            {option.value === value && (
                <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center text-primary-600">
                    <Check className="h-4 w-4" />
                </span>
            )}
        </button>
    )

    const dropdownContent = isOpen && ReactDOM.createPortal(
        <div
            ref={dropdownRef}
            style={dropdownStyle}
            role="listbox"
            id={listboxId}
            className={cn(
                "max-h-60 overflow-auto rounded-[1.25rem] border border-[color:var(--surface-border-strong)] bg-[color:var(--surface-elevated)] p-1.5 shadow-[var(--shadow-elevated)] animate-in fade-in-0 zoom-in-95",
                dropdownClassName
            )}
        >
            {flatOptions.length === 0 ? (
                <div className="py-2 px-2 text-sm text-gray-500 text-center">
                    No options
                </div>
            ) : isGroupedOptions(options) ? (
                options.map((group) => (
                    <div key={group.group}>
                        <div className="px-2 py-1 text-xs font-semibold text-gray-400 uppercase tracking-wider select-none">
                            {group.group}
                        </div>
                        {group.options.map(renderOption)}
                    </div>
                ))
            ) : (
                options.map(renderOption)
            )}
        </div>,
        document.body
    )

    return (
        <div className={cn("relative", className)}>
            <button
                ref={triggerRef}
                type="button"
                onClick={handleOpen}
                disabled={disabled}
                aria-label={ariaLabel}
                aria-expanded={isOpen}
                aria-haspopup="listbox"
                aria-controls={isOpen ? listboxId : undefined}
                className={cn(
                    "flex h-11 w-full items-center justify-between rounded-[1rem] border border-[color:var(--surface-border-strong)] bg-[color:var(--surface-elevated)] px-4 py-2 text-sm text-slate-700 shadow-[var(--shadow-soft)] transition-[border-color,box-shadow,background-color] duration-200 focus-visible:outline-none focus-visible:border-primary-300 focus-visible:ring-4 focus-visible:ring-primary-500/30 disabled:cursor-not-allowed disabled:opacity-50 hover:bg-white",
                    isOpen && "border-primary-300 ring-4 ring-primary-500/20",
                    triggerClassName
                )}
            >
                <span className={cn("block truncate", !selectedOption && "text-gray-400")}>
                    {selectedOption ? selectedOption.label : placeholder}
                </span>
                <ChevronDown className="h-4 w-4 opacity-50 shrink-0" />
            </button>

            {dropdownContent}
        </div>
    )
}
