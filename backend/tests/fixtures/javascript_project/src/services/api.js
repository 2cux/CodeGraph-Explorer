const formatDate = require("../utils/format");
const { hello, generateId } = require("../utils/helpers");

/**
 * ES-style class with methods.
 */
class ApiService {
  constructor(baseUrl) {
    this.baseUrl = baseUrl;
  }

  async fetchUser(userId) {
    const id = generateId();
    const ts = formatDate(new Date());
    return "User:" + userId + " at " + ts + " [" + id + "]";
  }

  createButton(label) {
    const btn = new Button(label);
    return btn;
  }
}

/**
 * Old-style constructor function.
 */
function Button(label) {
  this.label = label;
}

Button.prototype.handleClick = function() {
  this.logClick();
};

Button.prototype.logClick = function() {
  console.log("clicked");
};

module.exports = { ApiService, Button };
