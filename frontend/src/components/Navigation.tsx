"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "../lib/AuthContext";
import { useEffect } from "react";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/analytics", label: "Analytics" },
  { href: "/settings", label: "Settings" },
];

export default function Navigation() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, loading, logout } = useAuth();

  // Redirect to login if not authenticated (except on login page)
  useEffect(() => {
    if (!loading && !user && pathname !== "/login") {
      router.push("/login");
    }
  }, [user, loading, pathname, router]);

  // Don't show nav on login page
  if (pathname === "/login") return null;

  // Don't show nav while loading auth
  if (loading) return null;

  return (
    <nav className="bg-gray-900 border-b border-gray-800 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-6 flex items-center h-14 gap-8">
        {/* Brand */}
        <Link
          href="/"
          className="text-lg font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 to-cyan-400 whitespace-nowrap hidden sm:block"
        >
          Portfolio Tracker
        </Link>
        <Link
          href="/"
          className="text-lg font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 to-cyan-400 sm:hidden"
        >
          PT
        </Link>

        {/* Links */}
        <div className="flex items-center gap-0.5 flex-1 overflow-x-auto">
          {NAV_ITEMS.map(({ href, label }) => {
            const isActive =
              href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={`relative px-3 py-1.5 text-sm font-medium transition-colors whitespace-nowrap ${
                  isActive
                    ? "text-white"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                {label}
                {isActive && (
                  <span className="absolute bottom-0 left-1 right-1 h-0.5 bg-indigo-500 rounded-full" />
                )}
              </Link>
            );
          })}
        </div>

        {/* User */}
        {user && (
          <div className="flex items-center gap-3 ml-auto shrink-0">
            <span className="text-xs text-gray-400 hidden sm:block">
              {user.email || user.displayName || "User"}
            </span>
            <button
              onClick={async () => { await logout(); router.push("/login"); }}
              className="px-3 py-1 text-xs text-gray-400 hover:text-white border border-gray-700 hover:border-gray-600 rounded transition-colors"
            >
              Logout
            </button>
          </div>
        )}
      </div>
    </nav>
  );
}
