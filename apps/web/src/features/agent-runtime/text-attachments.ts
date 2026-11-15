import {
  CompositeAttachmentAdapter,
  SimpleTextAttachmentAdapter,
  type AttachmentAdapter,
  type PendingAttachment,
} from "@assistant-ui/react";

const TEXT_MIME_TYPES = new Set([
  "text/plain",
  "text/html",
  "text/markdown",
  "text/csv",
  "text/tab-separated-values",
  "text/xml",
  "text/json",
  "application/json",
  "text/css",
  "text/yaml",
  "application/yaml",
  "application/x-yaml",
]);

const TEXT_FILE_EXTENSIONS = [
  ".txt",
  ".md",
  ".markdown",
  ".csv",
  ".tsv",
  ".json",
  ".xml",
  ".html",
  ".htm",
  ".css",
  ".yaml",
  ".yml",
  ".log",
] as const;

function normalizeMimeType(mimeType: string | undefined): string {
  return (mimeType ?? "").split(";", 1)[0]?.trim().toLowerCase() ?? "";
}

function hasAllowedTextExtension(name: string | undefined): boolean {
  if (!name) return false;
  const lower = name.trim().toLowerCase();
  return TEXT_FILE_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

export function supportsTextFile(
  file: Pick<File, "type"> & { name?: string },
): boolean {
  const normalizedMime = normalizeMimeType(file.type);
  if (normalizedMime) {
    return TEXT_MIME_TYPES.has(normalizedMime);
  }
  return hasAllowedTextExtension(file.name);
}

class TextAttachmentAdapter
  extends SimpleTextAttachmentAdapter
  implements AttachmentAdapter
{
  public override accept = [
    ...TEXT_MIME_TYPES,
    ...TEXT_FILE_EXTENSIONS,
  ].join(",");

  public override add(state: { file: File }): Promise<PendingAttachment> {
    if (!supportsTextFile(state.file)) {
      throw new Error("No matching adapter found for file");
    }
    return super.add(state);
  }
}

// All entry paths share one adapter; files become text parts at submission.
export const attachmentAdapter = new CompositeAttachmentAdapter([
  new TextAttachmentAdapter(),
]);
