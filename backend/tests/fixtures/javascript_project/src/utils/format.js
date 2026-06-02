/**
 * Default export via module.exports.
 */
function formatDate(date) {
  return date.toISOString();
}

// module.exports = single function (default export)
module.exports = formatDate;
