import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PermissionCenterModal } from "@renderer/components/settings/PermissionCenterModal";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => {
    if (options?.count !== undefined) return `${key}:${String(options.count)}`;
    if (options?.name !== undefined) return `${key}:${String(options.name)}`;
    return key;
  } }),
}));

const fetchDatasetsMock = vi.fn();
const listUsersPagedMock = vi.fn();
const getUserDatasetGrantsMock = vi.fn();
const grantDatasetGrantMock = vi.fn();
const listDatasetGrantsMock = vi.fn();
const batchGrantDatasetGrantsMock = vi.fn();
const batchRevokeDatasetGrantsMock = vi.fn();
const revokeDatasetGrantMock = vi.fn();
const updateDatasetVisibilityMock = vi.fn();

vi.mock("@renderer/api", () => ({
  fetchDatasets: (...args: unknown[]) => fetchDatasetsMock(...args),
  listUsersPaged: (...args: unknown[]) => listUsersPagedMock(...args),
  getUserDatasetGrants: (...args: unknown[]) => getUserDatasetGrantsMock(...args),
  grantDatasetGrant: (...args: unknown[]) => grantDatasetGrantMock(...args),
  listDatasetGrants: (...args: unknown[]) => listDatasetGrantsMock(...args),
  batchGrantDatasetGrants: (...args: unknown[]) => batchGrantDatasetGrantsMock(...args),
  batchRevokeDatasetGrants: (...args: unknown[]) => batchRevokeDatasetGrantsMock(...args),
  revokeDatasetGrant: (...args: unknown[]) => revokeDatasetGrantMock(...args),
  updateDatasetVisibility: (...args: unknown[]) => updateDatasetVisibilityMock(...args),
}));

function renderModal() {
  return render(
    <PermissionCenterModal
      showConfirmDialog={vi.fn()}
      closeConfirmDialog={vi.fn()}
      onClose={vi.fn()}
      initialMode="user"
    />,
  );
}

function getGrantDatasetsButton(): HTMLButtonElement {
  const button = screen
    .getAllByRole("button")
    .find((item) => item.textContent?.includes("settings.permissionCenterModal.grantSelectedDatasets"));
  if (!button) throw new Error("Grant datasets button not found");
  return button;
}

function getSelectVisibleDatasetsLabel(): HTMLElement {
  const node = screen
    .getAllByText((content) => content.includes("settings.permissionCenterModal.selectVisibleDatasets"))
    .at(0);
  if (!node) throw new Error("Select visible datasets label not found");
  return node;
}

beforeEach(() => {
  vi.clearAllMocks();

  fetchDatasetsMock.mockResolvedValue({
    items: [
      {
        dataset_id: "private-1",
        dataset_name: "Private Dataset",
        user_id: "owner-1",
        file_count: 12,
        total_size: 1,
        data_type: "wsi",
        task_type: "classification",
        aggregation_level: "file",
        is_public: false,
      },
      {
        dataset_id: "public-1",
        dataset_name: "Public Dataset",
        user_id: "owner-2",
        file_count: 8,
        total_size: 1,
        data_type: "wsi",
        task_type: "classification",
        aggregation_level: "file",
        is_public: true,
      },
    ],
    total: 2,
  });

  listUsersPagedMock.mockResolvedValue({
    items: [
      {
        id: "user-1",
        email: "user@example.com",
        nickname: "User One",
        role: "pathologist",
        is_active: true,
      },
    ],
    total: 1,
    page: 1,
    page_size: 9,
  });

  getUserDatasetGrantsMock.mockResolvedValue({ user_id: "user-1", grants: [], valid_grants: [] });
  listDatasetGrantsMock.mockResolvedValue({ dataset_id: "private-1", grants: [] });
  grantDatasetGrantMock.mockResolvedValue({ message: "ok", permission: {} });
  batchGrantDatasetGrantsMock.mockResolvedValue({ failed: 0, results: [] });
  batchRevokeDatasetGrantsMock.mockResolvedValue({ failed: 0, results: [] });
  revokeDatasetGrantMock.mockResolvedValue({ message: "ok" });
  updateDatasetVisibilityMock.mockResolvedValue({ dataset_id: "private-1", is_public: false });
});

describe("PermissionCenterModal", () => {
  it("shows selectable dataset count excluding public datasets", async () => {
    renderModal();

    await screen.findByText("Private Dataset");
    await screen.findByText("Public Dataset");

    expect(getSelectVisibleDatasetsLabel().textContent).toContain(":1");
  });

  it("counts only private datasets when selecting all visible", async () => {
    const user = userEvent.setup();
    renderModal();

    await screen.findByText("Private Dataset");
    await screen.findByText("Public Dataset");

    const selectVisibleText = getSelectVisibleDatasetsLabel();
    const selectionContainer = selectVisibleText.closest("div");
    const selectVisibleCheckbox = selectionContainer?.querySelector(
      'input[type="checkbox"]',
    ) as HTMLInputElement;

    await user.click(selectVisibleCheckbox);

    await waitFor(() => {
      expect(getGrantDatasetsButton().textContent).toContain(":1");
    });
  });

  it("shows private temporary permissions wording in current permissions panel", async () => {
    renderModal();
    await screen.findByText("settings.permissionCenterModal.currentPermissions");

    expect(screen.getByText("settings.permissionCenterModal.currentPermissionsCount:0")).toBeInTheDocument();
    expect(screen.getByText("settings.permissionCenterModal.noCurrentPermissions")).toBeInTheDocument();
  });
});
