"""Builtin classifier: classifies unresolved calls as builtin/external/dynamic/truly_unresolved.

After CallResolver runs, many calls remain unresolved because they are calls to
language builtins (print, len, pairs), stdlib modules (string.format, os.path),
or well-known external libraries (cjson.encode, resty.redis).

This classifier examines unresolved calls and sets CallRef.classification to one of:
  - "builtin"          — language builtin or stdlib function
  - "external"         — known third-party library
  - "truly_unresolved" — genuinely unresolved (possible bug or missing resolver coverage)
  - None               — already resolved by CallResolver (skipped)

Usage:
    classifier = BuiltinClassifier()
    classifier.classify_all(all_asts)
    stats = classifier.stats()
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST


# ---------------------------------------------------------------------------
# Per-language lookup tables
# ---------------------------------------------------------------------------

LUA_BUILTINS = frozenset({
    "print", "pairs", "ipairs", "type", "tonumber", "tostring",
    "error", "assert", "next", "setmetatable", "getmetatable",
    "rawget", "rawset", "pcall", "xpcall", "require", "select",
    "unpack", "load", "loadfile", "dofile", "collectgarbage",
    "rawequal", "rawlen",
})

LUA_STDLIB_PREFIXES = frozenset({
    "string", "table", "math", "io", "os", "coroutine", "debug",
    "package", "utf8", "bit",
})

LUA_OPENRESTY_PREFIXES = frozenset({"ngx", "ndk"})

LUA_EXTERNAL_PREFIXES = frozenset({
    "cjson", "cmsgpack", "resty", "lfs", "lpeg", "socket",
    "pgmoon", "redis", "mysql",
})

# ---------------------------------------------------------------------------

PYTHON_BUILTINS = frozenset({
    "abs", "all", "any", "bool", "bytes", "callable", "chr", "dict", "dir",
    "enumerate", "eval", "filter", "float", "format", "frozenset", "getattr",
    "globals", "hasattr", "hash", "hex", "id", "input", "int", "isinstance",
    "issubclass", "iter", "len", "list", "locals", "map", "max", "min",
    "next", "object", "oct", "open", "ord", "pow", "print", "property",
    "range", "repr", "reversed", "round", "set", "setattr", "slice", "sorted",
    "staticmethod", "str", "sum", "super", "tuple", "type", "vars", "zip",
})

PYTHON_STDLIB_PREFIXES = frozenset({
    "os", "sys", "json", "re", "subprocess", "urllib", "collections",
    "datetime", "time", "pathlib", "logging", "threading", "multiprocessing",
    "functools", "itertools", "hashlib", "base64", "copy", "math", "random",
    "io", "abc", "typing", "enum", "contextlib", "traceback", "inspect",
    "signal", "socket", "http", "csv", "xml", "argparse", "shutil", "tempfile",
    "glob", "pickle", "sqlite3",
})

# ---------------------------------------------------------------------------

GO_BUILTINS = frozenset({
    "append", "cap", "clear", "close", "complex", "copy", "delete", "imag",
    "len", "make", "max", "min", "new", "panic", "print", "println", "real",
    "recover",
})

GO_STDLIB_PREFIXES = frozenset({
    "fmt", "io", "os", "path", "filepath", "strings", "bytes", "strconv",
    "encoding", "json", "net", "http", "sync", "time", "regexp", "sort",
    "errors", "context", "reflect", "testing", "log", "math", "crypto",
    "bufio", "flag", "runtime", "database", "html", "text",
})

# ---------------------------------------------------------------------------

JS_BUILTINS = frozenset({
    "parseInt", "parseFloat", "isNaN", "isFinite", "decodeURI",
    "decodeURIComponent", "encodeURI", "encodeURIComponent", "eval",
    "setTimeout", "setInterval", "clearTimeout", "clearInterval",
    "requestAnimationFrame", "alert", "confirm", "prompt", "atob", "btoa",
})

JS_BUILTIN_PREFIXES = frozenset({
    "console", "JSON", "Math", "Date", "Array", "Object", "String", "Number",
    "Boolean", "RegExp", "Error", "Promise", "Map", "Set", "Symbol", "Proxy",
    "Reflect", "document", "window", "navigator", "location", "history",
    "localStorage", "sessionStorage", "XMLHttpRequest", "fetch", "URL",
    "FormData", "WebSocket",
})

# ---------------------------------------------------------------------------

RUBY_BUILTINS = frozenset({
    "puts", "print", "p", "pp", "raise", "fail", "require", "require_relative",
    "load", "include", "extend", "prepend", "attr_reader", "attr_writer",
    "attr_accessor", "lambda", "proc", "loop", "sleep", "exit", "abort",
    "rand", "gets", "sprintf", "format", "warn", "open", "caller", "eval",
    "exec", "system", "fork", "spawn",
})

RUBY_STDLIB_PREFIXES = frozenset({
    "File", "Dir", "IO", "Time", "Date", "Regexp", "Array", "Hash", "String",
    "Integer", "Float", "Kernel", "Process", "Thread", "Mutex", "Queue", "ENV",
    "JSON", "YAML", "CSV", "ERB", "FileUtils", "Pathname", "URI", "Net",
    "Socket", "Digest", "Base64", "SecureRandom", "Logger", "Tempfile",
    "StringIO",
})


# ---------------------------------------------------------------------------
# Language config mapping
# ---------------------------------------------------------------------------

LANGUAGE_CONFIG = {
    "lua": {
        "builtins": LUA_BUILTINS,
        "builtin_prefixes": LUA_STDLIB_PREFIXES | LUA_OPENRESTY_PREFIXES,
        "external_prefixes": LUA_EXTERNAL_PREFIXES,
    },
    "python": {
        "builtins": PYTHON_BUILTINS,
        "builtin_prefixes": PYTHON_STDLIB_PREFIXES,
        "external_prefixes": frozenset(),
    },
    "go": {
        "builtins": GO_BUILTINS,
        "builtin_prefixes": GO_STDLIB_PREFIXES,
        "external_prefixes": frozenset(),
    },
    "javascript": {
        "builtins": JS_BUILTINS,
        "builtin_prefixes": JS_BUILTIN_PREFIXES,
        "external_prefixes": frozenset(),
    },
    "ruby": {
        "builtins": RUBY_BUILTINS,
        "builtin_prefixes": RUBY_STDLIB_PREFIXES,
        "external_prefixes": frozenset(),
    },
}

# Modules whose function aliases should be classified when used as bare names.
# Maps module name -> classification ("builtin" or "external").
_ALIAS_SOURCE_MODULES: dict[str, str] = {}
# Populate from existing Lua config
for _prefix in LUA_STDLIB_PREFIXES | LUA_OPENRESTY_PREFIXES:
    _ALIAS_SOURCE_MODULES[_prefix] = "builtin"
for _prefix in LUA_EXTERNAL_PREFIXES:
    _ALIAS_SOURCE_MODULES[_prefix] = "external"


class BuiltinClassifier:
    """Classifies unresolved calls as builtin, external, or truly_unresolved."""

    def __init__(self):
        self._counts: dict[str, int] = {
            "builtin": 0,
            "external": 0,
            "truly_unresolved": 0,
            "already_resolved": 0,
        }

    def classify_call(self, callee_string: str, language: str) -> str:
        """Classify a single call string for a given language.

        Returns one of: "builtin", "external", "truly_unresolved".
        """
        config = LANGUAGE_CONFIG.get(language)
        if not config:
            return "truly_unresolved"

        # Extract bare name (before first . or :)
        bare = callee_string.split(".")[0].split(":")[0]

        # Check global builtins set
        if bare in config["builtins"]:
            return "builtin"

        # Check stdlib/builtin prefix sets
        if bare in config["builtin_prefixes"]:
            return "builtin"

        # Check external prefix sets
        if bare in config["external_prefixes"]:
            return "external"

        return "truly_unresolved"

    def classify_all(self, all_asts: dict[str, FileAST]):
        """Classify all unresolved calls across all ASTs.

        Modifies CallRef.classification in place. Skips calls that already
        have resolved_module set (those were handled by CallResolver).

        For Lua files, builds a per-file alias map from FileAST.local_aliases
        so that bare calls like `format()` (aliased from `string.format`) are
        classified as builtin instead of truly_unresolved.
        """
        # Reset counts
        self._counts = {
            "builtin": 0,
            "external": 0,
            "truly_unresolved": 0,
            "already_resolved": 0,
        }

        for file_path, ast in all_asts.items():
            # Build per-file alias map for Lua files
            alias_map: dict[str, str] = {}
            if ast.language == "lua" and hasattr(ast, "local_aliases"):
                for local_name, rhs in ast.local_aliases:
                    # rhs is like "string.format" — extract the module prefix
                    prefix = rhs.split(".")[0]
                    if prefix in _ALIAS_SOURCE_MODULES:
                        alias_map[local_name] = _ALIAS_SOURCE_MODULES[prefix]

            for call in ast.calls:
                if call.resolved_module:
                    # Already resolved by CallResolver — skip
                    self._counts["already_resolved"] += 1
                    continue

                # Check alias map first (only for bare names without dots/colons)
                callee = call.callee_string
                if alias_map and "." not in callee and ":" not in callee and callee in alias_map:
                    classification = alias_map[callee]
                    call.classification = classification
                    self._counts[classification] += 1
                    continue

                classification = self.classify_call(callee, ast.language)
                call.classification = classification
                self._counts[classification] += 1

    def stats(self) -> dict[str, int]:
        """Return classification counts.

        Returns dict with keys: builtin, external, truly_unresolved, already_resolved.
        """
        return dict(self._counts)
