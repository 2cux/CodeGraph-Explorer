export function listUsers(req, res) {
  res.json([]);
}

export function createUser(req, res) {
  res.status(201).json({ ok: true });
}

export function ghostHandler(req, res) {
  res.json({ ghost: true });
}
