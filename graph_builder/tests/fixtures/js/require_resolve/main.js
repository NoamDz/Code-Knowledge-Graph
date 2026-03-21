const utils = require("./utils");

function doWork() {
  return utils.process("hello");
}

module.exports = { doWork };
