import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import CapabilityLibrary from "@renderer/components/chat/CapabilityLibrary";
import * as api from "@renderer/api/capabilities";
import i18n from "@renderer/i18n";

vi.mock("@renderer/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "a", role: "pathologist" }, isAdmin: false }),
}));
vi.mock("@renderer/api/capabilities", () => ({
  listCapabilities: vi.fn(),
  readCapability: vi.fn(),
  saveCapability: vi.fn(),
  installCapability: vi.fn(),
  removeCapability: vi.fn(),
  connectCapability: vi.fn(),
  importCapability: vi.fn(),
  syncCapability: vi.fn(),
  listSkillFiles: vi
    .fn()
    .mockResolvedValue({
      items: [{ path: "SKILL.md", size: 34, executable: false }],
      revision: 1,
      entrypoint: "SKILL.md",
      next_cursor: null,
    }),
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
const entry: api.CapabilityEntry = {
  id: "ugc-example",
  kind: "skill",
  name: "Handoff",
  description: "Clinical handoff rules",
  owner_id: "a",
  builtin: false,
  visibility: "private",
  revision: 1,
  installed: true,
  enabled: true,
  editable: true,
  connected: false,
  has_credential: false,
  tool_count: 0,
  content: "# Rules\nUse three headings.",
};
function show(onUse = vi.fn()) {
  vi.mocked(api.listCapabilities).mockResolvedValue({
    items: [entry],
    next_cursor: null,
  });
  vi.mocked(api.readCapability).mockResolvedValue(entry);
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <CapabilityLibrary kind="skill" onClose={vi.fn()} onUse={onUse} />
    </QueryClientProvider>,
  );
}
it('synchronizes a linked GitHub skill from its detail page', async () => {
  await i18n.changeLanguage('en-US');
  show();
  const linked = { ...entry, can_sync: true, github_source: { url: 'https://github.com/example/skill', commit: 'a'.repeat(40) } };
  vi.mocked(api.readCapability).mockResolvedValue(linked);
  vi.mocked(api.syncCapability).mockResolvedValue({ ...linked, revision: 2 });
  fireEvent.click(await screen.findByRole('heading', { name: 'Handoff' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Sync from GitHub' }));
  await waitFor(() => expect(api.syncCapability).toHaveBeenCalledWith(entry.id, 1, undefined));
  expect(screen.getByText('Artwork source and license:', { exact: false })).toBeVisible();
});
it("enters edit mode without submitting the replaced button, then saves revised instructions", async () => {
  await i18n.changeLanguage("en-US");
  show();
  fireEvent.click(await screen.findByRole("heading", { name: "Handoff" }));
  const edit = await screen.findByRole("button", { name: "Edit" });
  expect(
    screen.getByRole("textbox", { name: "Instructions" }),
  ).toBeDisabled();
  fireEvent.click(edit);
  await waitFor(() =>
    expect(
      screen.getByRole("textbox", { name: "Instructions" }),
    ).toBeEnabled(),
  );
  expect(api.saveCapability).not.toHaveBeenCalled();
  fireEvent.change(
    screen.getByRole("textbox", { name: "Instructions" }),
    { target: { value: "Use exactly two headings." } },
  );
  vi.mocked(api.saveCapability).mockResolvedValue({
    ...entry,
    revision: 2,
    content: "Use exactly two headings.",
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(api.saveCapability).toHaveBeenCalledWith(
      expect.objectContaining({
        revision: 1,
        content: "Use exactly two headings.",
      }),
      "ugc-example",
    ),
  );
});
it("selects a saved skill for actual Chat loading", async () => {
  await i18n.changeLanguage("en-US");
  const use = vi.fn();
  show(use);
  fireEvent.click(await screen.findByRole("heading", { name: "Handoff" }));
  fireEvent.click(await screen.findByRole("button", { name: "Use in Chat" }));
  expect(use).toHaveBeenCalledWith(
    expect.objectContaining({
      library_skill_id: "ugc-example",
      mode: "skill",
      name: "Handoff",
    }),
  );
  expect(
    screen.queryByRole("tab", { name: "All users" }),
  ).not.toBeInTheDocument();
});
