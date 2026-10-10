import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { AssistantMessage } from "../api/assistant";
import { ASSISTANT_STARTERS, AssistantPage, linkedListingId, liveParts } from "./AssistantPage";

const { useQuery } = vi.hoisted(() => ({ useQuery: vi.fn() }));
vi.mock("@tanstack/react-query", () => ({
  useQuery,
  useMutation: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useQueryClient: () => ({ invalidateQueries: vi.fn(), getQueryData: vi.fn(), setQueryData: vi.fn() }),
}));
// The markdown bundle is lazy; render the text itself so the page can be read synchronously.
vi.mock("./ChatMarkdown", () => ({ ChatMarkdown: ({ text }: { text: string }) => <p>{text}</p> }));

function render(turns: AssistantMessage[] | undefined, state: { isLoading?: boolean; error?: Error } = {}) {
  useQuery.mockReturnValue({
    data: turns, isLoading: Boolean(state.isLoading), isError: Boolean(state.error), error: state.error ?? null,
  });
  return renderToStaticMarkup(<AssistantPage onOpenProviders={vi.fn()} onOpenListing={vi.fn()} />);
}

describe("AssistantPage", () => {
  it("opens with what it reads and questions to start from", () => {
    const html = render([]);
    expect(html).toContain("<h1>Ask about your business</h1>");
    expect(html).toContain("it never changes a listing or sends anything");
    for (const starter of ASSISTANT_STARTERS) expect(html).toContain(starter);
    expect(html).toContain("About your business");
    expect(html).not.toContain("Clear conversation");
  });

  it("shows the saved conversation and offers to clear it", () => {
    const html = render([
      { id: "q", role: "user", text: "What sold last week?", created_at: null },
      { id: "a", role: "assistant", text: "Three items for $96.", created_at: null },
    ]);
    expect(html).toContain('<div class="msg msg-user"><p>What sold last week?</p></div>');
    expect(html).toContain('<div class="msg msg-assistant"><p>Three items for $96.</p></div>');
    expect(html).toContain("Clear conversation");
    expect(html).not.toContain("Ask about your business");
  });

  it("holds the welcome back while the conversation loads, and reports a failed load", () => {
    expect(render(undefined, { isLoading: true })).not.toContain("Ask about your business");
    expect(render(undefined, { error: new Error("Studio is not running") })).toContain("Studio is not running");
  });

  it("reads the listing an answer links to, and leaves other links alone", () => {
    expect(linkedListingId("#listing-674fb62ea1fb")).toBe("674fb62ea1fb");
    expect(linkedListingId("https://example.com/#listing-abc")).toBeNull();
    expect(linkedListingId("#listing-")).toBeNull();
    expect(linkedListingId(undefined)).toBeNull();
  });

  it("draws a question or an answer once when the saved conversation catches up mid-answer", () => {
    const turn = (role: "user" | "assistant", text: string): AssistantMessage => ({ id: text, role, text, created_at: null });
    const earlier = [turn("user", "Same question"), turn("assistant", "First answer")];
    const live = { question: "Same question", asked: 2, answer: "Second", status: "" };
    // Nothing saved yet: the page draws both itself.
    expect(liveParts(live, earlier)).toEqual({ question: true, answer: true });
    // The question arrived with a refresh, even though it reads the same as an earlier one.
    expect(liveParts(live, [...earlier, turn("user", "Same question")])).toEqual({ question: false, answer: true });
    // So did the finished answer.
    expect(liveParts(live, [...earlier, turn("user", "Same question"), turn("assistant", "Second answer")]))
      .toEqual({ question: false, answer: false });
    // An answer picked back up never draws its question, which is already saved.
    const resumed = { ...live, question: null };
    expect(liveParts(resumed, [...earlier, turn("user", "Same question")])).toEqual({ question: false, answer: true });
    expect(liveParts(resumed, earlier)).toEqual({ question: false, answer: false });
  });
});
