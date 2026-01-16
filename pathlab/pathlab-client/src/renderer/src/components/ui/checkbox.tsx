import * as React from "react"
import { Check } from "lucide-react"

import { cn } from "../../lib/utils"

interface CheckboxProps extends React.InputHTMLAttributes<HTMLInputElement> {
    onCheckedChange?: (checked: boolean) => void
    indeterminate?: boolean
}

const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
    ({ className, checked, onCheckedChange, indeterminate, onChange, ...props }, ref) => {

        const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
            if (onCheckedChange) {
                onCheckedChange(e.target.checked)
            }
            if (onChange) {
                onChange(e)
            }
        }

        return (
            <label className="relative flex items-center justify-center w-5 h-5 cursor-pointer group">
                <input
                    type="checkbox"
                    className="peer absolute opacity-0 w-full h-full cursor-pointer z-10"
                    ref={ref}
                    checked={checked}
                    onChange={handleChange}
                    {...props as any}
                />
                {/* Background & Border */}
                <div className={cn(
                    "w-5 h-5 border-[1.5px] rounded-md transition-all duration-200 flex items-center justify-center",
                    "border-slate-300 bg-white group-hover:border-slate-400 peer-focus:ring-2 peer-focus:ring-blue-500/20",
                    checked ? "bg-blue-600 border-blue-600 shadow-sm" : ""
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
