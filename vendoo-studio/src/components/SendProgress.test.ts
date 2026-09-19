import { describe, expect, it } from "vitest";
import { sendStepRange } from "./SendProgress";

describe("sendStepRange", () => {
  it("treats the job's initial create step as the start of the send", () => {
    expect(sendStepRange("vendoo_api_create", -1).index).toBe(0);
  });

  it("maps later steps further along the bar", () => {
    const fields = sendStepRange("vendoo_api_fields", 1);
    const create = sendStepRange("vendoo_api_create", fields.index);
    expect(create.floor).toBeGreaterThanOrEqual(fields.ceiling);
  });

  it("never rewinds to an earlier step", () => {
    expect(sendStepRange("vendoo_api_categories", 3).index).toBe(3);
  });
});
