import React from "react";
import ReactDOM from "react-dom/client";
import { focusManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./app/App";
import { applyTheme } from "./theme";
import "./styles/app.css";

applyTheme();

function markDesktopApp() {
  const root = document.documentElement;
  const apply = () => root.classList.add("desktop-app");
  const pywebview = (window as Window & { pywebview?: unknown }).pywebview;
  if (pywebview) apply();
  window.addEventListener("pywebviewready", apply);
}

markDesktopApp();

// Polls slow down while Studio sits behind another window (see pollMs), and the
// desktop webview never reports itself hidden, so also refetch on window focus.
focusManager.setEventListener((onFocus) => {
  const listener = () => onFocus();
  window.addEventListener("visibilitychange", listener, false);
  window.addEventListener("focus", listener, false);
  return () => {
    window.removeEventListener("visibilitychange", listener);
    window.removeEventListener("focus", listener);
  };
});

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      retry: 1,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>
);
