import React from "react";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import ResearchTimeline from "@renderer/components/autoresearch/ResearchTimeline";
import {
  mergeResearchEvents,
  researchTimeline,
} from "@renderer/components/autoresearch/researchActivity";
import type { AutoResearchEvent } from "@renderer/types/autoresearch";
import i18n from "@renderer/i18n";

afterEach(cleanup);

const message = (seq: number, id: string, text: string): AutoResearchEvent => ({
  kind: "message",
  seq,
  message: { id, type: "assistant", text } as unknown as string,
});
const tool = (seq: number): AutoResearchEvent => ({
  kind: "message",
  seq,
  message: {
    id: `m${seq}`,
    type: "assistant",
    content: [
      {
        id: `t${seq}`,
        type: "activity",
        action: "read_source",
        description: `核查第 ${seq} 篇文献的公开验证数据`,
        language: "zh-CN",
        status: "completed",
      },
    ],
  } as unknown as string,
});

it("collapses hundreds of public actions into one bounded, pageable process", async () => {
  await i18n.changeLanguage('en-US');
  const events = [
    message(1, "intro", "Question and initial findings"),
    ...Array.from({ length: 300 }, (_, i) => tool(i + 2)),
    message(302, "result", "Development result"),
  ];
  const { container } = render(
    <ResearchTimeline
      events={events}
      running={false}
      renderProse={(value) => <p>{value}</p>}
    />,
  );
  const process = screen.getByRole("button", { name: 'Execution process' });
  expect(process).toHaveAttribute("aria-expanded", "false");
  expect(container.querySelectorAll("li")).toHaveLength(0);
  expect(screen.getByText("Question and initial findings")).toBeVisible();
  fireEvent.click(process);
  expect(container.querySelectorAll("li")).toHaveLength(20);
  fireEvent.click(screen.getByRole("button", { name: 'Show 280 earlier actions' }));
  expect(container.querySelectorAll("li")).toHaveLength(70);
  expect(container.querySelector("ol")?.parentElement).toHaveClass(
    "max-h-64",
    "overflow-y-auto",
  );
  expect(screen.getByText("Development result")).toBeVisible();
});

it("keeps commands and prose in their original positions across updates and older-page merges", () => {
  const command = {
    kind: "command",
    seq: 2,
    action: "message",
    text: "Add a strong comparator",
    command_id: "c",
    status: "queued",
  };
  const delivery = {
    kind: "command",
    seq: 200,
    command_id: "c",
    status: "delivered",
  };
  const merged = mergeResearchEvents(
    [message(1, "p", "Initial"), command, tool(3)],
    [delivery, message(201, "p", "Updated findings")],
  );
  const withHistory = mergeResearchEvents(merged, [
    message(0, "old", "Older question"),
    command,
  ]);
  expect(withHistory.map((item) => item.activity_seq)).toEqual([0, 1, 2, 3]);
  expect(withHistory[1].message).toMatchObject({ text: "Updated findings" });
  expect(withHistory[2]).toMatchObject({
    text: "Add a strong comparator",
    status: "delivered",
  });
  const refreshed = mergeResearchEvents([delivery], [command]);
  expect(refreshed[0]).toMatchObject({
    text: "Add a strong comparator",
    status: "delivered",
  });
  expect(researchTimeline(withHistory).map((item) => item.type)).toEqual([
    "message",
    "message",
    "command",
    "process",
  ]);
});

it("keeps an expanded group open on status changes and preserves historical summaries", async () => {
  await i18n.changeLanguage('en-US');
  const events = [
    tool(1),
    { kind: "report", seq: 2, text: "Prior round result" },
    {
      kind: "command",
      seq: 3,
      action: "message",
      command_id: "c",
      text: "Continue with ablations",
    },
  ];
  const props = { events, renderProse: (value: string) => <p>{value}</p> };
  const { rerender } = render(<ResearchTimeline {...props} running />);
  fireEvent.click(screen.getByRole("button", { name: 'Execution process' }));
  act(() => rerender(<ResearchTimeline {...props} running={false} />));
  expect(
    screen.getByRole("button", { name: 'Execution process' }),
  ).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("Prior round result")).toBeVisible();
  expect(screen.getByText("Continue with ablations")).toBeVisible();
});

