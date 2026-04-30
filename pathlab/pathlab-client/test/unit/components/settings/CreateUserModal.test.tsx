import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { CreateUserModal } from "@renderer/components/settings/CreateUserModal";
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

describe("CreateUserModal", () => {
  it("renders the clarified English label Registration / Notification Email", () => {
    render(
      <CreateUserModal
        createForm={{ username: "", password: "", nickname: "", role: "pathologist", registration_email: "" }}
        onCreateFormChange={vi.fn()}
        onSubmit={vi.fn()}
        onClose={vi.fn()}
        isCreating={false}
      />,
    );

    expect(screen.getByText("Registration / Notification Email")).toBeInTheDocument();
  });
});
