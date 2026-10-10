import { useEffect, useRef, useState, type MouseEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { AssistantRefused, type AssistantMessage } from "../api/assistant";
import { confirmDialog } from "../ui/confirmDialog";
import { addToast } from "../ui/toast";
import { ChatMarkdown } from "./ChatMarkdown";
import { stableStreamingText } from "./streamingText";

/** Questions that show what the assistant can see, offered before the first one is asked. */
export const ASSISTANT_STARTERS = [
  "How did last month compare with the month before?",
  "Which brands and categories make me the most profit?",
  "What has been listed longest, and what should I do with it?",
  "Which wholesale boxes paid off, and which did not?",
];

/** Streamed text reaches the page at most this often, so a long answer does not re-render per token. */
const PAINT_MS = 50;
const MESSAGES_KEY = ["assistant", "messages"];
const NOTE_KEY = ["assistant", "note"];
const NOTE_MAX = 4000;
/** How often, and how many times, a dropped connection is retried before saying so. */
const RECONNECT_MS = 1500;
const RECONNECT_TRIES = 8;
const LOST_CONNECTION =
  "Lost the connection to Studio. If it was still answering, the answer appears here when you come back.";
/** How an answer points at a listing: `[title](#listing-<id>)`. */
const LISTING_LINK = /^#listing-([\w-]+)$/;

/** The listing an answer's link opens, or null for any other link. */
export function linkedListingId(href: string | null | undefined): string | null {
  return LISTING_LINK.exec(href ?? "")?.[1] ?? null;
}

/**
 * What of the turn being written still has to be drawn. The saved conversation
 * can refresh mid-answer and bring the question, or the finished answer, with
 * it; drawing the live copy as well would show it twice.
 */
export function liveParts(live: LiveTurn, turns: AssistantMessage[]): { question: boolean; answer: boolean } {
  if (live.question === null) return { question: false, answer: turns[turns.length - 1]?.role !== "assistant" };
  return { question: turns.length <= live.asked, answer: turns.length < live.asked + 2 };
}

interface Props {
  onOpenProviders: () => void;
  onOpenListing: (id: string) => void;
}

export interface LiveTurn {
  /** Null when an answer already under way was picked back up; its question is among the saved turns. */
  question: string | null;
  /** How many turns were saved when the question was asked. */
  asked: number;
  answer: string;
  status: string;
}

/**
 * A chat about the business as a whole, apart from any listing's chat. Every
 * question is answered from all of Studio's data, and it changes none of it.
 */
export function AssistantPage({ onOpenProviders, onOpenListing }: Props) {
  const queryClient = useQueryClient();
  const messages = useQuery({ queryKey: MESSAGES_KEY, queryFn: api.assistant.messages });
  const [input, setInput] = useState("");
  const [live, setLive] = useState<LiveTurn | null>(null);
  const [error, setError] = useState("");
  const [noteOpen, setNoteOpen] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement | null>(null);
  const pinned = useRef(true);

  const turns = messages.data ?? [];
  useEffect(() => {
    const el = scroller.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [turns.length, live?.answer, live?.status, error]);

  /**
   * Follow an answer to its end: a new one when there is a question, otherwise
   * whichever is already being written. Studio keeps writing when this
   * connection drops, so a drop is retried, not reported.
   */
  const follow = async (question: string | null) => {
    if (controller.current) return;
    const abort = new AbortController();
    controller.current = abort;
    let asking = question !== null;
    const asked = turns.length;
    let dropped = false;
    let answer = "";
    let timer: ReturnType<typeof setTimeout> | null = null;
    const show = (change: Partial<LiveTurn>) =>
      setLive((turn) => ({ question, asked, answer, status: "", ...turn, ...change }));
    const handlers = {
      onText: (piece: string) => {
        answer += piece;
        if (timer === null) {
          timer = setTimeout(() => {
            timer = null;
            show({ answer });
          }, PAINT_MS);
        }
      },
      onStatus: (status: string) => show({ status }),
    };
    if (question !== null) {
      pinned.current = true;
      setError("");
      setInput("");
      show({ status: "Reading your shop…" });
    }
    try {
      for (let tries = 0; ; tries += 1) {
        // A resumed answer is replayed from its first word.
        answer = "";
        try {
          const result = asking && question !== null
            ? await api.assistant.ask(question, handlers, abort.signal)
            : await api.assistant.resume(handlers, abort.signal);
          if (result.error) setError(result.error);
          break;
        } catch (failure) {
          if (abort.signal.aborted) break;
          if (failure instanceof AssistantRefused) {
            setError(failure.message);
            if (asking && question !== null) setInput((current) => current || question);
            break;
          }
          asking = false;
          dropped = true;
          if (tries >= RECONNECT_TRIES) {
            setError(LOST_CONNECTION);
            break;
          }
          if (question !== null) show({ status: "Reconnecting…" });
          await new Promise((resolve) => setTimeout(resolve, RECONNECT_MS));
          if (abort.signal.aborted) break;
        }
      }
    } finally {
      if (timer !== null) clearTimeout(timer);
      // Show the saved turns before dropping the live one, so the answer does not blink.
      await queryClient.invalidateQueries({ queryKey: MESSAGES_KEY });
      if (question !== null && dropped && !abort.signal.aborted) {
        // The connection may have dropped before Studio ever received the question.
        const saved = queryClient.getQueryData<AssistantMessage[]>(MESSAGES_KEY);
        if (saved && !saved.some((turn) => turn.role === "user" && turn.text === question)) {
          setError("Could not reach Studio. Check the connection and ask again.");
          setInput((current) => current || question);
        }
      }
      // A newer follow may own the page by now; leave its turn alone.
      if (controller.current === abort) {
        controller.current = null;
        setLive(null);
      }
    }
  };
  const followRef = useRef(follow);
  useEffect(() => {
    followRef.current = follow;
  });

  // Pick an answer back up after leaving the page, locking the phone, or reloading.
  useEffect(() => {
    const reattach = () => {
      if (document.hidden) return;
      setError((current) => (current === LOST_CONNECTION ? "" : current));
      void followRef.current(null);
    };
    reattach();
    document.addEventListener("visibilitychange", reattach);
    return () => {
      document.removeEventListener("visibilitychange", reattach);
      controller.current?.abort();
      controller.current = null;
    };
  }, []);

  const ask = (raw: string) => {
    const question = raw.trim();
    if (question && !live) void follow(question);
  };

  const stop = async () => {
    await api.assistant.stop().catch(() => undefined);
    controller.current?.abort();
  };

  const startOver = async () => {
    const confirmed = await confirmDialog("Clear this conversation? Your listings and sales are not touched.", {
      variant: "destructive",
      confirmLabel: "Clear conversation",
    });
    if (!confirmed) return;
    await api.assistant.clear();
    setError("");
    await queryClient.invalidateQueries({ queryKey: MESSAGES_KEY });
  };

  // Answers link the listings they name; open those in Studio instead of a new tab.
  const openLinkedListing = (event: MouseEvent<HTMLDivElement>) => {
    const link = (event.target as HTMLElement).closest("a");
    const id = linkedListingId(link?.getAttribute("href"));
    if (!id) return;
    event.preventDefault();
    const known = queryClient.getQueryData<{ id: string }[]>(["conversations"]);
    if (known && !known.some((listing) => listing.id === id)) {
      addToast({ type: "warning", title: "That listing is no longer in Studio." });
      return;
    }
    onOpenListing(id);
  };

  const drawn = live ? liveParts(live, turns) : { question: false, answer: false };
  const visible = live && drawn.answer ? stableStreamingText(live.answer) : "";
  const empty = !turns.length && !live && !messages.isLoading;
  const needsProvider = /sign in with chatgpt/i.test(error);

  return (
    <div className="assistant-page">
      <div
        className="assistant-scroll"
        ref={scroller}
        onScroll={(event) => {
          const el = event.currentTarget;
          pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
        }}
      >
        <div className="assistant-inner" onClick={openLinkedListing}>
          {empty ? (
            <div className="assistant-welcome">
              <h1>Ask about your business</h1>
              <p className="analytics-lead">
                The assistant reads every listing, sale, box, ad and sale event in Studio each time you ask. It
                answers questions and gives advice; it never changes a listing or sends anything.
              </p>
              <ul className="assistant-starters">
                {ASSISTANT_STARTERS.map((starter) => (
                  <li key={starter}>
                    <button type="button" className="assistant-starter" onClick={() => ask(starter)}>
                      {starter}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {messages.isError ? (
            <p className="analytics-status">{(messages.error as Error).message || "Could not load the conversation."}</p>
          ) : null}
          {turns.map((turn) => (
            <div key={turn.id} className={`msg ${turn.role === "user" ? "msg-user" : "msg-assistant"}`}>
              <ChatMarkdown text={turn.text} lineBreaks={turn.role === "user"} />
            </div>
          ))}
          {live ? (
            <>
              {drawn.question && live.question !== null ? (
                <div className="msg msg-user">
                  <ChatMarkdown text={live.question} lineBreaks />
                </div>
              ) : null}
              {visible ? (
                <div className="msg msg-assistant">
                  <ChatMarkdown text={visible} isStreaming />
                </div>
              ) : null}
              {drawn.answer ? (
                <div className="chat-activity is-busy" role="status">
                  <span className="chat-activity-dot" aria-hidden="true" />
                  <span className="chat-activity-text">{live.answer ? "Answering…" : live.status}</span>
                </div>
              ) : null}
            </>
          ) : null}
          {error ? (
            <div className="chat-error" role="alert">
              <div className="chat-error-text">{error}</div>
              {needsProvider ? (
                <div className="chat-error-actions">
                  <button type="button" className="btn btn-secondary btn-sm" onClick={onOpenProviders}>
                    Open provider settings
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
      <div className="chat-composer assistant-composer">
        <div className="assistant-inner">
          <div className="chat-composer-pill">
            <textarea
              className="chat-composer-input"
              rows={1}
              value={input}
              placeholder="Ask about sales, profit, stock, sourcing…"
              aria-label="Ask the business assistant"
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
                event.preventDefault();
                ask(input);
              }}
            />
            {live ? (
              <button
                type="button"
                className="chat-send chat-send-cancel"
                onClick={() => { void stop(); }}
                aria-label="Stop"
                title="Stop answering"
              >
                <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" aria-hidden="true">
                  <rect x="1" y="1" width="8" height="8" rx="1" />
                </svg>
              </button>
            ) : (
              <button
                type="button"
                className="chat-send"
                onClick={() => ask(input)}
                disabled={!input.trim()}
                aria-label="Send"
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <path d="M8 12.5V3.5M8 3.5L3.5 8M8 3.5L12.5 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            )}
          </div>
          {noteOpen ? <BusinessNote onClose={() => setNoteOpen(false)} /> : null}
          <div className="assistant-actions">
            <button type="button" className="assistant-action" aria-expanded={noteOpen} onClick={() => setNoteOpen((open) => !open)}>
              About your business
            </button>
            {turns.length && !live ? (
              <button type="button" className="assistant-action" onClick={() => { void startOver(); }}>
                Clear conversation
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * What the seller wants the assistant to keep in mind — goals, margins, what
 * they will not source — sent along with every question.
 */
function BusinessNote({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const saved = useQuery({ queryKey: NOTE_KEY, queryFn: api.assistant.note });
  const [draft, setDraft] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (note: string) => api.assistant.saveNote(note),
    onSuccess: (result) => {
      queryClient.setQueryData(NOTE_KEY, result);
      onClose();
    },
  });
  const note = draft ?? saved.data?.note ?? "";

  return (
    <form
      className="assistant-note"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(note);
      }}
    >
      <label htmlFor="assistant-note-text">About your business</label>
      <p className="analytics-note">
        Anything the assistant should keep in mind on every question: your goals, the margin you want, how much time
        you have, what you will not source, where you ship from.
      </p>
      <textarea
        id="assistant-note-text"
        className="input"
        rows={5}
        maxLength={NOTE_MAX}
        value={note}
        disabled={saved.isLoading}
        placeholder="I want at least $15 profit per item and sell mostly vintage menswear. I list about 20 items a week."
        onChange={(event) => setDraft(event.target.value)}
      />
      {save.isError ? <p className="chat-error-text">{(save.error as Error).message || "Could not save."}</p> : null}
      <div className="assistant-note-actions">
        <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
        <button type="submit" className="btn btn-primary btn-sm" disabled={save.isPending || saved.isLoading}>Save</button>
      </div>
    </form>
  );
}
