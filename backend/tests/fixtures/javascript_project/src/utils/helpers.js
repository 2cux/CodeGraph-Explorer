/**
 * CommonJS exports.foo pattern.
 */

function generateId() {
  return Math.random().toString(36).substring(7);
}

function hello(name) {
  return "Hello " + name;
}

// exports.foo pattern
exports.hello = hello;
exports.generateId = generateId;
