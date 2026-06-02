/**
 * CommonJS require / module.exports patterns.
 */

// Side-effect require
require("dotenv/config");

// Named imports via destructuring
const { join, resolve } = require("path");

// Default import
const express = require("express");

function buildPath(...parts) {
  return join(...parts);
}

function createServer() {
  const app = express();
  return app;
}

module.exports = {
  buildPath,
  createServer,
};
