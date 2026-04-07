import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "../../lib/utils"
import { motion } from "framer-motion"

const buttonVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap rounded-full text-sm font-medium focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gray-950 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "bg-gray-900 text-gray-50 shadow hover:bg-gray-900/90",
        destructive:
          "bg-red-500 text-gray-50 shadow-sm hover:bg-red-500/90",
        outline:
          "border border-gray-200 bg-white shadow-sm hover:bg-gray-100/80 hover:text-gray-900",
        secondary:
          "bg-gray-100 text-gray-900 shadow-sm hover:bg-gray-100/80",
        ghost: "hover:bg-gray-100 hover:text-gray-900",
        link: "text-gray-900 underline-offset-4 hover:underline",
        primary: "bg-primary-600 text-white shadow hover:bg-primary-600/90"
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 rounded-full px-3 text-xs",
        lg: "h-10 rounded-full px-8",
        icon: "h-9 w-9",
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

const MotionSlot = motion.create(Slot)

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const springTransition = { type: "spring", stiffness: 400, damping: 25 }

    if (asChild) {
      return (
        <MotionSlot
          className={cn(buttonVariants({ variant, size, className }))}
          ref={ref as any}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.95 }}
          transition={springTransition}
          {...(props as any)}
        />
      )
    }

    return (
      <motion.button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        whileHover={{ scale: 1.02 }}
        whileTap={{ scale: 0.95 }}
        transition={springTransition}
        {...(props as any)}
      />
    )
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
