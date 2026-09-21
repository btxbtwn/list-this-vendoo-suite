import { describe, expect, it } from "vitest";
import {
  dragHasFiles,
  folderKeyForFile,
  groupImageFilesByFolder,
  imageFilesFrom,
  isImageFile,
  listingTitleForFolder,
} from "./photoDrop";

function file(name: string, type: string, relativePath = ""): File {
  const created = new File(["x"], name, { type });
  Object.defineProperty(created, "webkitRelativePath", { value: relativePath });
  return created;
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

describe("folderKeyForFile", () => {
  it("returns null for a flat file with no relative path", () => {
    expect(folderKeyForFile(file("front.jpg", "image/jpeg"))).toBe(null);
  });

  it("uses the immediate parent directory", () => {
    expect(folderKeyForFile(file("front.jpg", "image/jpeg", "NikeTee/front.jpg"))).toBe("NikeTee");
    expect(
      folderKeyForFile(file("front.jpg", "image/jpeg", "Batch/NikeTee/front.jpg")),
    ).toBe("Batch/NikeTee");
  });
});

describe("listingTitleForFolder", () => {
  it("uses the last path segment", () => {
    expect(listingTitleForFolder(null)).toBe("New Listing");
    expect(listingTitleForFolder("NikeTee")).toBe("NikeTee");
    expect(listingTitleForFolder("Batch/Adidas Hoodie")).toBe("Adidas Hoodie");
  });
});

describe("groupImageFilesByFolder", () => {
  it("keeps a flat multi-file drop as one group", () => {
    const groups = groupImageFilesByFolder([
      file("front.jpg", "image/jpeg"),
      file("back.jpg", "image/jpeg"),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].folder).toBe(null);
    expect(groups[0].files.map((f) => f.name)).toEqual(["front.jpg", "back.jpg"]);
  });

  it("splits multiple product folders into separate groups", () => {
    const groups = groupImageFilesByFolder([
      file("a.jpg", "image/jpeg", "NikeTee/a.jpg"),
      file("b.jpg", "image/jpeg", "NikeTee/b.jpg"),
      file("c.jpg", "image/jpeg", "AdidasHoodie/c.jpg"),
      file("notes.txt", "text/plain", "AdidasHoodie/notes.txt"),
    ]);
    expect(groups.map((g) => g.folder)).toEqual(["AdidasHoodie", "NikeTee"]);
    expect(groups[0].files.map((f) => f.name)).toEqual(["c.jpg"]);
    expect(groups[1].files.map((f) => f.name)).toEqual(["a.jpg", "b.jpg"]);
  });

  it("splits sibling item folders under a shared parent", () => {
    const groups = groupImageFilesByFolder([
      file("a.jpg", "image/jpeg", "Batch/Item1/a.jpg"),
      file("b.jpg", "image/jpeg", "Batch/Item2/b.jpg"),
    ]);
    expect(groups.map((g) => g.folder)).toEqual(["Batch/Item1", "Batch/Item2"]);
  });

  it("keeps one folder of photos as a single group", () => {
    const groups = groupImageFilesByFolder([
      file("a.jpg", "image/jpeg", "NikeTee/a.jpg"),
      file("b.jpg", "image/jpeg", "NikeTee/b.jpg"),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].folder).toBe("NikeTee");
  });
});
