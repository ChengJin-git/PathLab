import React, { createRef } from "react";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  WorkbenchPicker,
  completionToken,
  type PickerHandle,
} from "../../../../src/renderer/src/components/chat/WorkbenchPicker";
import {
  searchResources,
  searchCommands,
} from "../../../../src/renderer/src/api/workbench";

vi.mock("../../../../src/renderer/src/api/workbench", () => ({
  searchResources: vi.fn(),
  searchCommands: vi.fn(),
}));
const locale = vi.hoisted(() => ({ language: "en-US" }));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ i18n: locale }) }));

beforeEach(() => {
  locale.language = "en-US";
  vi.useFakeTimers();
  vi.mocked(searchResources).mockReset();
  vi.mocked(searchCommands).mockResolvedValue({ items: [], next_cursor: null });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});
const props = {
  value: "@a",
  caret: 2,
  composing: false,
  workspaceId: "ws",
  onChange: vi.fn(),
  onCommand: vi.fn(),
  onReference: vi.fn(),
};
const tick = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(200);
  });

describe("bounded composer autocomplete", () => {
  it('offers conversation references with bounded-context guidance', async () => {
    const selected=vi.fn();
    vi.mocked(searchResources).mockImplementation(async params => ({items: params.kind === 'conversation'
      ? [{kind:'conversation',id:'chat-history',name:'Prior research'}] : [], next_cursor:null}));
    render(<WorkbenchPicker {...props} onReference={selected}/>);
    await tick();
    fireEvent.click(screen.getByRole('button',{name:'Conversations'}));
    await tick();
    expect(searchResources).toHaveBeenLastCalledWith(expect.objectContaining({kind:'conversation',workspace_id:'ws'}),expect.any(AbortSignal));
    expect(screen.getByText(/not the entire conversation/)).toBeVisible();
    fireEvent.click(screen.getByRole('option',{name:'Prior research'}));
    expect(selected).toHaveBeenCalledWith(expect.objectContaining({kind:'conversation',id:'chat-history'}));
  });
  it('selects a custom preloaded skill without routing it to a research-only command', async () => {
    const selected=vi.fn();const command={id:'ugc-handoff',library_skill_id:'ugc-handoff',mode:'skill' as const,name:'Clinical handoff',description:'Use for handoff summaries'}
    vi.mocked(searchCommands).mockResolvedValue({items:[command],next_cursor:null})
    render(<WorkbenchPicker {...props} value="/handoff" caret={8} canExecute={false} onCommand={selected}/>);
    await tick();fireEvent.click(screen.getByRole('option',{name:/Clinical handoff/}))
    expect(selected).toHaveBeenCalledWith(command)
    expect(screen.queryByText('/ugc-handoff')).not.toBeInTheDocument()
  });
  it("reloads localized skill introductions when the UI language changes", async () => {
    vi.mocked(searchCommands).mockImplementation(
      async (_q, _cursor, _signal, language) => ({
        items: [
          {
            id: "nature-statistics",
            skill_id: "nature-statistics",
            mode: "research",
            name: language === "zh-HK" ? "統計審查" : "统计审查",
            description:
              language === "zh-HK"
                ? "審查統計檢定與結果報告。"
                : "审查统计检验与结果报告。",
          },
        ],
        next_cursor: null,
      }),
    );
    locale.language = "zh-CN";
    const view = render(
      <WorkbenchPicker {...props} value="/nature" caret={7} />,
    );
    await tick();
    expect(screen.getByText("审查统计检验与结果报告。")).toBeInTheDocument();
    locale.language = "zh-HK";
    view.rerender(<WorkbenchPicker {...props} value="/nature" caret={7} />);
    await tick();
    expect(screen.getByText("審查統計檢定與結果報告。")).toBeInTheDocument();
    expect(
      screen.queryByText("审查统计检验与结果报告。"),
    ).not.toBeInTheDocument();
    expect(searchCommands).toHaveBeenLastCalledWith(
      "nature",
      "",
      expect.any(AbortSignal),
      "zh-HK",
    );
  });
  it("recognizes commands only at the beginning and avoids email/URL triggers", () => {
    expect(completionToken("/exp", 4)?.query).toBe("exp");
    expect(completionToken("look @cohort", 12)?.query).toBe("cohort");
    expect(completionToken("a@b.com", 7)).toBeNull();
    expect(completionToken("https://site", 12)).toBeNull();
    expect(completionToken("read /tmp", 9)).toBeNull();
    expect(completionToken("分析@队列", 5)?.query).toBe("队列");
  });
  it("cancels stale queries and rejects their late results", async () => {
    let late!: (result: any) => void;
    vi.mocked(searchResources)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            late = resolve;
          }),
      )
      .mockResolvedValueOnce({
        items: [{ kind: "dataset", id: "b", name: "Beta" }],
        next_cursor: null,
      });
    const view = render(<WorkbenchPicker {...props} />);
    await tick();
    const firstSignal = vi.mocked(searchResources).mock.calls[0][1]!;
    view.rerender(<WorkbenchPicker {...props} value="@b" />);
    await tick();
    expect(firstSignal.aborted).toBe(true);
    expect(screen.getByRole("option", { name: "Beta" })).toBeInTheDocument();
    await act(async () => {
      late({
        items: [{ kind: "dataset", id: "a", name: "Stale Alpha" }],
        next_cursor: null,
      });
    });
    expect(screen.queryByText("Stale Alpha")).not.toBeInTheDocument();
  });
  it("does not issue searches during IME composition and scopes file browsing", async () => {
    vi.mocked(searchResources).mockResolvedValue({
      items: [{ kind: "dataset", id: "cohort", name: "Cohort" }],
      next_cursor: null,
    });
    const view = render(<WorkbenchPicker {...props} composing />);
    await tick();
    expect(searchResources).not.toHaveBeenCalled();
    view.rerender(<WorkbenchPicker {...props} />);
    await tick();
    fireEvent.click(
      screen.getByRole("button", { name: "Browse files Cohort" }),
    );
    await tick();
    expect(searchResources).toHaveBeenLastCalledWith(
      expect.objectContaining({
        kind: "slide",
        dataset_id: "cohort",
        workspace_id: "ws",
      }),
      expect.any(AbortSignal),
    );
  });
  it("loads one page at a time and Enter selects without submitting the form", async () => {
    vi.mocked(searchResources)
      .mockResolvedValueOnce({
        items: [{ kind: "dataset", id: "a", name: "Alpha" }],
        next_cursor: "next",
      })
      .mockResolvedValueOnce({
        items: [{ kind: "dataset", id: "b", name: "Beta" }],
        next_cursor: null,
      });
    const ref = createRef<PickerHandle>();
    const selected = vi.fn();
    render(<WorkbenchPicker {...props} ref={ref} onReference={selected} />);
    await tick();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await tick();
    expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
    const event = {
      key: "Enter",
      nativeEvent: { isComposing: false },
      preventDefault: vi.fn(),
    } as any;
    act(() => {
      expect(ref.current!.keyDown(event)).toBe(true);
    });
    expect(event.preventDefault).toHaveBeenCalled();
    expect(selected).toHaveBeenCalledWith(expect.objectContaining({ id: "b" }));
  });
});
