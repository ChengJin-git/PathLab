export interface NamedSegmentationItem {
  name: string;
}

const JSON_SUFFIX_REGEX = /\.json$/i;
const FILE_SUFFIX_REGEX = /\.[^/.]+$/;

export function getSegmentationStem(name: string): string {
  return name.replace(JSON_SUFFIX_REGEX, '').replace(FILE_SUFFIX_REGEX, '').toLowerCase();
}

export function mergeSegmentationJsonFiles(
  existing: Map<string, File>,
  files: File[],
): { jsonFilesByStem: Map<string, File>; duplicateJsonStems: string[] } {
  const jsonFilesByStem = new Map(existing);
  const duplicateJsonStems = new Set<string>();

  files.forEach((file) => {
    const stem = getSegmentationStem(file.name);
    if (jsonFilesByStem.has(stem)) {
      duplicateJsonStems.add(stem);
      return;
    }
    jsonFilesByStem.set(stem, file);
  });

  return {
    jsonFilesByStem,
    duplicateJsonStems: Array.from(duplicateJsonStems).sort(),
  };
}

export function summarizeSegmentationMatches<T extends NamedSegmentationItem>(
  items: T[],
  jsonFilesByStem: Map<string, File>,
): {
  duplicateImageStems: string[];
  missingImageStems: string[];
  orphanJsonStems: string[];
  matchedStems: Set<string>;
} {
  const duplicateImageStems = new Set<string>();
  const missingImageStems = new Set<string>();
  const seenImageStems = new Set<string>();
  const matchedStems = new Set<string>();

  items.forEach((item) => {
    const stem = getSegmentationStem(item.name);
    if (seenImageStems.has(stem)) {
      duplicateImageStems.add(stem);
    } else {
      seenImageStems.add(stem);
    }

    if (jsonFilesByStem.has(stem)) {
      matchedStems.add(stem);
    } else {
      missingImageStems.add(stem);
    }
  });

  const orphanJsonStems = Array.from(jsonFilesByStem.keys())
    .filter((stem) => !seenImageStems.has(stem))
    .sort();

  return {
    duplicateImageStems: Array.from(duplicateImageStems).sort(),
    missingImageStems: Array.from(missingImageStems).sort(),
    orphanJsonStems,
    matchedStems,
  };
}
