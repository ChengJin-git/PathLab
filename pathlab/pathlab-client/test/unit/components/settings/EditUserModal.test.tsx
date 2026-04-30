import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { EditUserModal } from "@renderer/components/settings/EditUserModal";
import type { UserListItem } from "@renderer/api/users";
import enUS from "@renderer/locales/en-US.json";

function getTranslation(obj: Record<string, unknown>, key: string): string | undefined {
  const parts = key.split(".");
  let current: unknown = obj;
  for (const part of parts) {
    if (current && typeof current === "object" && part in current) {
      current = (current as Record<string, unknown>)[part];
    } else {
      return undefined;
    }
  }
  return typeof current === "string" ? current : undefined;
}

vi.mock("react-i18next", () => ({
  initReactI18next: { type: "3rdParty", init: () => {} },
  useTranslation: () => ({
    t: (key: string) => getTranslation(enUS, key) ?? key,
  }),
}));

describe("EditUserModal", () => {
  it("renders the clarified English label Registration / Notification Email", () => {
    const mockUser: UserListItem = {
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
      email: "path1@hospital.com",
    };

    render(
      <EditUserModal
        user={mockUser}
        editForm={{ nickname: "Path One", role: "pathologist", password: "", registration_email: "path1@hospital.com" }}
        onEditFormChange={vi.fn()}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("Registration / Notification Email")).toBeInTheDocument();
  });
});
