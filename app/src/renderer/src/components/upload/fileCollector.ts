import {
  isSupportedName,
  isTmapDataFile,
  getBaseName,
  getFilePath,
} from "../../constants/fileTypes";
import type {
  CollectionResult,
  CollectItemsOptions,
  CollectionProgressSnapshot,
} from "./types";

export const buildFileKey = (
  file: File,
  relative = file.webkitRelativePath || file.name,
) => `${relative}-${file.size}-${file.lastModified}`;
export const yieldToBrowser = () =>
  new Promise<void>((resolve) => setTimeout(resolve, 0));

interface Entry {
  name: string;
  isFile: boolean;
  isDirectory: boolean;
  file: (
    success: (file: File) => void,
    failure: (error: Error) => void,
  ) => void;
  createReader: () => {
    readEntries: (
      success: (entries: Entry[]) => void,
      failure: (error: Error) => void,
    ) => void;
  };
}
interface CollectedFile {
  file: File;
  relative: string;
}

/** Bounded file reads and cooperative traversal keep large folder drops responsive. */
export async function collectItemsFromDataTransfer(
  dataTransfer: DataTransfer,
  options: CollectItemsOptions = {},
): Promise<CollectionResult> {
  // Capture entry handles synchronously: browsers clear DataTransfer after the drop event.
  const entries = Array.from(dataTransfer.items || [])
    .map((item) => item.webkitGetAsEntry?.() as Entry | null)
    .filter((entry): entry is Entry => !!entry);
  const plain = entries.length ? [] : Array.from(dataTransfer.files || []);
  const progress: CollectionProgressSnapshot = {
    phase: "preparing",
    totalTopLevelEntries: entries.length || plain.length,
    processedItems: 0,
    discoveredFiles: 0,
    discoveredDirectories: 0,
    completed: false,
  };
  const files: CollectedFile[] = [];
  const folders = new Map<string, { name: string; files: CollectedFile[] }>();
  const batchSize = Math.max(1, options.yieldAfterEntries ?? 200);
  let processed = 0;
  const checkpoint = async () => {
    options.signal?.throwIfAborted();
    if (++processed % batchSize) return;
    options.onProgress?.({ ...progress });
    await yieldToBrowser();
  };
  options.onProgress?.({ ...progress });
  progress.phase = "collecting";
  options.onProgress?.({ ...progress });

  async function walk(entry: Entry, parent: string): Promise<CollectedFile[]> {
    options.signal?.throwIfAborted();
    const relative = parent ? `${parent}/${entry.name}` : entry.name;
    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) =>
        entry.file(resolve, (error) =>
          reject(error || new Error(`Unable to read ${relative}`)),
        ),
      );
      progress.discoveredFiles++;
      await checkpoint();
      return [{ file, relative }];
    }
    progress.discoveredDirectories++;
    progress.currentDirectoryName = entry.name;
    const reader = entry.createReader();
    const collected: CollectedFile[] = [];
    while (true) {
      const batch = await new Promise<Entry[]>((resolve, reject) =>
        reader.readEntries(resolve, (error) =>
          reject(error || new Error(`Unable to read ${relative}`)),
        ),
      );
      if (!batch.length) break;
      for (let start = 0; start < batch.length; start += 32) {
        const chunk = await Promise.all(
          batch
            .slice(start, start + 32)
            .filter((child) => child.isFile)
            .map((child) => walk(child, relative)),
        );
        for (const group of chunk)
          for (const item of group) collected.push(item);
        for (const directory of batch
          .slice(start, start + 32)
          .filter((child) => child.isDirectory)) {
          for (const item of await walk(directory, relative))
            collected.push(item);
        }
        await checkpoint();
      }
    }
    folders.set(relative.toLowerCase(), { name: entry.name, files: collected });
    return collected;
  }
  for (let start = 0; start < entries.length; start += 32) {
    const chunk = await Promise.all(
      entries
        .slice(start, start + 32)
        .filter((entry) => entry.isFile)
        .map((entry) => walk(entry, "")),
    );
    for (const group of chunk) for (const file of group) files.push(file);
    for (const directory of entries
      .slice(start, start + 32)
      .filter((entry) => entry.isDirectory)) {
      for (const item of await walk(directory, "")) files.push(item);
    }
    progress.processedItems += entries
      .slice(start, start + 32)
      .filter((entry) => entry.isDirectory).length;
  }
  for (const file of plain) {
    files.push({ file, relative: file.webkitRelativePath || file.name });
    progress.discoveredFiles++;
    await checkpoint();
  }
  if (plain.length) {
    // Folder pickers expose relative paths instead of DirectoryEntry handles.
    for (const item of files) {
      const pieces = item.relative.split("/");
      for (let depth = 1; depth < pieces.length; depth++) {
        const path = pieces.slice(0, depth).join("/").toLowerCase();
        if (!folders.has(path))
          folders.set(path, { name: pieces[depth - 1], files: [] });
        folders.get(path)!.files.push(item);
      }
    }
    options.onProgress?.({ ...progress });
  }
  progress.phase = "matching";
  options.onProgress?.({ ...progress });
  const used = new Set<File>(),
    usedFolders = new Set<string>();
  const result: CollectionResult = {
    items: [],
    orphanFolders: [],
    orphanDtFiles: new Map(),
    unsupportedFileNames: [],
    jsonFiles: [],
  };
  const dataFiles = new Map<string, File[]>();
  for (const { file, relative } of files)
    if (isTmapDataFile(file.name)) {
      const base = relative.replace(/\.[^/.]+$/, "").toLowerCase();
      const list = dataFiles.get(base) || [];
      list.push(file);
      dataFiles.set(base, list);
    }
  for (const { file, relative } of files) {
    if (!/\.(mrxs|tmap)$/i.test(file.name)) continue;
    const base = relative.replace(/\.[^/.]+$/, "").toLowerCase();
    const type = file.name.toLowerCase().endsWith(".mrxs") ? "mrxs" : "tmap";
    const associated =
      type === "mrxs"
        ? folders.get(base)?.files.map((item) => item.file) || []
        : dataFiles.get(base) || [];
    if (type === "mrxs" && folders.has(base)) usedFolders.add(base);
    used.add(file);
    associated.forEach((item) => used.add(item));
    const path = getFilePath(file);
    result.items.push({
      key: path || buildFileKey(file, relative),
      name: file.name,
      file,
      path,
      type,
      associatedFiles: associated,
      missingAssociated: !path && !associated.length,
    });
    await checkpoint();
  }
  // Unmatched data folders may arrive before their .mrxs header. Ordinary nested
  // image directories are always traversed as image collections, never hidden here.
  for (const [path, folder] of [...folders].sort(
    ([a], [b]) => a.length - b.length,
  )) {
    if (
      usedFolders.has(path) ||
      folder.files.some(
        ({ file }) =>
          isSupportedName(file.name) ||
          file.name.toLowerCase().endsWith(".json") ||
          isTmapDataFile(file.name),
      )
    )
      continue;
    const uncovered = folder.files.filter(({ file }) => !used.has(file));
    if (!uncovered.length) continue;
    result.orphanFolders.push({
      folderName: folder.name,
      folderFiles: uncovered.map((item) => item.file),
    });
    uncovered.forEach(({ file }) => used.add(file));
  }
  for (const { file, relative } of files) {
    if (used.has(file)) continue;
    if (isTmapDataFile(file.name)) {
      const base = getBaseName(file.name).toLowerCase();
      const list = result.orphanDtFiles.get(base) || [];
      list.push(file);
      result.orphanDtFiles.set(base, list);
    } else if (file.name.toLowerCase().endsWith(".json"))
      result.jsonFiles.push(file);
    else if (isSupportedName(file.name)) {
      const path = getFilePath(file);
      result.items.push({
        key: path || buildFileKey(file, relative),
        name: file.name,
        file,
        path,
        type: "standard",
      });
    } else result.unsupportedFileNames.push(file.name);
    await checkpoint();
  }
  options.onProgress?.({
    ...progress,
    phase: "complete",
    completed: true,
    currentDirectoryName: undefined,
  });
  return result;
}
