import { generateId, type ID } from "./helpers";

/**
 * Default export — a formatting function.
 */
export default function formatDate(date: Date): string {
  const id: ID = generateId();
  return `${date.toISOString()} [${id}]`;
}

/** Named export alongside default. */
export function formatNumber(n: number): string {
  return n.toLocaleString("en-US");
}
