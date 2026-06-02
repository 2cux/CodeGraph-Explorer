/**
 * Utility helpers — named exports, type aliases, interfaces.
 */

export type ID = string | number;

export interface HasID {
  id: ID;
}

export function generateId(): string {
  return Math.random().toString(36).substring(7);
}

export function validateId(id: ID): boolean {
  return typeof id === "string" || typeof id === "number";
}

// Internal helper — not exported
function _normalize(s: string): string {
  return s.trim().toLowerCase();
}
