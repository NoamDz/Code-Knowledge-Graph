// Test fixture for JS export pattern detection
// Tests all the export patterns that should be recognized

const helper = require("./helper");
const utils = require("../utils");

class DataCollector {
  constructor() {
    this.data = [];
  }

  collect(item) {
    this.data.push(item);
  }

  flush() {
    const result = this.data;
    this.data = [];
    return result;
  }
}

function processData(raw) {
  return raw.map(item => item.value);
}

const formatOutput = (data) => {
  return JSON.stringify(data);
};

// Pattern 1: module.exports = ClassName (identifier)
// Uncomment to test: module.exports = DataCollector;

// Pattern 2: module.exports = function(){}
// Uncomment to test: module.exports = function() { return 42; };

// Pattern 3: exports.foo = value
exports.processData = processData;
exports.formatOutput = formatOutput;

// Pattern 4: module.exports.ClassName = DataCollector
module.exports.DataCollector = DataCollector;
