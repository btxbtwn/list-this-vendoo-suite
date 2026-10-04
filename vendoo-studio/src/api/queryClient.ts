import { QueryClient } from "@tanstack/react-query";

export function createStudioQueryClient() {
  return new QueryClient({
    defaultOptions: {
      // Studio talks to its local server. The webview's Internet connection
      // status must not pause local reads or a confirmed listing action.
      queries: {
        networkMode: "always",
        staleTime: 5000,
        retry: 1,
      },
      mutations: {
        networkMode: "always",
      },
    },
  });
}
