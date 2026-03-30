import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import React from "react";

// Track apiCall invocations
const apiCallMock = vi.fn().mockResolvedValue(
  new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } })
);

// Mock apiCall
vi.mock("../lib/api", () => ({
  apiCall: (...args: any[]) => apiCallMock(...args),
}));

// Mock recharts to avoid rendering issues in test env
vi.mock("recharts", () => ({
  AreaChart: ({ children }: any) => <div>{children}</div>,
  Area: () => <div />,
  XAxis: () => <div />,
  YAxis: () => <div />,
  Tooltip: () => <div />,
  ResponsiveContainer: ({ children }: any) => <div>{children}</div>,
}));

// Mock useAuth - control the return value per test
let mockUser: any = null;
let mockLoading = true;

vi.mock("../lib/AuthContext", () => ({
  useAuth: () => ({ user: mockUser, loading: mockLoading, logout: vi.fn() }),
}));

// Mock firebase
vi.mock("../lib/firebase", () => ({
  auth: { currentUser: null },
}));

import PortfolioChart from "../components/PortfolioChart";

describe("Auth-gated data fetching", () => {
  beforeEach(() => {
    apiCallMock.mockClear();
    mockUser = null;
    mockLoading = true;
  });

  describe("PortfolioChart", () => {
    it("does NOT fetch when user is null (auth loading)", () => {
      mockUser = null;
      mockLoading = true;

      render(<PortfolioChart />);

      expect(apiCallMock).not.toHaveBeenCalled();
    });

    it("does NOT fetch when auth is done but no user (logged out)", () => {
      mockUser = null;
      mockLoading = false;

      render(<PortfolioChart />);

      expect(apiCallMock).not.toHaveBeenCalled();
    });

    it("fetches when user is authenticated", async () => {
      mockUser = { uid: "test-user", getIdToken: vi.fn() };
      mockLoading = false;

      render(<PortfolioChart />);

      await waitFor(() => {
        expect(apiCallMock).toHaveBeenCalledWith(
          expect.stringContaining("/api/portfolio/history")
        );
      });
    });
  });
});
