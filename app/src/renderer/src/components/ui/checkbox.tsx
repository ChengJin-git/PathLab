import * as React from "react";
import { cn } from "../../lib/utils/utils";
import "./form-controls.css";

interface CheckboxProps extends Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  "type"
> {
  onCheckedChange?: (checked: boolean) => void;
  indeterminate?: boolean;
}

/** Keep native form, label and keyboard semantics, with one visual treatment. */
export const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  (
    {
      className,
      onCheckedChange,
      indeterminate = false,
      onChange,
      onClick,
      ...props
    },
    ref,
  ) => {
    const input = React.useRef<HTMLInputElement | null>(null);
    React.useLayoutEffect(() => {
      if (input.current) input.current.indeterminate = indeterminate;
    }, [indeterminate, props.checked]);
    return (
      <input
        {...props}
        type="checkbox"
        className={cn("pathlab-checkbox", className)}
        ref={(node) => {
          input.current = node;
          if (typeof ref === "function") ref(node);
          else if (ref) ref.current = node;
        }}
        onClick={(event) => {
          event.stopPropagation();
          onClick?.(event);
        }}
        onChange={(event) => {
          onCheckedChange?.(event.target.checked);
          onChange?.(event);
        }}
      />
    );
  },
);
Checkbox.displayName = "Checkbox";
