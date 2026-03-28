var Utils = (function(){
  function isString(val) { return typeof val === "string"; }
  function isArray(val) { return Array.isArray(val); }
  return { isString: isString, isArray: isArray };
})();
