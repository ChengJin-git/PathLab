import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import * as Dialog from "@radix-ui/react-dialog";
import { Select } from "@renderer/components/ui/select";

it("supports keyboard selection, disabled options, typeahead and Escape inside a modal", async () => {
  const user = userEvent.setup(),
    change = vi.fn(),
    close = vi.fn();
  render(
    <Dialog.Root open onOpenChange={close}>
      <Dialog.Portal>
        <Dialog.Content aria-describedby={undefined}>
          <Dialog.Title>Preferences</Dialog.Title>
          <Select
            ariaLabel="Mode"
            value="a"
            onChange={change}
            options={[
              { value: "a", label: "Alpha" },
              { value: "b", label: "Beta", disabled: true },
              { value: "c", label: "Charlie" },
            ]}
          />
          <button>Next field</button>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>,
  );
  screen.getByRole("button", { name: "Mode" }).focus();
  await user.keyboard("{ArrowDown}");
  await waitFor(() =>
    expect(screen.getByRole("option", { name: "Alpha" })).toHaveFocus(),
  );
  await user.keyboard("{ArrowDown}{Enter}");
  expect(change).toHaveBeenLastCalledWith("c");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Mode" })).toHaveFocus();
  await user.keyboard("{ArrowDown}{Escape}");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(close).not.toHaveBeenCalled();
  await user.keyboard("c");
  expect(change).toHaveBeenLastCalledWith("c");
});

it("shows optional result metadata without using it as the selected value", async () => {
  const user = userEvent.setup(),
    change = vi.fn();
  render(
    <Select
      value="fold_0"
      onChange={change}
      ariaLabel="Result"
      showDescription
      options={[
        { value: "fold_0", label: "Same result", description: "Fold 0" },
        { value: "fold_1", label: "Same result", description: "Fold 1" },
      ]}
    />,
  );
  const trigger = screen.getByRole("button", { name: "Result" });
  expect(trigger).toHaveTextContent("Same resultFold 0");
  trigger.focus();
  await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");
  expect(change).toHaveBeenCalledWith("fold_1");
  expect(trigger).toHaveFocus();
});
