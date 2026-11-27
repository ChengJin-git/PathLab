import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import FileDeliveryCard, {
  parseDeliveredFiles,
} from "@renderer/components/chat/FileDeliveryCard";
import i18n from "@renderer/i18n";
import { downloadWorkbenchFile } from "@renderer/api/workbench";

const viewer = vi.hoisted(() => ({ openFile: vi.fn(), changed: vi.fn() }));
vi.mock("@renderer/components/chat/ConversationFiles", () => ({
  useConversationFiles: () => viewer,
}));
vi.mock("@renderer/api/workbench", () => ({ downloadWorkbenchFile: vi.fn() }));
afterEach(cleanup);
it("opens only a server-receipted file and downloads its stored bytes", async () => {
  await i18n.changeLanguage("en-US");
  expect(
    parseDeliveredFiles(
      '[DELIVER_FILE]{"filename":"fake.md","content":"not saved"}[/DELIVER_FILE]',
    ),
  ).toEqual([]);
  const files = parseDeliveredFiles(
    '[FILE_DELIVERY]{"files":[{"kind":"file","id":"saved","name":"report.md"}]}[/FILE_DELIVERY]',
  );
  render(<FileDeliveryCard files={files} />);
  fireEvent.click(screen.getByRole("button", { name: /report\.md\s*Saved/ }));
  expect(viewer.openFile).toHaveBeenCalledWith(files[0]);
  fireEvent.click(screen.getByRole("button", { name: "Download report.md" }));
  await waitFor(() =>
    expect(downloadWorkbenchFile).toHaveBeenCalledWith(files[0], null),
  );
});
