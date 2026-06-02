/**
 * Shared type definitions — interface and type alias exports.
 */

export interface User {
  id: number;
  name: string;
  email: string;
}

export type UserList = User[];

export interface AdminUser extends User {
  role: "admin" | "superadmin";
  permissions: string[];
}

export type ApiResponse<T> = {
  data: T;
  status: number;
  ok: boolean;
};
