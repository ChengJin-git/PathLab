import * as React from "react";
import * as Popover from "@radix-ui/react-popover";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "../../lib/utils/utils";
import "./form-controls.css";

export interface SelectOption {
  value: string;
  label: string;
  description?: string;
  disabled?: boolean;
}
export interface SelectOptionGroup {
  group: string;
  options: SelectOption[];
}
export interface SelectProps {
  value: string;
  onChange: (value: string) => void;
  options: readonly SelectOption[] | readonly SelectOptionGroup[];
  placeholder?: string;
  className?: string;
  triggerClassName?: string;
  dropdownClassName?: string;
  disabled?: boolean;
  showDescription?: boolean;
  ariaLabel?: string;
  id?: string;
}

function grouped(
  options: SelectProps["options"],
): options is readonly SelectOptionGroup[] {
  return options.length > 0 && "group" in options[0];
}

/** One listbox for app and desktop setup: collision-aware, portal-safe and keyboard operable. */
export function Select({
  value,
  onChange,
  options,
  placeholder = "—",
  className,
  triggerClassName,
  dropdownClassName,
  disabled = false,
  showDescription = false,
  ariaLabel,
  id,
}: SelectProps) {
  const [open, setOpen] = React.useState(false);
  const trigger = React.useRef<HTMLButtonElement>(null);
  const list = React.useRef<HTMLDivElement>(null);
  const initialIndex = React.useRef(0);
  const typeahead = React.useRef({ text: "", at: 0 });
  const listId = React.useId();
  const flat = grouped(options)
    ? options.flatMap((group) => group.options)
    : [...options];
  const enabled = flat.filter((option) => !option.disabled);
  const selected = flat.find((option) => option.value === value);

  React.useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);
  const focus = (index: number) => {
    const items = list.current?.querySelectorAll<HTMLButtonElement>(
      '[role="option"]:not(:disabled)',
    );
    items?.[index]?.focus();
    items?.[index]?.scrollIntoView?.({ block: "nearest" });
  };
  const choose = (option: SelectOption) => {
    if (option.disabled) return;
    onChange(option.value);
    trigger.current?.focus();
    setOpen(false);
  };
  const search = (key: string, from: number) => {
    const now = Date.now();
    const previous =
      now - typeahead.current.at < 700 ? typeahead.current.text : "";
    const text = previous === key ? key : previous + key;
    typeahead.current = { text, at: now };
    for (let step = 1; step <= enabled.length; step++) {
      const index = (from + step) % enabled.length;
      if (
        enabled[index].label
          .toLocaleLowerCase()
          .startsWith(text.toLocaleLowerCase())
      )
        return index;
    }
    return -1;
  };
  const openAt = (index: number) => {
    initialIndex.current = Math.max(0, index);
    setOpen(true);
  };
  const option = (item: SelectOption) => (
    <button
      key={item.value}
      type="button"
      role="option"
      aria-selected={item.value === value}
      disabled={item.disabled}
      tabIndex={-1}
      className="pathlab-select-option"
      onClick={() => choose(item)}
    >
      <span className="pathlab-select-option-text">
        <span>{item.label}</span>
        {showDescription && item.description && (
          <span className="pathlab-select-description">{item.description}</span>
        )}
      </span>
      {item.value === value && <Check size={16} aria-hidden="true" />}
    </button>
  );

  return (
    <Popover.Root
      open={open && !disabled}
      onOpenChange={(next) => {
        initialIndex.current = Math.max(
          0,
          enabled.findIndex((item) => item.value === value),
        );
        setOpen(next);
      }}
    >
      <span className={cn("pathlab-select", className)}>
        <Popover.Trigger asChild>
          <button
            ref={trigger}
            id={id}
            type="button"
            disabled={disabled}
            aria-label={ariaLabel}
            aria-haspopup="listbox"
            aria-expanded={open && !disabled}
            aria-controls={open ? listId : undefined}
            className={cn("pathlab-select-trigger", triggerClassName)}
            onKeyDown={(event) => {
              if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
                event.preventDefault();
                openAt(
                  event.key === "End"
                    ? enabled.length - 1
                    : event.key === "Home"
                      ? 0
                      : enabled.findIndex((item) => item.value === value) >= 0
                        ? enabled.findIndex((item) => item.value === value)
                        : event.key === "ArrowUp"
                          ? enabled.length - 1
                          : 0,
                );
              } else if (
                event.key.length === 1 &&
                event.key !== " " &&
                !event.ctrlKey &&
                !event.metaKey &&
                !event.altKey
              ) {
                const index = search(
                  event.key,
                  enabled.findIndex((item) => item.value === value),
                );
                if (index >= 0) {
                  event.preventDefault();
                  choose(enabled[index]);
                }
              }
            }}
          >
            <span
              className={cn(
                "pathlab-select-value",
                !selected && "pathlab-select-placeholder",
              )}
            >
              {showDescription && selected?.description ? (
                <>
                  <span className="pathlab-select-label">{selected.label}</span>
                  <span className="pathlab-select-description">
                    {selected.description}
                  </span>
                </>
              ) : (
                (selected?.label ?? placeholder)
              )}
            </span>
            <ChevronDown size={16} aria-hidden="true" />
          </button>
        </Popover.Trigger>
        <Popover.Portal container={trigger.current?.closest<HTMLElement>('[role="dialog"]') ?? undefined}>
          <Popover.Content
            ref={list}
            id={listId}
            role="listbox"
            aria-label={ariaLabel}
            sideOffset={6}
            align="start"
            collisionPadding={12}
            className={cn("pathlab-select-menu", dropdownClassName)}
            onOpenAutoFocus={(event) => {
              event.preventDefault();
              focus(initialIndex.current);
            }}
            onCloseAutoFocus={(event) => {
              event.preventDefault();
            }}
            onEscapeKeyDown={(event) => {
              event.stopPropagation();
              trigger.current?.focus();
            }}
            onKeyDown={(event) => {
              const items = Array.from(
                list.current?.querySelectorAll<HTMLButtonElement>(
                  '[role="option"]:not(:disabled)',
                ) || [],
              );
              const index = items.indexOf(
                document.activeElement as HTMLButtonElement,
              );
              if (event.key === "Tab") {
                setOpen(false);
                trigger.current?.focus();
                return;
              }
              if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
                event.preventDefault();
                focus(
                  event.key === "Home"
                    ? 0
                    : event.key === "End"
                      ? items.length - 1
                      : (index +
                          (event.key === "ArrowDown" ? 1 : -1) +
                          items.length) %
                        items.length,
                );
              } else if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                if (enabled[index]) choose(enabled[index]);
                trigger.current?.focus();
              } else if (
                event.key.length === 1 &&
                !event.ctrlKey &&
                !event.metaKey &&
                !event.altKey
              ) {
                const next = search(event.key, index);
                if (next >= 0) {
                  event.preventDefault();
                  focus(next);
                }
              }
            }}
          >
            {grouped(options)
              ? options.map((group) => (
                  <div role="group" aria-label={group.group} key={group.group}>
                    <div className="pathlab-select-group">{group.group}</div>
                    {group.options.map(option)}
                  </div>
                ))
              : options.map(option)}
            {!flat.length && (
              <span className="pathlab-select-empty">{placeholder}</span>
            )}
          </Popover.Content>
        </Popover.Portal>
      </span>
    </Popover.Root>
  );
}
