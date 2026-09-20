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
