import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "../../lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap rounded-full border text-sm font-medium transition-[background-color,border-color,color,box-shadow,transform] duration-200 ease-out focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary-500/20 focus-visible:ring-offset-2 focus-visible:ring-offset-white disabled:pointer-events-none disabled:opacity-50 motion-reduce:transform-none motion-reduce:transition-none",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-slate-900 text-white shadow-[var(--shadow-soft)] hover:bg-slate-950",
        destructive:
          "border-transparent bg-red-600 text-white shadow-[var(--shadow-soft)] hover:bg-red-700",
        outline:
          "border-[color:var(--surface-border-strong)] bg-[color:var(--surface-elevated)] text-slate-700 shadow-[var(--shadow-soft)] hover:border-primary-200 hover:bg-white hover:text-slate-950",
        secondary:
          "border-transparent bg-[color:var(--surface-muted)] text-slate-700 shadow-[var(--shadow-soft)] hover:bg-[color:var(--surface-base)] hover:text-slate-950",
        ghost: "border-transparent text-slate-600 hover:bg-white/70 hover:text-slate-950",
        link: "border-transparent px-0 text-primary-700 shadow-none underline-offset-4 hover:text-primary-800 hover:underline",
        primary: "border border-primary-500/80 bg-primary-600 text-white shadow-[var(--shadow-soft)] hover:-translate-y-0.5 hover:bg-primary-700 hover:shadow-[var(--shadow-elevated)]"
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-9 rounded-full px-3 text-xs",
        lg: "h-11 rounded-full px-6 text-[15px]",
        icon: "h-10 w-10 rounded-full",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    if (asChild) {
      return (
        <Slot
          className={cn(buttonVariants({ variant, size, className }))}
          data-button-variant={variant ?? "default"}
          data-button-size={size ?? "default"}
          {...props}
        />
      )
    }

    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        data-button-variant={variant ?? "default"}
        data-button-size={size ?? "default"}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
