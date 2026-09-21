// Photos also arrive by dragging them from Finder/Explorer onto the window.
// Browsers leave `type` empty for some camera formats (HEIC, most often), so
// fall back to the extension the server already accepts.
const IMAGE_EXTENSIONS = ["jpg", "jpeg", "png", "webp", "heic", "heif"];

export function isImageFile(file: { name?: string; type?: string }): boolean {
  const type = (file.type || "").toLowerCase();
  if (type.startsWith("image/")) return true;
  if (type) return false;
  const name = (file.name || "").toLowerCase();
  return IMAGE_EXTENSIONS.some((ext) => name.endsWith(`.${ext}`));
}

export function imageFilesFrom(transfer: DataTransfer | null): File[] {
  if (!transfer || !transfer.files) return [];
  return Array.from(transfer.files).filter((file) => isImageFile(file));
}

// A drag only exposes its file list on drop, so the hover state has to go by
// the advertised types. Reordering a thumbnail carries an id, never "Files".
export function dragHasFiles(transfer: DataTransfer | null): boolean {
  if (!transfer) return false;
  return Array.from(transfer.types || []).includes("Files");
}

export type PhotoFolderGroup = {
  /** Immediate parent path from webkitRelativePath, or null for a flat drop. */
  folder: string | null;
  files: File[];
};

/** Directory that immediately contains the file, from webkitRelativePath. */
export function folderKeyForFile(file: File): string | null {
  const relative = (file.webkitRelativePath || "").replace(/\\/g, "/").trim();
  if (!relative.includes("/")) return null;
  const parts = relative.split("/").filter(Boolean);
  if (parts.length < 2) return null;
  parts.pop();
  return parts.join("/") || null;
}

/** Last path segment — used as the new listing title. */
export function listingTitleForFolder(folder: string | null): string {
  if (!folder) return "New Listing";
  const name = folder.split("/").filter(Boolean).pop() || folder;
  const trimmed = name.trim();
  return trimmed ? trimmed.slice(0, 80) : "New Listing";
}

/**
 * Split image files into one group per source folder.
 *
 * Dropping `ItemA/` and `ItemB/` (or a parent that holds those subfolders)
 * yields two groups so Studio can open a draft per set of photos. A flat
 * multi-file drop with no relative paths stays a single group.
 */
export function groupImageFilesByFolder(files: File[]): PhotoFolderGroup[] {
  const images = files.filter((file) => isImageFile(file));
  if (!images.length) return [];

  const buckets = new Map<string, File[]>();
  let sawRelativePath = false;

  for (const file of images) {
    const key = folderKeyForFile(file);
    if (key !== null) sawRelativePath = true;
    const bucketKey = key ?? "";
    const list = buckets.get(bucketKey);
    if (list) list.push(file);
    else buckets.set(bucketKey, [file]);
  }

  if (!sawRelativePath) {
    return [{ folder: null, files: images }];
  }

  return Array.from(buckets.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, groupFiles]) => ({
      folder: key || null,
      files: groupFiles,
    }));
}
