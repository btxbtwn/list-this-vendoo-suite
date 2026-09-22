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

type EntryLike = {
  isFile: boolean;
  isDirectory: boolean;
  name: string;
};

type FileEntryLike = EntryLike & {
  file: (success: (file: File) => void, error?: (err: DOMException) => void) => void;
};

type DirectoryReaderLike = {
  readEntries: (
    success: (entries: EntryLike[]) => void,
    error?: (err: DOMException) => void,
  ) => void;
};

type DirectoryEntryLike = EntryLike & {
  createReader: () => DirectoryReaderLike;
};

function withRelativePath(file: File, relativePath: string): File {
  // Entry.file() Files often lock webkitRelativePath to "". Clone so we can
  // stamp the folder path the bulk-upload grouper reads.
  const stamped = new File([file], file.name, {
    type: file.type,
    lastModified: file.lastModified,
  });
  Object.defineProperty(stamped, "webkitRelativePath", {
    configurable: true,
    enumerable: true,
    value: relativePath,
  });
  return stamped;
}

/** Chrome returns directory entries in batches of ~100; keep reading until empty. */
function readAllDirectoryEntries(dir: DirectoryEntryLike): Promise<EntryLike[]> {
  const reader = dir.createReader();
  const entries: EntryLike[] = [];
  return new Promise((resolve, reject) => {
    const readBatch = () => {
      reader.readEntries((batch) => {
        if (!batch.length) {
          resolve(entries);
          return;
        }
        entries.push(...batch);
        readBatch();
      }, reject);
    };
    readBatch();
  });
}

async function imageFilesFromEntry(entry: EntryLike, pathPrefix: string): Promise<File[]> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) => {
      (entry as FileEntryLike).file(resolve, reject);
    });
    if (!isImageFile(file)) return [];
    if (!pathPrefix) return [file];
    return [withRelativePath(file, `${pathPrefix}/${file.name}`)];
  }
  if (!entry.isDirectory) return [];

  const children = await readAllDirectoryEntries(entry as DirectoryEntryLike);
  const nextPrefix = pathPrefix ? `${pathPrefix}/${entry.name}` : entry.name;
  const nested = await Promise.all(children.map((child) => imageFilesFromEntry(child, nextPrefix)));
  return nested.flat();
}

/**
 * Collect images from a drop, including folders.
 *
 * Folder drops often put only directory stubs in `files`. Walk
 * `webkitGetAsEntry()` so each product folder's photos are recovered with a
 * `webkitRelativePath` the bulk-upload grouper can split on. Fall back to the
 * flat `files` list when the entry API is missing or empty.
 */
export async function imageFilesFromTransfer(transfer: DataTransfer | null): Promise<File[]> {
  if (!transfer) return [];

  const items = transfer.items ? Array.from(transfer.items) : [];
  const entries: EntryLike[] = [];

  // Capture every entry before the first await. Browsers invalidate the drag
  // data store when the drop callback returns, so asking for item 2 only after
  // item 1 has been enumerated makes a multi-folder drop lose every folder
  // except the first one.
  for (const item of items) {
    if (item.kind !== "file") continue;
    const getter = (item as DataTransferItem & {
      webkitGetAsEntry?: () => EntryLike | null;
    }).webkitGetAsEntry;
    if (typeof getter !== "function") continue;
    const entry = getter.call(item);
    if (!entry) continue;
    entries.push(entry);
  }

  const expanded = await Promise.all(entries.map(async (entry) => {
    try {
      return await imageFilesFromEntry(entry, "");
    } catch {
      return [];
    }
  }));
  const fromEntries = expanded.flat();

  if (entries.length && fromEntries.length) return fromEntries;
  return imageFilesFrom(transfer);
}
