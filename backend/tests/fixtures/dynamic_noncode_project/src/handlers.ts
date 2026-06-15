export function listUsers() {
  return ["u1"];
}

export function createUser() {
  return { ok: true };
}

export function authMiddleware(req: unknown, res: unknown, next: () => void) {
  next();
}
