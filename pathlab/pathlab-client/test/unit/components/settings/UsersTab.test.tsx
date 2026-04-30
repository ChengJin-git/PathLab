import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { UsersTab } from "@renderer/components/settings/UsersTab";
import { TooltipProvider } from "@renderer/components/ui/tooltip";

vi.mock("react-i18next", () => ({
  initReactI18next: { type: "3rdParty", init: () => {} },
  useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => {
    if (options?.count !== undefined) return `${key}:${String(options.count)}`;
    if (options?.name !== undefined) return `${key}:${String(options.name)}`;
    return key;
  } }),
}));

vi.mock("@renderer/contexts/AuthContext", () => ({
  useAuth: () => ({ isAdmin: true }),
}));

const listUsersPagedMock = vi.fn();
const createUserMock = vi.fn();
const updateUserMock = vi.fn();
const deleteUserMock = vi.fn();
const revokeUserAgreementMock = vi.fn();
const batchActivateUsersMock = vi.fn();
const batchDeactivateUsersMock = vi.fn();
const batchDeleteUsersMock = vi.fn();
const getMaintenanceModeMock = vi.fn();
const setMaintenanceModeMock = vi.fn();
const getMaintenanceNoticeMock = vi.fn();
const setMaintenanceNoticeMock = vi.fn();
const getGlobalSettingsMock = vi.fn();
const updateGlobalSettingsMock = vi.fn();

vi.mock("@renderer/api/users", () => ({
  listUsersPaged: (...args: unknown[]) => listUsersPagedMock(...args),
  createUser: (...args: unknown[]) => createUserMock(...args),
  updateUser: (...args: unknown[]) => updateUserMock(...args),
  deleteUser: (...args: unknown[]) => deleteUserMock(...args),
  revokeUserAgreement: (...args: unknown[]) => revokeUserAgreementMock(...args),
  batchActivateUsers: (...args: unknown[]) => batchActivateUsersMock(...args),
  batchDeactivateUsers: (...args: unknown[]) => batchDeactivateUsersMock(...args),
  batchDeleteUsers: (...args: unknown[]) => batchDeleteUsersMock(...args),
  getMaintenanceMode: (...args: unknown[]) => getMaintenanceModeMock(...args),
  setMaintenanceMode: (...args: unknown[]) => setMaintenanceModeMock(...args),
  getMaintenanceNotice: (...args: unknown[]) => getMaintenanceNoticeMock(...args),
  setMaintenanceNotice: (...args: unknown[]) => setMaintenanceNoticeMock(...args),
}));

vi.mock("@renderer/api/settings", () => ({
  getGlobalSettings: (...args: unknown[]) => getGlobalSettingsMock(...args),
  updateGlobalSettings: (...args: unknown[]) => updateGlobalSettingsMock(...args),
}));

function renderUsersTab() {
  return render(
    <TooltipProvider>
      <UsersTab
        showConfirmDialog={vi.fn()}
        closeConfirmDialog={vi.fn()}
        currentUserId="admin-1"
      />
    </TooltipProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();

  listUsersPagedMock.mockResolvedValue({
    items: [
      {
        id: "user-1",
        username: "pathologist1",
        nickname: "Path One",
        role: "pathologist",
        is_active: true,
        is_superuser: false,
        is_verified: true,
        agreement_accepted_at: null,
        agreement_ip: null,
        notice_acknowledged_at: null,
        registration_email: "path1@hospital.com",
        created_at: "2024-01-01T00:00:00Z",
      },
    ],
    total: 1,
    page: 1,
    page_size: 10,
  });

  getMaintenanceModeMock.mockResolvedValue({ enabled: false });
  getMaintenanceNoticeMock.mockResolvedValue({ active: false, message: null, needs_acknowledgment: false });
  getGlobalSettingsMock.mockResolvedValue({});

  createUserMock.mockResolvedValue({
    id: "new-user-1",
    username: "newpath",
    nickname: "New Pathologist",
    role: "pathologist",
    is_active: true,
  });

  updateUserMock.mockResolvedValue({ id: "legacy-user-1", role: "pathologist" });
});

describe("UsersTab", () => {
  it("opens create-user modal and submits a pathologist user via createUser()", async () => {
    const user = userEvent.setup();
    renderUsersTab();

    await screen.findByText("pathologist1");

    const createButton = screen.getByRole("button", { name: /settings.usersTab.createUser/i });
    await user.click(createButton);

    await screen.findByText("settings.createUserModal.title");

    const usernameInput = screen.getByPlaceholderText("settings.createUserModal.enterUsername");
    const passwordInput = screen.getByPlaceholderText("settings.createUserModal.minSixChars");
    const nicknameInput = screen.getByPlaceholderText("settings.createUserModal.displayNameOptional");
    const emailInput = screen.getByPlaceholderText("settings.createUserModal.emailPlaceholder");

    await user.type(usernameInput, "newpath");
    await user.type(passwordInput, "secure123");
    await user.type(nicknameInput, "New Pathologist");
    await user.type(emailInput, "newpath@hospital.com");

    const submitButton = screen.getByRole("button", { name: /settings.createUserModal.createUser/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(createUserMock).toHaveBeenCalledTimes(1);
    });

    expect(createUserMock).toHaveBeenCalledWith({
      username: "newpath",
      password: "secure123",
      nickname: "New Pathologist",
      role: "pathologist",
      registration_email: "newpath@hospital.com",
    });

    expect(updateUserMock).not.toHaveBeenCalled();
  });
});
