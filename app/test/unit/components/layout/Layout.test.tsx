import React from "react";
import { MemoryRouter, Link } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import Layout from "@renderer/components/Layout";
vi.mock("@renderer/components/chat/WorkbenchSidebar", () => ({
  default: () => <aside aria-label="Chats" />,
}));
vi.mock("@renderer/pages/AIChatPage", () => ({
  default: () => {
    const [value, setValue] = React.useState("");
    return (
      <input
        aria-label="Chat draft"
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
    );
  },
}));
afterEach(cleanup);

vi.mock("@renderer/contexts/AuthContext", () => ({
  useAuth: () => ({
    user: {
      nickname: "Pathologist",
      email: "path@example.com",
      role: "pathologist",
      avatar_url: null,
    },
    logout: vi.fn(),
    needsAgreement: false,
    acceptAgreement: vi.fn(),
    isLoading: false,
    isAdmin: false,
    refreshUser: vi.fn(),
  }),
}));

vi.mock("@renderer/contexts/ToastContext", () => ({
  useToast: () => ({ error: vi.fn(), success: vi.fn() }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    i18n: { language: "en-US" },
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

vi.mock("@renderer/components/BackgroundTaskPanel", () => ({
  BackgroundTaskPanel: () => <div data-testid="background-task-panel" />,
}));

vi.mock("@renderer/components/InstallPWA", () => ({
  InstallPWA: () => null,
}));

vi.mock("@renderer/components/DisclaimerModal", () => ({
  DisclaimerModal: () => null,
}));

vi.mock("@renderer/components/PrivacyPolicyModal", () => ({
  PrivacyPolicyModal: () => null,
}));


vi.mock("@renderer/components/ChangePasswordModal", () => ({
  ChangePasswordModal: () => null,
}));


vi.mock("@renderer/components/common/LanguageSwitcher", () => ({
  LanguageSwitcher: () => <button type="button">Lang</button>,
}));

vi.mock("@renderer/components/ui/tooltip", () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@renderer/api", () => ({
  uploadAvatar: vi.fn(),
  deleteAvatar: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

describe("Layout", () => {
  it('keeps language switching in the header and logout unboxed inside the account menu',()=>{
    render(<MemoryRouter initialEntries={['/results']}><Layout><div>Results</div></Layout></MemoryRouter>);
    expect(screen.getByRole('button',{name:'Lang'})).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'layout.profileMenu'}));
    expect(screen.getByRole('button',{name:'auth.logout'}).className).not.toMatch(/border/);
    expect(screen.queryByRole('button',{name:'common.settings'})).not.toBeInTheDocument();
  });
  it("keeps the same chat draft mounted across tools navigation and return", async () => {
    render(
      <MemoryRouter initialEntries={["/dashboard/chat-1"]}>
        <Link to="/tools">Open tools</Link>
        <Link to="/dashboard/chat-1">Return chat</Link>
        <Layout>
          <div>Tools body</div>
        </Layout>
      </MemoryRouter>,
    );
    const draft = await screen.findByRole("textbox", { name: "Chat draft" });
    fireEvent.change(draft, { target: { value: "unsent work" } });
    fireEvent.click(screen.getByText("Open tools"));
    expect(draft.closest("[aria-hidden]")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(screen.getByText("Tools body")).toBeVisible();
    fireEvent.click(screen.getByText("Return chat"));
    expect(screen.getByRole("textbox", { name: "Chat draft" })).toBe(draft);
    expect(draft).toHaveValue("unsent work");
  });
  it("renders premium shell hooks around application chrome", () => {
    render(
      <MemoryRouter initialEntries={["/results"]}>
        <Layout>
          <div>Results body</div>
        </Layout>
      </MemoryRouter>,
    );

    expect(screen.getByRole("banner")).toHaveAttribute(
      "data-shell-header",
      "true",
    );
    expect(screen.getByRole("main")).toHaveAttribute("data-shell-main", "true");
  });
});
