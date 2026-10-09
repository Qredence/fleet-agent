import Ajv from "ajv";
import schema from "@fleet-agent/contracts/inline-card.schema.json";
import type { InlineCard } from "@/contracts/inline-card";
const validate = new Ajv({ strict: true }).compile<InlineCard>(schema);
/** Validate current envelopes and normalize bounded historical v1 payloads. */
export function cardData(
  value: unknown,
  kind: string,
): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value))
    return null;
  const raw = value as Record<string, unknown>;
  let envelope: unknown = raw;
  if (
    raw.schemaVersion === 1 ||
    (kind === "artifact" && raw.schemaVersion === undefined)
  ) {
    const { schemaVersion: _version, ...data } = raw;
    envelope = {
      schemaVersion: 2,
      kind,
      runId: "legacy",
      messageId: "legacy",
      data,
    };
  }
  if (!validate(envelope) || envelope.kind !== kind) return null;
  return { ...envelope.data, schemaVersion: 1 };
}
