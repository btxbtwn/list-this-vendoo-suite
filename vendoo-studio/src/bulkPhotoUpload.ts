import type { PhotoUploadResult } from "./api/types";
import type { PhotoFolderGroup } from "./photoDrop";
import { listingTitleForFolder } from "./photoDrop";
import { joinLabels, splitLabels } from "./components/itemLabels";
import { notesWithMeasurements, typedMeasurements, type Garment } from "./components/garmentMeasurements";

export interface BulkUploadDefaults {
  cog: string;
  labels: string;
  /** The wholesale box these items came out of. */
  boxId?: string;
}

/** One folder's photos plus what the seller typed for that item alone. */
export interface BulkUploadItem extends PhotoFolderGroup {
  sku?: string;
  garment?: Garment;
  measurements?: Record<string, string>;
}

interface BulkUploadApi {
  create: (body: { title: string; notes?: string; box_id?: string }) => Promise<{ id: string }>;
  uploadPhotos: (convId: string, files: File[]) => Promise<PhotoUploadResult>;
}

export interface BulkListingUploadResult {
  convId: string;
  folder: string | null;
  count: number;
  errors: string[];
}

/** Build the same Item Details note fields used by an individually edited draft. */
export function bulkListingNotes(defaults: BulkUploadDefaults, item: Omit<BulkUploadItem, "files" | "folder"> = {}): string | undefined {
  const cog = defaults.cog.trim();
  const vendooLabels = joinLabels(splitLabels(defaults.labels));
  const sku = item.sku?.trim();
  const notes = {
    ...(cog || vendooLabels ? { cog, vendooLabels } : {}),
    ...(sku ? { sku } : {}),
  };
  const shared = Object.keys(notes).length ? JSON.stringify(notes) : undefined;
  const { garment, measurements = {} } = item;
  if (!garment || !Object.keys(typedMeasurements(garment, measurements)).length) return shared;
  return notesWithMeasurements(shared, garment, measurements);
}

/** Create each draft with its details already attached, then add its photos. */
export async function createBulkPhotoListings(
  items: BulkUploadItem[],
  defaults: BulkUploadDefaults,
  conversations: BulkUploadApi,
): Promise<BulkListingUploadResult[]> {
  const listings: BulkListingUploadResult[] = [];

  for (const item of items) {
    const notes = bulkListingNotes(defaults, item);
    const conv = await conversations.create({
      title: listingTitleForFolder(item.folder),
      ...(notes ? { notes } : {}),
      ...(defaults.boxId ? { box_id: defaults.boxId } : {}),
    });
    const result = await conversations.uploadPhotos(conv.id, item.files);
    listings.push({
      convId: conv.id,
      folder: item.folder,
      count: result.count,
      errors: result.errors || [],
    });
  }

  return listings;
}
