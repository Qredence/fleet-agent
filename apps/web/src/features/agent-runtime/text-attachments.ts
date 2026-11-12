import {
  CompositeAttachmentAdapter,
  SimpleTextAttachmentAdapter,
} from "@assistant-ui/react";

// All entry paths share one adapter; files become text parts at submission.
export const attachmentAdapter = new CompositeAttachmentAdapter([
  new SimpleTextAttachmentAdapter(),
]);
export function supportsTextFile(file: Pick<File, "type">): boolean {
  return attachmentAdapter.accept.split(",").includes(file.type);
}
