import { describe, expect, it, vi } from "vitest";
import { bulkListingNotes, createBulkPhotoListings } from "./bulkPhotoUpload";

function photo(name: string): File {
  return new File(["photo"], name, { type: "image/jpeg" });
}

describe("bulkListingNotes", () => {
  it("stores normalized COG and labels in Item Details notes", () => {
    expect(JSON.parse(bulkListingNotes({ cog: " 12.50 ", labels: " To List, Bin 4, " }) || "{}"))
      .toEqual({ cog: "12.50", vendooLabels: "To List, Bin 4" });
  });

  it("omits notes when both shared fields are blank", () => {
    expect(bulkListingNotes({ cog: "", labels: " , " })).toBeUndefined();
  });
});

describe("createBulkPhotoListings", () => {
  it("applies the shared notes to every created draft", async () => {
    const create = vi.fn()
      .mockResolvedValueOnce({ id: "listing-a" })
      .mockResolvedValueOnce({ id: "listing-b" });
    const uploadPhotos = vi.fn().mockResolvedValue({ ok: true, count: 1, photos: [] });

    const result = await createBulkPhotoListings(
      [
        { folder: "upload/Item A", files: [photo("a.jpg")] },
        { folder: "upload/Item B", files: [photo("b.jpg")] },
      ],
      { cog: "8", labels: "To List, Shelf A" },
      { create, uploadPhotos },
    );

    const expectedNotes = JSON.stringify({ cog: "8", vendooLabels: "To List, Shelf A" });
    expect(create).toHaveBeenNthCalledWith(1, { title: "Item A", notes: expectedNotes });
    expect(create).toHaveBeenNthCalledWith(2, { title: "Item B", notes: expectedNotes });
    expect(uploadPhotos).toHaveBeenNthCalledWith(1, "listing-a", expect.any(Array));
    expect(uploadPhotos).toHaveBeenNthCalledWith(2, "listing-b", expect.any(Array));
    expect(result.map((listing) => listing.convId)).toEqual(["listing-a", "listing-b"]);
  });
});
