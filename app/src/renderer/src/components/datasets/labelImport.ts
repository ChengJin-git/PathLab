import Papa from "papaparse";
import type { TaskType } from "../../constants/training";
import { readFileText } from "../../lib/utils/csvImporter";

export async function parseLabelFiles(
  table: File | null,
  files: Partial<Record<TaskType, File>>,
) {
  let rows: Record<string, unknown>[] = [];
  if (table) {
    const parsed = Papa.parse<Record<string, string>>(
      await readFileText(table),
      {
        header: true,
        skipEmptyLines: true,
        transformHeader: (key) => key.trim(),
      },
    );
    if (parsed.errors.length) throw new Error(parsed.errors[0].message);
    rows = parsed.data.map((row) => {
      if (!row.filename?.trim()) throw new Error("filename is required");
      const item: Record<string, unknown> = { filename: row.filename.trim() };
      const metadata: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(row)) {
        if (key === "filename" || !value.trim()) continue;
        if (["age", "event_time", "event_status"].includes(key)) {
          const number = Number(value);
          if (!Number.isFinite(number))
            throw new Error(`Invalid ${key}: ${value}`);
          item[key] = number;
        } else if (["label", "case_id", "gender", "split"].includes(key))
          item[key] = value.trim();
        else metadata[key] = value;
      }
      if (Object.keys(metadata).length) item.metadata = metadata;
      return item;
    });
  }
  const annotations: Partial<Record<TaskType, Record<string, unknown>>> = {};
  for (const [task, file] of Object.entries(files))
    if (file)
      annotations[task as TaskType] = JSON.parse(await readFileText(file));
  return { rows, annotations };
}
