/**
 * Main entry point — CommonJS module.exports pattern.
 */
const { hello } = require("./utils/helpers");
const format = require("./utils/format");

function main() {
  const greeting = hello("World");
  const formatted = format(greeting);
  console.log(formatted);
}

module.exports = { main, hello };
