// Test fixture for IIFE / revealing module pattern
// This is the pattern used by browser-side JS files like container.js.erb

(function() {
  var win = window;
  var doc = document;

  var MyModule = (function() {
    var privateState = {};

    function publicMethod() {
      return privateState;
    }

    function anotherPublic(data) {
      privateState = data;
      _helperPrivate();
    }

    function _helperPrivate() {
      console.log("internal");
    }

    function collect(id, data, immediate) {
      // Send data to backend
      fetch("/api/collect", {
        method: "POST",
        body: JSON.stringify({ id: id, data: data })
      });
    }

    return {
      publicMethod: publicMethod,
      anotherPublic: anotherPublic,
      collect: collect,
      version: "1.0"
    };
  })();

  window.MyModule = MyModule;
})();
