"use client";
import { createContext, useContext, useState, useCallback, useEffect } from "react";

type ToastType = "success" | "error" | "info";

interface Toast {
  id: number;
  message: string;
  type: ToastType;
}

interface ToastContextValue {
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

let nextId = 0;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((message: string, type: ToastType) => {
    const id = nextId++;
    setToasts((prev) => [...prev, { id, message, type }]);
  }, []);

  const removeToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const value: ToastContextValue = {
    success: useCallback((msg: string) => addToast(msg, "success"), [addToast]),
    error: useCallback((msg: string) => addToast(msg, "error"), [addToast]),
    info: useCallback((msg: string) => addToast(msg, "info"), [addToast]),
  };

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* Toast container — fixed bottom-right */}
      <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 max-w-sm">
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onDismiss={removeToast} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  const [exiting, setExiting] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setExiting(true), 3500);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (exiting) {
      const timer = setTimeout(() => onDismiss(toast.id), 300);
      return () => clearTimeout(timer);
    }
  }, [exiting, onDismiss, toast.id]);

  const styles: Record<ToastType, string> = {
    success: "bg-green-900/90 border-green-700 text-green-200",
    error: "bg-red-900/90 border-red-700 text-red-200",
    info: "bg-gray-800/95 border-gray-600 text-gray-200",
  };

  const icons: Record<ToastType, string> = {
    success: "\u2713",
    error: "\u2717",
    info: "\u2139",
  };

  return (
    <div
      className={`px-4 py-3 rounded-lg border shadow-xl backdrop-blur-sm text-sm flex items-start gap-3 transition-all duration-300 ${styles[toast.type]} ${
        exiting ? "opacity-0 translate-x-4" : "opacity-100 translate-x-0 animate-slide-in"
      }`}
    >
      <span className="text-base mt-0.5 shrink-0">{icons[toast.type]}</span>
      <p className="flex-1 leading-snug">{toast.message}</p>
      <button
        onClick={() => setExiting(true)}
        className="text-gray-400 hover:text-white text-xs shrink-0 mt-0.5"
      >
        &times;
      </button>
    </div>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}
