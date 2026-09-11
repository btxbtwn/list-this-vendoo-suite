import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./app/App";
import "./styles/app.css";

function markDesktopApp() {
  const root = document.documentElement;
  const apply = () => root.classList.add("desktop-app");
  const pywebview = (window as Window & { pywebview?: unknown }).pywebview;
  if (pywebview) apply();
  window.addEventListener("pywebviewready", apply);
}

markDesktopApp();

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
