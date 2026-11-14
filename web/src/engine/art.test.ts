import { describe, expect, it } from "vitest";
import { COLORS } from "./palette";
import { validateSheet, type SheetFile } from "./sheet";

// Every art/*.json sheet must be valid and use only palette keys.
const sheets = import.meta.glob("../art/*.json", { eager: true, import: "default" }) as Record<string, unknown>;
const KEYS = new Set(COLORS.map((c) => c.key));

describe("art sheets", () => {
  for (const [file, data] of Object.entries(sheets)) {
    if (file.endsWith("palette.json")) continue;
    it(file, () => { expect(validateSheet(data as SheetFile, KEYS, file)).toEqual([]); });
  }
});
