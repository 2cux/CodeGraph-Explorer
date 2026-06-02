import { formatDate } from "../utils/format";
import { generateId, validateId } from "../utils/helpers";
import { Button } from "../components/Button";
import type { ID } from "../utils/helpers";
import * as React from "react";

/**
 * API service class with methods that call imported functions.
 */
export class ApiService {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  async fetchUser(userId: ID): Promise<string> {
    if (!validateId(userId)) {
      throw new Error("Invalid ID");
    }
    const ts = formatDate(new Date());
    const id = generateId();
    return `User:${userId} at ${ts} [${id}]`;
  }

  async createButton(label: string): Promise<Button> {
    const btn = new Button({ label, onClick: () => {} });
    return btn;
  }
}

// Standalone function using imports
export async function initializeApi(baseUrl: string): Promise<ApiService> {
  return new ApiService(baseUrl);
}
