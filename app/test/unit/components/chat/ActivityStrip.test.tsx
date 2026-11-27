import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import ActivityStrip from "@renderer/components/chat/ActivityStrip";
import { summarizeChatActivity } from "@renderer/components/chat/chatActivity";
import type { ChatActivity } from "@renderer/api/chat";
import i18n from "@renderer/i18n";

afterEach(cleanup);
const item = (id: string, operation: ChatActivity["operation"], status: ChatActivity["status"] = "completed", subject = ""): ChatActivity => ({
  id, operation, status, subject,
});
const internal = { detail: "INTERNAL_SENTINEL /srv/private/context.json token=secret tool=load_capability" };

it("describes each search and article while omitting internal preparation and payloads", async () => {
  await i18n.changeLanguage("zh-CN");
  const items = [
    item("context", "context", "completed", "private system prompt"),
    item("connector", "tool", "completed", "LOAD_CAPABILITY"),
    item("search1", "search", "completed", "空间蛋白组 foundation model"),
    item("search2", "search", "completed", "Spatium 公开验证数据"),
    { ...item("read", "read", "running", "Spatium: A Protein Language Foundation Model"), ...internal },
  ];
  const view = render(<ActivityStrip items={items} running />);
  const toggle = screen.getByRole("button", { name: "处理过程" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByRole("list")).not.toBeInTheDocument();
  expect(toggle).toHaveTextContent("正在阅读《Spatium: A Protein Language Foundation Model》");
  fireEvent.click(toggle);
  expect(screen.getAllByRole("listitem")).toHaveLength(3);
  const list = screen.getByRole("list");
  expect(list).toHaveTextContent("已搜索“空间蛋白组 foundation model”相关资料");
  expect(list).toHaveTextContent("已搜索“Spatium 公开验证数据”相关资料");
  expect(view.container.innerHTML).not.toMatch(/INTERNAL_SENTINEL|context\.json|secret|load_capability|LOAD_CAPABILITY|private system prompt/);
  expect(view.container.textContent).not.toContain(" · ");
  view.rerender(<ActivityStrip items={[...items.map(value => ({ ...value, status: "completed" as const })), item("model", "respond")]} />);
  expect(toggle).toHaveTextContent("已阅读《Spatium: A Protein Language Foundation Model》");
  expect(within(list).queryByText("进行中")).not.toBeInTheDocument();
  expect(toggle).toHaveAttribute("aria-controls", list.parentElement!.id);
});

it("changes the concrete current action immediately without an exit-animation wait", async () => {
  await i18n.changeLanguage("en-US");
  const view = render(<ActivityStrip items={[item("search", "search", "running", "spatial proteomics")]} running />);
  expect(screen.getByRole("button")).toHaveTextContent("Searching for “spatial proteomics”");
  view.rerender(<ActivityStrip items={[item("search", "search"), item("read", "read", "running", "HEIST")]} running />);
  expect(screen.getByRole("button")).toHaveTextContent("Reading “HEIST”");
  expect(screen.getByRole("button")).not.toHaveTextContent("spatial proteomics");
});

it("keeps a failed lookup visible after a response succeeds, without calling it active", async () => {
  await i18n.changeLanguage("zh-CN");
  render(<ActivityStrip items={[item("failed-search", "search", "failed", "Spatium"), item("good-search", "search", "completed", "HEIST"), item("model", "respond")]} />);
  const toggle = screen.getByRole("button", { name: "处理过程" });
  expect(toggle).toHaveTextContent("有步骤未完成");
  fireEvent.click(toggle);
  expect(screen.getByText("未能完成“Spatium”的资料检索")).toBeInTheDocument();
  expect(screen.queryByText(/正在/)).not.toBeInTheDocument();
});

it("does not mark interrupted work as completed or invent a running stage", async () => {
  await i18n.changeLanguage("zh-HK");
  render(<ActivityStrip items={[item("read", "read", "running", "HEIST")]} />);
  const toggle = screen.getByRole("button", { name: "處理過程" });
  expect(toggle).toHaveTextContent("已中斷");
  fireEvent.click(toggle);
  expect(screen.getByText("未能完成《HEIST》的閱讀")).toBeInTheDocument();
  expect(screen.queryByText("已完成")).not.toBeInTheDocument();
  expect(screen.queryByText("進行中")).not.toBeInTheDocument();
});

it("bounds projection before grouping and never renders unknown tool data", async () => {
  const items = Array.from({ length: 1000 }, (_, index) => item(String(index), "search", "completed", `topic ${index}`));
  expect(summarizeChatActivity(items, false).steps).toHaveLength(12);
  const repeat = Array.from({ length: 12 }, (_, index) => item(String(index), "read", "completed", "HEIST"));
  expect(summarizeChatActivity(repeat, false).steps).toHaveLength(1);
  await i18n.changeLanguage("en-US");
  const view = render(<ActivityStrip items={[{ ...item("private", "tool", "completed", "INTERNAL_SUBJECT"), operation: "INTERNAL_TOOL" as ChatActivity["operation"], ...internal }]} />);
  fireEvent.click(screen.getByRole("button"));
  expect(within(screen.getByRole("list")).getByText("Request reviewed")).toBeInTheDocument();
  expect(view.container.innerHTML).not.toMatch(/INTERNAL_TOOL|INTERNAL_SUBJECT|INTERNAL_SENTINEL/);
});
