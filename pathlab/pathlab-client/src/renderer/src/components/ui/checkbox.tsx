import * as React from "react"
import { Check } from "lucide-react"

import { cn } from "../../lib/utils"

interface CheckboxProps extends React.InputHTMLAttributes<HTMLInputElement> {
    onCheckedChange?: (checked: boolean) => void
    indeterminate?: boolean
}

const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
    ({ className, checked, onCheckedChange, indeterminate, onChange, disabled, ...props }, ref) => {

        const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
            e.stopPropagation()
            if (onCheckedChange) {
                onCheckedChange(e.target.checked)
            }
            if (onChange) {
                onChange(e)
            }
        }

        return (
            <label className={cn("relative flex items-center justify-center w-5 h-5 group", disabled ? "cursor-not-allowed" : "cursor-pointer")}>
                <input
                    type="checkbox"
                    className={cn("peer absolute opacity-0 w-full h-full z-10", disabled ? "cursor-not-allowed" : "cursor-pointer")}
                    ref={ref}
                    checked={checked}
                    disabled={disabled}
                    onClick={(e) => e.stopPropagation()}
                    onChange={handleChange}
                    {...props as any}
                />
                {/* Background & Border */}
                <div className={cn(
                    "w-5 h-5 border-[1.5px] rounded border-gray-300 bg-white transition-all duration-200 flex items-center justify-center shadow-sm",
                    !disabled && "group-hover:border-gray-400",
                    "peer-focus:ring-2 peer-focus:ring-gray-950/20",
                    checked ? "bg-gray-900 border-gray-900" : "",
                    disabled ? "opacity-40" : ""
                )}>
                    {/* Check Icon */}
                    <Check
                        className={cn(
                            "w-3.5 h-3.5 text-white transition-all duration-200",
                            checked ? "scale-100 opacity-100" : "scale-50 opacity-0"
                        )}
                        strokeWidth={3}
                    />
                </div>

                {/* Indeterminate State (Optional visual) */}
                {indeterminate && !checked && (
                    <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                        <div className="w-2.5 h-2.5 bg-blue-600 rounded-sm opacity-50" />
                    </div>
                )}
            </label>
        )
    }
)
Checkbox.displayName = "Checkbox"

export { Checkbox }
