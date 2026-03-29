"use client";
import { useEffect } from "react";

/**
 * Global keyboard shortcut hook.
 * - Escape: calls onEscape if provided
 * - Cmd/Ctrl+K: focuses the first visible input[type="text"] or input[placeholder*="Filter"]
 */
export function useEscape(onEscape: (() => void) | null) {
  useEffect(() => {
    if (!onEscape) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onEscape();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onEscape]);
}

export function useCmdK() {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        // Focus the first filter/search input on the page
        const input = document.querySelector<HTMLInputElement>(
          'input[placeholder*="Filter"], input[placeholder*="Search"], input[placeholder*="filter"], input[placeholder*="search"]'
        );
        if (input) {
          input.focus();
          input.select();
        }
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);
}
