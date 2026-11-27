import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import SkillPackageEditor from "@renderer/components/chat/SkillPackageEditor";
import * as api from "@renderer/api/capabilities";
import i18n from "@renderer/i18n";

vi.mock("@renderer/contexts/AuthContext", () => ({
  useAuth: () => ({ user: { id: "a", role: "pathologist" } }),
}));
vi.mock("@renderer/api/capabilities", () => ({
  listSkillFiles: vi.fn(),
  readSkillFile: vi.fn(),
  saveSkillFile: vi.fn(),
  uploadSkillFile: vi.fn(),
  replaceSkillPackage: vi.fn(),
  deleteSkillFile: vi.fn(),
  downloadSkillFile: vi.fn(),
}));
const entry: api.CapabilityEntry = {
  id: "ugc-a",
  kind: "skill",
  name: "Scripted skill",
  description: "",
  owner_id: "a",
  builtin: false,
  visibility: "private",
  revision: 7,
  installed: true,
  enabled: true,
  editable: true,
  connected: false,
  has_credential: false,
  tool_count: 0,
};
beforeEach(async () => {
  await i18n.changeLanguage("en-US");
  vi.mocked(api.listSkillFiles).mockResolvedValue({
    revision: 7,
    entrypoint: "SKILL.md",
    items: [
      { path: "scripts/run.py", size: 10, executable: true },
      { path: "assets/image.png", size: 20, executable: false },
    ],
    next_cursor: null,
  });
  vi.mocked(api.readSkillFile).mockImplementation(async (_, path) => ({
    revision: 7,
    path,
    text: path.endsWith(".py") ? "print(1)\n" : null,
    size: 10,
    executable: path.endsWith(".py"),
  }));
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
function show(editable = true) {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <SkillPackageEditor
        entry={{ ...entry, editable }}
        onChanged={vi.fn().mockResolvedValue(undefined)}
        onEditing={vi.fn()}
      />
    </QueryClientProvider>,
  );
}
it("edits script bytes with executable flag and optimistic revision, retains draft on conflict", async () => {
  show();
  fireEvent.click(
    await screen.findByRole("button", { name: /scripts\/run.py/ }),
  );
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  fireEvent.change(screen.getByRole("textbox", { name: "File content" }), {
    target: { value: "print(2)\n\n" },
  });
  vi.mocked(api.saveSkillFile).mockRejectedValue(
    new Error("This skill changed; refresh before saving"),
  );
  fireEvent.click(screen.getByRole("button", { name: "Save file" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "refresh before saving",
  );
  expect(api.saveSkillFile).toHaveBeenCalledWith("ugc-a", {
    revision: 7,
    path: "scripts/run.py",
    content: "print(2)\n\n",
    executable: true,
    overwrite: true,
  });
  expect(screen.getByRole("textbox", { name: "File content" })).toHaveValue(
    "print(2)\n\n",
  );
});
it("uploads a binary replacement without coercing its content to Markdown", async () => {
  show();
  fireEvent.click(
    await screen.findByRole("button", { name: /assets\/image.png/ }),
  );
  fireEvent.click(await screen.findByRole("button", { name: "Replace file" }));
  const file = new File([new Uint8Array([0, 255, 128])], "image.png", {
    type: "image/png",
  });
  fireEvent.change(screen.getByLabelText("Upload file"), {
    target: { files: [file] },
  });
  vi.mocked(api.uploadSkillFile).mockResolvedValue({ revision: 8 });
  fireEvent.submit(
    screen.getByRole("button", { name: "Save file" }).closest("form")!,
  );
  await waitFor(() =>
    expect(api.uploadSkillFile).toHaveBeenCalledWith(
      "ugc-a",
      file,
      "assets/image.png",
      7,
      true,
      false,
    ),
  );
});
it("shows public package files read-only for someone other than the owner", async () => {
  show(false);
  expect(
    screen.queryByRole("button", { name: "New text file" }),
  ).not.toBeInTheDocument();
  fireEvent.click(
    await screen.findByRole("button", { name: /scripts\/run.py/ }),
  );
  await screen.findByText("print(1)");
  expect(
    screen.queryByRole("button", { name: "Edit" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Delete file" }),
  ).not.toBeInTheDocument();
});
