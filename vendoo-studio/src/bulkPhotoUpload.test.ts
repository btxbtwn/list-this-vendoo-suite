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

  it("adds the item's own SKU and typed measurements", () => {
    const notes = bulkListingNotes(
      { cog: "8", labels: "" },
      { sku: " LEV-505 ", garment: "pants", measurements: { waist: "16", inseam: " ", rise: "11" } },
    );
    expect(JSON.parse(notes || "{}")).toEqual({
      cog: "8",
      vendooLabels: "",
      sku: "LEV-505",
      garment: "pants",
      measurements: { pants: { waist: "16", rise: "11" } },
    });
  });

  it("leaves the garment out when nothing was measured", () => {
    expect(bulkListingNotes({ cog: "", labels: "" }, { sku: "", garment: "top", measurements: { length: " " } }))
      .toBeUndefined();
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

  it("keeps each item's SKU on its own draft", async () => {
    const create = vi.fn()
      .mockResolvedValueOnce({ id: "listing-a" })
      .mockResolvedValueOnce({ id: "listing-b" });
    const uploadPhotos = vi.fn().mockResolvedValue({ ok: true, count: 1, photos: [] });

    await createBulkPhotoListings(
      [
        { folder: "upload/Item A", files: [photo("a.jpg")], sku: "A1" },
        { folder: "upload/Item B", files: [photo("b.jpg")] },
      ],
      { cog: "", labels: "" },
      { create, uploadPhotos },
    );

    expect(create).toHaveBeenNthCalledWith(1, { title: "Item A", notes: JSON.stringify({ sku: "A1" }) });
    expect(create).toHaveBeenNthCalledWith(2, { title: "Item B" });
  });

  it("puts every draft in the chosen box", async () => {
    const create = vi.fn().mockResolvedValue({ id: "listing-a" });
    const uploadPhotos = vi.fn().mockResolvedValue({ ok: true, count: 1, photos: [] });

    await createBulkPhotoListings(
      [{ folder: "upload/Item A", files: [photo("a.jpg")] }],
      { cog: "", labels: "", boxId: "box-1" },
      { create, uploadPhotos },
    );

    expect(create).toHaveBeenCalledWith({ title: "Item A", box_id: "box-1" });
  });
});
