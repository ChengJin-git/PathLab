import * as React from "react"
import { cn } from "../../lib/utils"

interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
    variant?: "default" | "secondary" | "destructive" | "outline"
}

function Badge({ className, variant = "default", ...props }: BadgeProps) {
    const variants = {
        default: "border border-primary-200 bg-primary-50 text-primary-800",
        secondary: "border border-secondary-200 bg-secondary-50 text-secondary-800",
        destructive: "border border-red-200 bg-red-50 text-red-700",
        outline: "border-[color:var(--surface-border-strong)] bg-white/80 text-slate-700",
    }

    return (
        <div
            className={cn(
                "inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:ring-offset-2",
                variants[variant],
                className
            )}
            {...props}
        />
    )
}

export { Badge }
