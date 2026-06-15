import express from "express";
import { EventEmitter } from "events";
import { authMiddleware, createUser, listUsers } from "./handlers";

const app = express();
const emitter = new EventEmitter();

export function registerHandlers() {
  emitter.on("user.created", createUser);
}

export function triggerUserCreated() {
  emitter.emit("user.created", { id: "1" });
}

export function scheduleRefresh() {
  setTimeout(listUsers, 1000);
}

export function readApiUrl() {
  return process.env.API_URL;
}

app.get("/users", authMiddleware, listUsers);
