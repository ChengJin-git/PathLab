import { getBaseName } from "../../constants/fileTypes";
import type { CollectionResult, LocalItem } from "./types";

export function mergeCollection(
  existing: LocalItem[],
  incoming: CollectionResult,
  pendingFolders: Map<string, File[]>,
  pendingData: Map<string, File[]>,
) {
  const folders = new Map(pendingFolders),
    data = new Map(pendingData);
  const mergeFiles = (a: File[], b: File[]) =>
    Array.from(
      new Map(
        [...a, ...b].map((file) => [
          `${file.webkitRelativePath || file.name}:${file.size}:${file.lastModified}`,
          file,
        ]),
      ).values(),
    );
  for (const folder of incoming.orphanFolders) {
    const key = folder.folderName.toLowerCase();
    folders.set(key, mergeFiles(folders.get(key) || [], folder.folderFiles));
  }
  for (const [name, files] of incoming.orphanDtFiles) {
    const key = name.toLowerCase();
    data.set(key, mergeFiles(data.get(key) || [], files));
  }
  const items = new Map(existing.map((item) => [item.key, item]));
  for (const item of incoming.items) {
    const previous = items.get(item.key);
    items.set(
      item.key,
      previous
        ? {
            ...previous,
            ...item,
            associatedFiles: mergeFiles(
              previous.associatedFiles || [],
              item.associatedFiles || [],
            ),
          }
        : item,
    );
  }
  for (const [key, item] of items) {
    if (item.type !== "mrxs" && item.type !== "tmap") continue;
    const collection = item.type === "mrxs" ? folders : data;
    const base = getBaseName(item.name).toLowerCase();
    const files = mergeFiles(
      item.associatedFiles || [],
      collection.get(base) || [],
    );
    if (files.length) {
      items.set(key, {
        ...item,
        associatedFiles: files,
        missingAssociated: false,
      });
      collection.delete(base);
    }
  }
  return { items: Array.from(items.values()), folders, data };
}
