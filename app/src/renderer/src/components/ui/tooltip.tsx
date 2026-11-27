import * as React from "react"
import * as TooltipPrimitive from "@radix-ui/react-tooltip"
import { cn } from "../../lib/utils/utils"

const TooltipProvider = TooltipPrimitive.Provider
const TooltipRoot = TooltipPrimitive.Root
const TooltipTrigger = TooltipPrimitive.Trigger

const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 6, children, ...props }, ref) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        "z-50 rounded-lg px-2.5 py-1.5 max-w-[220px] break-words text-center",
        "bg-[#1c1c2e]/[0.97] text-[11px] font-medium leading-snug tracking-wide text-white",
        "shadow-lg shadow-black/30 border border-white/[0.07]",
        "data-[state=delayed-open]:animate-tooltip-in",
        "data-[state=instant-open]:animate-tooltip-in",
        "data-[state=closed]:animate-tooltip-out",
        "data-[side=top]:origin-bottom data-[side=bottom]:origin-top",
        "data-[side=left]:origin-right data-[side=right]:origin-left",
        className
      )}
      {...props}
    >
      {children}
      <TooltipPrimitive.Arrow className="fill-[#1c1c2e]/[0.97]" width={8} height={4} />
    </TooltipPrimitive.Content>
  </TooltipPrimitive.Portal>
))
TooltipContent.displayName = "TooltipContent"

export interface TooltipProps {
  children: React.ReactElement
  content: React.ReactNode
  side?: "top" | "bottom" | "left" | "right"
  align?: "start" | "center" | "end"
  sideOffset?: number
  delayDuration?: number
  contentClassName?: string
  disabled?: boolean
}

function Tooltip({
  children,
  content,
  side = "top",
  align = "center",
  sideOffset = 6,
  delayDuration = 400,
  contentClassName,
  disabled = false,
}: TooltipProps) {
  if (!content || disabled) return children

  return (
    <TooltipRoot delayDuration={delayDuration}>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side} align={align} sideOffset={sideOffset} className={contentClassName}>
        {content}
      </TooltipContent>
    </TooltipRoot>
  )
}

export { TooltipProvider, TooltipRoot, TooltipTrigger, TooltipContent, Tooltip }
