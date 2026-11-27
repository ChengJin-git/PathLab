import * as React from "react"
import { cn } from "../../lib/utils/utils"

export interface InputProps
    extends React.InputHTMLAttributes<HTMLInputElement> { }

const Input = React.forwardRef<HTMLInputElement, InputProps>(
    ({ className, type, ...props }, ref) => {
        return (
            <input
                type={type}
                data-premium-field="true"
                className={cn(
                    "flex h-11 w-full rounded-[1rem] border border-[color:var(--surface-border-strong)] bg-[color:var(--surface-elevated)] px-4 py-2 text-sm text-slate-700 shadow-[var(--shadow-soft)] transition-[border-color,box-shadow,background-color] duration-200 file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-slate-400 focus-visible:outline-none focus-visible:border-primary-300 focus-visible:ring-4 focus-visible:ring-primary-500/30 disabled:cursor-not-allowed disabled:border-[color:var(--surface-border)] disabled:bg-[color:var(--surface-muted)] disabled:text-slate-400 disabled:shadow-none",
                    className
                )}
                ref={ref}
                {...props}
            />
        )
    }
)
Input.displayName = "Input"

export { Input }