it("shows localized decisions and one current public topic without a background-task list", async () => {
  await i18n.changeLanguage('zh-CN');
  const events: AutoResearchEvent[] = [
    { kind: "native_work", seq: 1, status: "running", description: "核查疗效空间证据", language: "zh-CN" },
    { kind: "research_decision", seq: 2, decision: {
      action: "pivot", assessment: "inconclusive", scope: "candidate", observation: "No validation gain", interpretation: "Frozen representation may hide the signal",
      next_action: "Train the encoder with consistency loss", run_ids: ["real-run"],
    } },
    { kind: "native_work", seq: 3, status: "running", description: "核查公开数据资源", language: "zh-CN" },
  ];
  const view = render(<ResearchTimeline events={events} running renderProse={(value) => <p>{value}</p>} />);
  expect(screen.getByText("No validation gain")).toBeVisible();
  expect(screen.getByText("Train the encoder with consistency loss")).toBeVisible();
  expect(screen.getByText("转向另一研究方向")).toBeVisible();
  expect(screen.getByText("现有证据尚不能定论")).toBeVisible();
  expect(screen.getAllByText("核查公开数据资源")).toHaveLength(1);
  expect(screen.queryByText("核查疗效空间证据")).not.toBeInTheDocument();
  expect(view.container.textContent).not.toMatch(/native_work|pivot|real-run| · /);
  view.rerender(<ResearchTimeline events={[...events, {kind: 'native_work', seq: 4, status: 'completed'}]} running renderProse={value => <p>{value}</p>} />);
  expect(screen.queryByText("核查公开数据资源")).not.toBeInTheDocument();
  expect(screen.getByText("研究仍在进行")).toBeVisible();
});

it("never renders raw tool payloads and localizes descriptions immediately when language changes", async () => {
  await i18n.changeLanguage('zh-CN');
  const events = [tool(1), tool(2), { kind: 'message', seq: 3, message: { id: 'private', type: 'assistant', content: [
    { type: 'tool', name: 'get_research_context', state: {input: {path: '/private'}, output: 'SECRET'} },
    { type: 'activity', action: 'search_sources', status: 'running', description: 'Risom 2022 transition invasive breast cancer', language: 'zh-CN' },
  ]} as unknown as string }];
  const view = render(<ResearchTimeline events={events} running renderProse={value => <p>{value}</p>} />);
  const button = screen.getByRole('button', {name: '执行过程'});
  expect(button).toHaveTextContent('查找相关资料');
  expect(button).not.toHaveTextContent('核查第');
  fireEvent.click(button);
  expect(screen.getByText('核查第 1 篇文献的公开验证数据')).toBeVisible();
  expect(view.container.innerHTML).not.toMatch(/get_research_context|SECRET|\/private|Risom|步骤详情/);
  await act(async () => { await i18n.changeLanguage('en-US'); });
  expect(screen.getByRole('button', {name: 'Execution process'})).toHaveTextContent('Search relevant sources');
  expect(within(screen.getByRole('list')).getAllByText('Read the source material')).toHaveLength(2);
  expect(view.container.textContent).not.toContain('核查第');
  await act(async () => { await i18n.changeLanguage('zh-HK'); });
  expect(screen.getByRole('button', {name: '執行過程'})).toHaveTextContent('查找相關資料');
  expect(within(screen.getByRole('list')).getAllByText('閱讀來源內容')).toHaveLength(2);
});

it("retains failure and interrupted states instead of showing raw errors or false completion", async () => {
  await i18n.changeLanguage('zh-CN');
  const events = [{ kind: 'message', seq: 1, message: { id: 'm', type: 'assistant', content: [
    {type: 'activity', id: 'f', action: 'read_source', description: '核查患者队列', language: 'zh-CN', status: 'failed'},
    {type: 'activity', id: 'r', action: 'search_data', status: 'running'},
  ]} as unknown as string }];
  const view = render(<ResearchTimeline events={events} running renderProse={value => <p>{value}</p>} />);
  fireEvent.click(screen.getByRole('button', {name: '执行过程'}));
  expect(within(screen.getByRole('list')).getByText('未完成')).toBeVisible();
  view.rerender(<ResearchTimeline events={events} running={false} renderProse={value => <p>{value}</p>} />);
  expect(within(screen.getByRole('list')).getByText('已中断')).toBeVisible();
  expect(screen.queryByText('已完成')).not.toBeInTheDocument();
});
