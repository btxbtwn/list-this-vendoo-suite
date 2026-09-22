import type { PhotoUploadResult } from "./api/types";
import type { PhotoFolderGroup } from "./photoDrop";
import { listingTitleForFolder } from "./photoDrop";
import { joinLabels, splitLabels } from "./components/itemLabels";

export interface BulkUploadDefaults {
  cog: string;
  labels: string;
}

interface BulkUploadApi {
  create: (body: { title: string; notes?: string }) => Promise<{ id: string }>;
  uploadPhotos: (convId: string, files: File[]) => Promise<PhotoUploadResult>;
}

export interface BulkListingUploadResult {
  convId: string;
  folder: string | null;
  count: number;
  errors: string[];
}

/** Build the same Item Details note fields used by an individually edited draft. */
export function bulkListingNotes(defaults: BulkUploadDefaults): string | undefined {
  const cog = defaults.cog.trim();
  const vendooLabels = joinLabels(splitLabels(defaults.labels));
  if (!cog && !vendooLabels) return undefined;
  return JSON.stringify({ cog, vendooLabels });
}

/** Create each draft with its shared details already attached, then add its photos. */
export async function createBulkPhotoListings(
  groups: PhotoFolderGroup[],
  defaults: BulkUploadDefaults,
  conversations: BulkUploadApi,
): Promise<BulkListingUploadResult[]> {
  const notes = bulkListingNotes(defaults);
  const listings: BulkListingUploadResult[] = [];

  for (const group of groups) {
    const conv = await conversations.create({
      title: listingTitleForFolder(group.folder),
      ...(notes ? { notes } : {}),
    });
    const result = await conversations.uploadPhotos(conv.id, group.files);
    listings.push({
      convId: conv.id,
      folder: group.folder,
      count: result.count,
      errors: result.errors || [],
    });
  }

  return listings;
}
