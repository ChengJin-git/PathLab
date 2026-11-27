import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import FileLibraryPage from "@renderer/pages/FileLibraryPage";
import * as api from "@renderer/api/fileLibrary";
import { downloadWorkbenchFile } from "@renderer/api/workbench";
import i18n from "@renderer/i18n";
const auth = vi.hoisted(() => ({ user: { id: "a" }, isAdmin: false }));
vi.mock("@renderer/contexts/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("@renderer/components/chat/FilePreviewContent", () => ({
  default: () => <div>Preview body</div>,
}));
vi.mock("@renderer/api/fileLibrary", () => ({
  libraryFiles: vi.fn(),
  libraryGroups: vi.fn(),
  batchLibraryFiles: vi.fn(),
  readLibraryText: vi.fn(),
  saveLibraryText: vi.fn(),
  libraryFile: vi.fn(),
  libraryFolders: vi.fn(),
  libraryOwners: vi.fn(),
  uploadLibraryFile: vi.fn(),
  saveLibraryFolder: vi.fn(),
  deleteLibraryFolder: vi.fn(),
  editLibraryFile: vi.fn(),
  deleteLibraryFile: vi.fn(),
  indexLibraryFile: vi.fn(),
  searchLibrary: vi.fn(),
}));
vi.mock("@renderer/api/workbench", () => ({ downloadWorkbenchFile: vi.fn() }));
const file: api.LibraryFile = {
  kind: "file",
  id: "f",
  name: "protocol.md",
  revision: "r",
  size: 1024,
  folder_id: null,
  origin: "upload",
  owner_id: "a",
  conversation_id: null,
  source_title: null,
  updated_at: "2026-11-01",
  index_status: "ready",
  index_progress: 100,
  index_error: null,
};
beforeEach(async () => {
  await i18n.changeLanguage("en-US");
  auth.isAdmin = false;
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  vi.stubGlobal("innerWidth", 1440);
  vi.mocked(api.libraryFiles).mockResolvedValue({
    items: [file],
    next_cursor: null,
  });
  vi.mocked(api.libraryFile).mockResolvedValue(file);
  vi.mocked(api.libraryFolders).mockResolvedValue({
    items: [{ id: "folder", name: "Study", owner_id: "a" }],
  });
  vi.mocked(api.libraryOwners).mockResolvedValue({ items: [] });
  vi.mocked(api.libraryGroups).mockResolvedValue({
    items: [
      {
        id: "__unlinked__",
        title: null,
        file_count: 1,
        total_size: 1024,
        updated_at: "2026-11-01",
      },
    ],
    next_cursor: null,
  });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
function show() {
  render(
    <MemoryRouter initialEntries={["/files?file=f"]}>
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <FileLibraryPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}
it("keeps one file library with automatic search state and no knowledge-base step", async () => {
  show();
  await screen.findByText("Preview body");
  expect(
    screen.getByRole("heading", { name: "File library" }),
  ).toBeInTheDocument();
  expect(screen.queryByText("Knowledge bases")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "All users" }),
  ).not.toBeInTheDocument();
});
it("downloads while a folder move is still completing", async () => {
  let release!: () => void;
  vi.mocked(api.editLibraryFile).mockImplementation(
    () =>
      new Promise((resolve) => {
        release = () => resolve({ ...file, folder_id: "folder" });
      }),
  );
  show();
  await screen.findByText("Preview body");
  fireEvent.click(screen.getByRole("button", { name: "Folder" }));
  fireEvent.click(await screen.findByRole("option", { name: "Study" }));
  fireEvent.click(screen.getByRole("button", { name: "Download" }));
  await waitFor(() =>
    expect(downloadWorkbenchFile).toHaveBeenCalledWith(file, null),
  );
  release();
});
it("searches content in the current owner scope", async () => {
  vi.mocked(api.searchLibrary).mockResolvedValue({
    items: [
      {
        file_id: "f",
        revision: "r",
        name: "protocol.md",
        page: 2,
        section: "Methods",
        text: "Cold ischemia limit: 38 minutes.",
        score: 1,
        url: "/files?file=f&page=2",
      },
    ],
  });
  show();
  fireEvent.change(
    screen.getByRole("textbox", {
      name: "Search names or ask about your files",
    }),
    { target: { value: "cold ischemia" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Search contents" }));
  expect(
    await screen.findByText("Cold ischemia limit: 38 minutes."),
  ).toBeInTheDocument();
  expect(api.searchLibrary).toHaveBeenCalledWith(
    "cold ischemia",
    { folder: "", all_users: false, owner: "" },
    expect.any(AbortSignal),
  );
});

it("loads group files on demand and shows atomic batch mutation errors", async () => {
  show();
  await screen.findByText("Independent files");
  expect(api.libraryFiles).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /Independent files/ }));
  const selection = await screen.findByRole("checkbox", {
    name: "protocol.md",
  });
  expect(api.libraryFiles).toHaveBeenCalledWith(
    expect.objectContaining({ conversation: "__unlinked__", limit: "30" }),
    expect.any(AbortSignal),
  );
  fireEvent.click(selection);
  fireEvent.click(screen.getByRole("button", { name: "Edit selected" }));
  fireEvent.change(screen.getByRole("textbox", { name: "protocol.md" }), {
    target: { value: "updated.md" },
  });
  vi.mocked(api.batchLibraryFiles).mockRejectedValueOnce(
    new Error("File changed; reload before editing"),
  );
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(
      screen
        .getAllByRole("alert")
        .some((element) => element.textContent?.includes("File changed")),
    ).toBe(true),
  );
  expect(api.batchLibraryFiles).toHaveBeenCalledWith(
    [
      {
        id: "f",
        revision: "r",
        updated_at: file.updated_at,
        name: "updated.md",
      },
    ],
    "edit",
    undefined,
  );
  expect(screen.getByRole("textbox", { name: "protocol.md" })).toHaveValue(
    "updated.md",
  );
});
