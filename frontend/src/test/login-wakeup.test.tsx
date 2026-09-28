/** Sign-in against a sleeping free-tier API: never a silent failure. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";

const login = vi.hoisted(() => vi.fn());

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ user: null, loading: false, login, logout: vi.fn() }),
}));

import { LoginPage } from "../pages/Login";

function fill(): void {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "admin@example.com" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "correct-horse" } });
  fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
}

function renderLogin(): void {
  render(
    <MemoryRouter initialEntries={["/login"]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/dashboard" element={<p>dashboard</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  login.mockReset();
});

describe("api() error messages", () => {
  it("gives a proxy 502 with no statusText a readable message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("<html>502</html>", { status: 502, statusText: "", headers: { "content-type": "text/html" } })),
    );
    const err = await api("/auth/login", { method: "POST" }).then(() => null, (e: unknown) => e as ApiError);
    expect(err).toBeInstanceOf(ApiError);
    if (!err) return;
    expect(err.status).toBe(502);
    expect(err.message).toMatch(/starting up/);
  });

  it("falls back to the status code for other non-JSON errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("x", { status: 418, statusText: "" })));
    const err = await api("/x").then(() => null, (e: unknown) => e as ApiError);
    expect(err?.message).toBe("Request failed (418)");
  });
});

describe("login page", () => {
  it("retries while the server wakes up, then signs in", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}")));
    vi.useFakeTimers({ shouldAdvanceTime: true });
    login.mockRejectedValueOnce(new ApiError(502, "server_unavailable", "starting")).mockResolvedValueOnce(undefined);
    renderLogin();
    fill();
    expect(await screen.findByText(/waking up the server/i)).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(3_000);
    expect(await screen.findByText("dashboard")).toBeInTheDocument();
    expect(login).toHaveBeenCalledTimes(2);
  });

  it("shows wrong-password errors immediately without retrying", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}")));
    login.mockRejectedValue(new ApiError(401, "invalid_credentials", "Invalid email or password"));
    renderLogin();
    fill();
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
    expect(login).toHaveBeenCalledTimes(1);
  });

  it("never fails silently on an empty error message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}")));
    login.mockRejectedValue(new ApiError(500, "error", ""));
    renderLogin();
    fill();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/sign in failed/i));
  });
});
