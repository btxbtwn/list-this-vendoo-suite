import { describe, expect, it } from "vitest";
import {
  enqueueChatMessage,
  newQueuedChatMessage,
  removeChatMessage,
  takeNextChatMessage,
} from "./chatMessageQueue";

describe("chatMessageQueue", () => {
  it("keeps messages in submission order", () => {
    const first = newQueuedChatMessage("first");
    const second = newQueuedChatMessage("second");
    const queue = enqueueChatMessage(enqueueChatMessage([], first), second);
    expect(queue.map((message) => message.text)).toEqual(["first", "second"]);
  });

  it("takeNext hands the oldest message to exactly one caller", () => {
    const first = newQueuedChatMessage("first");
    const second = newQueuedChatMessage("second");
    const queue = enqueueChatMessage(enqueueChatMessage([], first), second);

    const taken = takeNextChatMessage(queue);
    expect(taken.next?.text).toBe("first");
    expect(taken.rest.map((message) => message.text)).toEqual(["second"]);
    expect(takeNextChatMessage([]).next).toBeNull();
  });

  it("remove keeps the other messages in order", () => {
    const first = newQueuedChatMessage("first");
    const second = newQueuedChatMessage("second");
    const third = newQueuedChatMessage("third");
    const queue = enqueueChatMessage(
      enqueueChatMessage(enqueueChatMessage([], first), second),
      third,
    );

    expect(removeChatMessage(queue, second.id).map((message) => message.text)).toEqual([
      "first",
      "third",
    ]);
  });

  it("snapshots browser fields onto the queued message", () => {
    const message = newQueuedChatMessage("fix material", {
      browserJobId: "job-1",
      browserFields: [{ marketplace: "depop", label: "Material", value: "Cotton" }],
    });
    expect(message.browserJobId).toBe("job-1");
    expect(message.browserFields).toEqual([
      { marketplace: "depop", label: "Material", value: "Cotton" },
    ]);
    expect(newQueuedChatMessage("plain").browserFields).toBeUndefined();
  });
});
