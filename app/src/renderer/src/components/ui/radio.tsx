import * as React from "react";
import { cn } from "../../lib/utils/utils";
import "./form-controls.css";

export const Radio = React.forwardRef<
  HTMLInputElement,
  Omit<React.InputHTMLAttributes<HTMLInputElement>, "type">
>(({ className, ...props }, ref) => (
  <input
    {...props}
    ref={ref}
    type="radio"
    className={cn("pathlab-radio", className)}
  />
));
Radio.displayName = "Radio";
