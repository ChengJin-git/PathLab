import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "../../lib/utils/utils"

const cardVariants = cva(
    "rounded-[1.5rem] border text-slate-950 transition-[border-color,box-shadow,background-color] duration-200",
    {
        variants: {
            surface: {
                base: "border-[color:var(--surface-border)] bg-[color:var(--surface-base)] shadow-none",
                work: "border-[color:var(--surface-border)] bg-[color:var(--surface-work)] shadow-[var(--shadow-soft)]",
                elevated: "border-[color:var(--surface-border-strong)] bg-[color:var(--surface-elevated)] shadow-[var(--shadow-elevated)] backdrop-blur-sm",
            },
        },
        defaultVariants: {
            surface: "work",
        },
    }
)

interface CardProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof cardVariants> {}

const Card = React.forwardRef<HTMLDivElement, CardProps>(
    ({ className, surface = "work", ...props }, ref) => (
        <div
            ref={ref}
            data-surface={surface}
            className={cn(cardVariants({ surface }), className)}
            {...props}
        />
    )
)
Card.displayName = "Card"

const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
    ({ className, ...props }, ref) => (
        <div
            ref={ref}
            className={cn("flex flex-col space-y-2 p-5 sm:p-6", className)}
            {...props}
        />
    )
)
CardHeader.displayName = "CardHeader"

const CardTitle = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLHeadingElement>>(
    ({ className, ...props }, ref) => (
        <h3
            ref={ref}
            className={cn(
                "text-xl font-semibold leading-tight tracking-[-0.03em] text-slate-950 sm:text-2xl",
                className
            )}
            {...props}
        />
    )
)
CardTitle.displayName = "CardTitle"

const CardDescription = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(
    ({ className, ...props }, ref) => (
        <p
            ref={ref}
            className={cn("text-sm leading-6 text-slate-500", className)}
            {...props}
        />
    )
)
CardDescription.displayName = "CardDescription"

const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
    ({ className, ...props }, ref) => (
        <div ref={ref} className={cn("p-5 pt-0 sm:p-6 sm:pt-0", className)} {...props} />
    )
)
CardContent.displayName = "CardContent"

const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
    ({ className, ...props }, ref) => (
        <div
            ref={ref}
            className={cn("flex items-center p-5 pt-0 sm:p-6 sm:pt-0", className)}
            {...props}
        />
    )
)
CardFooter.displayName = "CardFooter"

export { Card, CardHeader, CardFooter, CardTitle, CardDescription, CardContent }
