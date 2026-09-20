import { describe, expect, it } from "vitest";
import { dragHasFiles, imageFilesFrom, isImageFile } from "./photoDrop";

function file(name: string, type: string): File {
  return new File(["x"], name, { type });
}

describe("isImageFile", () => {
  it("accepts anything the browser labels an image", () => {
    expect(isImageFile(file("front.jpg", "image/jpeg"))).toBe(true);
    expect(isImageFile(file("tag.PNG", "image/png"))).toBe(true);
  });

  it("falls back to the extension when the browser reports no type", () => {
    expect(isImageFile(file("IMG_0421.HEIC", ""))).toBe(true);
    expect(isImageFile(file("notes", ""))).toBe(false);
  });

  it("rejects non-image files even when the extension looks like one", () => {
    expect(isImageFile(file("invoice.pdf", "application/pdf"))).toBe(false);
    expect(isImageFile(file("photos.jpg.zip", "application/zip"))).toBe(false);
  });
});

describe("imageFilesFrom", () => {
  it("keeps only the images in a mixed drop", () => {
    const transfer = {
      files: [file("front.jpg", "image/jpeg"), file("receipt.pdf", "application/pdf")],
    } as unknown as DataTransfer;
    expect(imageFilesFrom(transfer).map((f) => f.name)).toEqual(["front.jpg"]);
  });

  it("handles a drag with no files", () => {
    expect(imageFilesFrom(null)).toEqual([]);
    expect(imageFilesFrom({ files: null } as unknown as DataTransfer)).toEqual([]);
  });
});

describe("dragHasFiles", () => {
  it("is true for a file drag and false for a thumbnail reorder", () => {
    expect(dragHasFiles({ types: ["Files"] } as unknown as DataTransfer)).toBe(true);
    expect(
      dragHasFiles({ types: ["application/x-vendoo-photo-id", "text/plain"] } as unknown as DataTransfer),
    ).toBe(false);
    expect(dragHasFiles(null)).toBe(false);
  });
});
