import express, { Router } from "express";
import { listUsers, createUser } from "./handlers";

const app = express();
const router = Router();
const userController = {
  list(req, res) {
    res.json([]);
  },
};

app.get("/users", listUsers);
router.post("/users", createUser);
app.use("/api", router);
app.get("/inline", (req, res) => res.json({ ok: true }));
app.get("/object", userController.list);
app.get("/ghost", ghostHandler);

export { router };
