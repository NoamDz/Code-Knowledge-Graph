# Quick Fixes Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eight surgical fixes: Go Redis .Result() chaining, Python self-resolution, Python RedisCluster, Ruby preprocessor loading, Ruby metrics fix, Go interfaces, Ruby Redis detection, and Tornado route detection.

**Architecture:** Each fix is independent and modifies 1-2 existing files. Fixes target: redis_abstraction_resolver (Go Redis), call_resolver (Python self), python_parser (RedisCluster + Tornado), ruby_resolver (loading), ruby_parser (module_name + Redis), graph_health (metrics), go_parser + go_resolver (interfaces).

**Tech Stack:** Python, Tree-sitter, existing parser/resolver infrastructure

---

## File Structure

| File | Action | Fixes |
|------|--------|-------|
| `graph_builder/resolvers/redis_abstraction_resolver.py` | Modify | 4A |
| `graph_builder/validate/graph_health.py` | Modify | 4A, 4E |
| `graph_builder/resolvers/call_resolver.py` | Modify | 4B |
| `graph_builder/parsers/python_parser.py` | Modify | 4C, 4H |
| `graph_builder/resolvers/ruby_resolver.py` | Modify | 4D |
| `graph_builder/parsers/ruby_parser.py` | Modify | 4E, 4G |
| `graph_builder/parsers/base.py` | Modify | 4F |
| `graph_builder/parsers/go_parser.py` | Modify | 4F |
| `graph_builder/resolvers/go_resolver.py` | Modify | 4F |
| `graph_builder/ingestion/writer.py` | Modify | 4D, 4F |
| `graph_builder/tests/test_quick_fixes.py` | Create | All 8 fixes |
| `graph_builder/tests/fixtures/go/redis_wrapper.go` | Create | 4A |
| `graph_builder/tests/fixtures/python/self_calls.py` | Create | 4B |
| `graph_builder/tests/fixtures/python/redis_cluster_service.py` | Create | 4C |
| `graph_builder/tests/fixtures/ruby/preprocessor_loader.rb` | Create | 4D |
| `graph_builder/tests/fixtures/ruby/preprocess/strip_whitespace.rb` | Create | 4D |
| `graph_builder/tests/fixtures/ruby/class_with_calls.rb` | Create | 4E |
| `graph_builder/tests/fixtures/go/interfaces.go` | Create | 4F |
| `graph_builder/tests/fixtures/ruby/redis_helper.rb` | Create | 4G |
| `graph_builder/tests/fixtures/python/tornado_app.py` | Create | 4H |

---

## Task 1: Fix 4A — Go Redis Indicators and Method Lists

Go Redis calls use `r.client.HGet(ctx, key).Result()` internally and wrapper methods like `HGetAsString` externally. The resolver misses these because (1) `_GO_REDIS_INDICATORS` does not contain `"client"` and (2) the method sets lack standard go-redis methods (`HGet`, `Get`) and wrapper methods (`HGetAsString`, etc.). Also, `resolve_go_redis_abstractions()` is never called from `graph_health.py`.

**Files:**
- Modify: `graph_builder/resolvers/redis_abstraction_resolver.py`
- Modify: `graph_builder/validate/graph_health.py`
- Create: `graph_builder/tests/fixtures/go/redis_wrapper.go`
- Create (start): `graph_builder/tests/test_quick_fixes.py`

### Step 1: Create test fixture

- [ ] **1.1: Create Go fixture with `r.client` pattern**

Create `graph_builder/tests/fixtures/go/redis_wrapper.go`:

```go
package redis

import (
	"context"
	"time"
	"github.com/go-redis/redis/v8"
)

type RedisClient struct {
	client *redis.Client
}

func NewRedisClient(addr string) *RedisClient {
	return &RedisClient{
		client: redis.NewClient(&redis.Options{Addr: addr}),
	}
}

func (r *RedisClient) HGetAsString(ctx context.Context, key, field string) (string, error) {
	return r.client.HGet(ctx, key, field).Result()
}

func (r *RedisClient) GetAsInt(ctx context.Context, key string) (int64, error) {
	return r.client.Get(ctx, key).Int64()
}

func (r *RedisClient) HSetWithExpire(ctx context.Context, key, field string, value interface{}, ttl time.Duration) error {
	pipe := r.client.Pipeline()
	pipe.HSet(ctx, key, field, value)
	pipe.Expire(ctx, key, ttl)
	_, err := pipe.Exec(ctx)
	return err
}

func (r *RedisClient) DeleteKey(ctx context.Context, key string) error {
	return r.client.Del(ctx, key).Err()
}

type Service struct {
	redis *RedisClient
}

func (s *Service) HandleRequest(ctx context.Context, userID string) string {
	val, _ := s.redis.HGetAsString(ctx, "users", userID)
	count, _ := s.redis.GetAsInt(ctx, "counter:"+userID)
	s.redis.HSetWithExpire(ctx, "session:"+userID, "count", count, 24*time.Hour)
	return val
}
```

### Step 2: Write tests

- [ ] **1.2: Create test file with 4A tests**

Create `graph_builder/tests/test_quick_fixes.py`:

```python
"""Tests for the quick-fixes bundle (4A-4H).

Run with: python -m pytest graph_builder/tests/test_quick_fixes.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from graph_builder.parsers.go_parser import parse_go_file
from graph_builder.resolvers.redis_abstraction_resolver import resolve_go_redis_abstractions

GO_FIXTURES = Path(__file__).parent / "fixtures" / "go"

# ───────────────────────────────────────────────────────────────
# 4A: Go Redis r.client pattern + wrapper methods
# ───────────────────────────────────────────────────────────────

def test_4a_r_client_internal_redis_detected():
    """r.client.HGet inside redis wrapper should produce Redis accesses."""
    ast = parse_go_file(str(GO_FIXTURES / "redis_wrapper.go"))
    all_asts = {"redis_wrapper.go": ast}
    resolve_go_redis_abstractions(all_asts)

    internal_ops = [a for a in ast.redis_accesses if "r.client" in a.key_name]
    assert len(internal_ops) >= 3, (
        f"Expected >=3 internal r.client Redis ops, got {len(internal_ops)}: "
        f"{[(a.operation, a.key_name) for a in internal_ops]}"
    )
    internal_op_names = {a.operation for a in internal_ops}
    assert "HGet" in internal_op_names
    assert "Get" in internal_op_names
    assert "Del" in internal_op_names


def test_4a_wrapper_methods_detected():
    """s.redis.HGetAsString wrapper calls should be detected as Redis ops."""
    ast = parse_go_file(str(GO_FIXTURES / "redis_wrapper.go"))
    all_asts = {"redis_wrapper.go": ast}
    resolve_go_redis_abstractions(all_asts)

    wrapper_ops = [a for a in ast.redis_accesses
                   if a.operation in ("HGetAsString", "GetAsInt", "HSetWithExpire")]
    assert len(wrapper_ops) >= 3, (
        f"Expected >=3 wrapper Redis ops, got {len(wrapper_ops)}: "
        f"{[(a.operation, a.access_type) for a in wrapper_ops]}"
    )


def test_4a_read_write_classification():
    """Read/write classification should be correct for all detected ops."""
    ast = parse_go_file(str(GO_FIXTURES / "redis_wrapper.go"))
    all_asts = {"redis_wrapper.go": ast}
    resolve_go_redis_abstractions(all_asts)

    ops = {a.operation: a.access_type for a in ast.redis_accesses}
    # Reads
    for read_op in ("HGet", "Get", "HGetAsString", "GetAsInt"):
        if read_op in ops:
            assert ops[read_op] == "read", f"{read_op} should be read, got {ops[read_op]}"
    # Writes
    for write_op in ("Del", "HSet", "Expire", "HSetWithExpire"):
        if write_op in ops:
            assert ops[write_op] == "write", f"{write_op} should be write, got {ops[write_op]}"
```

### Step 3: Run tests (expect failure)

- [ ] **1.3: Run tests, confirm they fail**

```bash
python -m pytest graph_builder/tests/test_quick_fixes.py::test_4a_r_client_internal_redis_detected -xvs
python -m pytest graph_builder/tests/test_quick_fixes.py::test_4a_wrapper_methods_detected -xvs
```

Both should fail: `r.client` is not matched by indicators, and `HGetAsString`/`GetAsInt`/`HSetWithExpire` are already in the method sets but `r.client` is not in indicators.

### Step 4: Implement the fix

- [ ] **1.4: Add `.client` suffix matching to `_GO_REDIS_INDICATORS` check**

In `graph_builder/resolvers/redis_abstraction_resolver.py`, modify the `resolve_go_redis_abstractions` function. At line 309, after the existing `is_redis` check, add a `.client` suffix check:

```python
# Current code (line 309-312):
            is_redis = any(ind in receiver for ind in _GO_REDIS_INDICATORS)
            if not is_redis:
                receiver_tail = receiver.rsplit(".", 1)[-1]
                is_redis = receiver_tail.lower() in {"redisclient", "redis", "rdb", "redisconn", "rclient"}

# Replace with:
            is_redis = any(ind in receiver for ind in _GO_REDIS_INDICATORS)
            if not is_redis:
                receiver_tail = receiver.rsplit(".", 1)[-1]
                is_redis = receiver_tail.lower() in {"redisclient", "redis", "rdb", "redisconn", "rclient", "client"}
```

This adds `"client"` to the tail-match set. The receiver `r.client` splits to tail `client`, which now matches. This is safe because `client` as a final segment in a Go method receiver is almost always a Redis/DB client in this codebase.

- [ ] **1.5: Wire `resolve_go_redis_abstractions` into `graph_health.py`**

In `graph_builder/validate/graph_health.py`, add the import at the top (around line 28):

```python
# Existing import:
from graph_builder.resolvers.redis_abstraction_resolver import resolve_redis_abstractions

# Add:
from graph_builder.resolvers.redis_abstraction_resolver import resolve_redis_abstractions, resolve_go_redis_abstractions
```

Then in `run_health_report()`, after line 179 (`resolve_redis_abstractions(all_asts)`), add:

```python
    resolve_redis_abstractions(all_asts)
    resolve_go_redis_abstractions(all_asts)  # 4A: Go Redis wrapper detection
```

### Step 5: Run tests (expect pass)

- [ ] **1.6: Run tests, confirm they pass**

```bash
python -m pytest graph_builder/tests/test_quick_fixes.py -k "test_4a" -xvs
```

### Step 6: Commit

- [ ] **1.7: Commit**

```bash
git add graph_builder/resolvers/redis_abstraction_resolver.py graph_builder/validate/graph_health.py graph_builder/tests/test_quick_fixes.py graph_builder/tests/fixtures/go/redis_wrapper.go
git commit -m "fix(4A): detect Go Redis r.client pattern and wire go_redis into health report"
```

---

## Task 2: Fix 4B — Python `self.method()` Resolution

Python `self.method()` calls never resolve because the existing self-handling in `CallResolver._resolve_call()` checks `ast.module_info.table_var_name` which is Lua-specific. Python ASTs have no `module_info`, so the self-check at line 202 (`if ast.module_info and table_name == ast.module_info.table_var_name`) always fails. The later `self` check at line 211-225 does match `table_name == "self"`, but only resolves if the file has a `module_info` with a `table_var_name` (Lua) or if it finds the method by bare name match. For Python, `self` calls should resolve to same-file methods by matching `func.name == method_name`.

**Files:**
- Modify: `graph_builder/resolvers/call_resolver.py`
- Create: `graph_builder/tests/fixtures/python/self_calls.py`
- Modify: `graph_builder/tests/test_quick_fixes.py`

### Step 1: Create test fixture

- [ ] **2.1: Create Python fixture with self.method() calls**

Create `graph_builder/tests/fixtures/python/self_calls.py`:

```python
"""Python class with self.method() calls for testing."""

import logging


class RecordProcessor:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.batch = []

    def process(self, record):
        validated = self._validate_record(record)
        if validated:
            self._add_to_batch(validated)
            if len(self.batch) >= self.config.batch_size:
                self._flush_batch()

    def _validate_record(self, record):
        if not record.get("id"):
            self.logger.warning("Missing ID")
            return None
        return record

    def _add_to_batch(self, record):
        self.batch.append(record)

    def _flush_batch(self):
        self._retry_failed(self.batch)
        self.batch = []

    def _retry_failed(self, items):
        for item in items:
            self.logger.debug("Retrying %s", item["id"])
```

### Step 2: Write tests

- [ ] **2.2: Add 4B tests to test_quick_fixes.py**

Append to `graph_builder/tests/test_quick_fixes.py`:

```python
from graph_builder.parsers.python_parser import parse_python_file
from graph_builder.resolvers.call_resolver import CallResolver

PY_FIXTURES = Path(__file__).parent / "fixtures" / "python"

# ───────────────────────────────────────────────────────────────
# 4B: Python self.method() resolution
# ───────────────────────────────────────────────────────────────

def test_4b_self_method_resolved():
    """self._validate_record() should resolve to the same-file function."""
    ast = parse_python_file(str(PY_FIXTURES / "self_calls.py"))
    all_asts = {str(PY_FIXTURES / "self_calls.py"): ast}
    resolver = CallResolver(all_asts, {})
    resolver.resolve_all()

    self_calls = [c for c in ast.calls
                  if c.callee_string.startswith("self.")
                  and c.resolved_module is not None]
    resolved_names = {c.resolved_function for c in self_calls}
    assert "_validate_record" in resolved_names, (
        f"self._validate_record not resolved. Resolved: {resolved_names}"
    )
    assert "_add_to_batch" in resolved_names, (
        f"self._add_to_batch not resolved. Resolved: {resolved_names}"
    )
    assert "_flush_batch" in resolved_names, (
        f"self._flush_batch not resolved. Resolved: {resolved_names}"
    )


def test_4b_self_attribute_chain_not_resolved():
    """self.logger.warning() should NOT be resolved (attribute chain, not method)."""
    ast = parse_python_file(str(PY_FIXTURES / "self_calls.py"))
    all_asts = {str(PY_FIXTURES / "self_calls.py"): ast}
    resolver = CallResolver(all_asts, {})
    resolver.resolve_all()

    # self.logger.warning → callee_string is "self.logger.warning"
    # The first "." split gives table_name="self", method_name="logger.warning"
    # "logger.warning" won't match any function name, so it should NOT resolve
    # via the self-python path
    logger_calls = [c for c in ast.calls
                    if "logger" in c.callee_string
                    and c.resolution_confidence == "self_python"]
    assert len(logger_calls) == 0, (
        f"self.logger.X calls should not resolve as self_python: {logger_calls}"
    )


def test_4b_self_resolution_confidence():
    """Self-resolved calls should have confidence 'self_python'."""
    ast = parse_python_file(str(PY_FIXTURES / "self_calls.py"))
    all_asts = {str(PY_FIXTURES / "self_calls.py"): ast}
    resolver = CallResolver(all_asts, {})
    resolver.resolve_all()

    self_resolved = [c for c in ast.calls
                     if c.resolution_confidence == "self_python"]
    assert len(self_resolved) >= 3, (
        f"Expected >=3 self_python resolutions, got {len(self_resolved)}"
    )
```

### Step 3: Run tests (expect failure)

- [ ] **2.3: Run tests, confirm they fail**

```bash
python -m pytest graph_builder/tests/test_quick_fixes.py -k "test_4b" -xvs
```

### Step 4: Implement the fix

- [ ] **2.4: Add Python self-handling to `CallResolver._resolve_call()`**

In `graph_builder/resolvers/call_resolver.py`, inside `_resolve_call()`, find the existing self-handling block (around line 211-225, the `if table_name == "self":` block). Add a Python-specific branch BEFORE the existing Lua self-handling. Insert after line 207 (after `return True` for `ast.module_info.table_var_name`):

```python
                # Check if it's a self-call on the module table
                if ast.module_info and table_name == ast.module_info.table_var_name:
                    call.resolved_module = ast.module_name or ast.file_path
                    call.resolved_function = method_name
                    call.resolution_confidence = "self"
                    return True

                # Python self.method() resolution
                if table_name == "self" and ast.language == "python":
                    for func in ast.functions:
                        if func.name == method_name:
                            call.resolved_module = ast.module_name or ast.file_path
                            call.resolved_function = method_name
                            call.resolution_confidence = "self_python"
                            return True
                    # self.attr.method() chains — don't try to resolve
                    # Fall through to other strategies

                # self:method() resolution — in Lua, `self` inside a method
```

The key insight: Python `FunctionDef.name` stores bare names (e.g., `_validate_record`), not `ClassName._validate_record`, so a bare name match works. For `self.logger.warning`, the first `.` split gives `method_name="logger.warning"`, which won't match any bare function name, so it correctly falls through.

### Step 5: Run tests (expect pass)

- [ ] **2.5: Run tests, confirm they pass**

```bash
python -m pytest graph_builder/tests/test_quick_fixes.py -k "test_4b" -xvs
```

### Step 6: Commit

- [ ] **2.6: Commit**

```bash
git add graph_builder/resolvers/call_resolver.py graph_builder/tests/test_quick_fixes.py graph_builder/tests/fixtures/python/self_calls.py
git commit -m "fix(4B): resolve Python self.method() calls to same-file functions"
```

---

## Task 3: Fix 4C — Python RedisCluster Factory

Python Redis detection finds 0 because `RedisCluster` is not in the `redis_factories` set and `self.connection = RedisCluster(...)` is not handled (LHS type is `attribute`, not `identifier`).

**Files:**
- Modify: `graph_builder/parsers/python_parser.py`
- Create: `graph_builder/tests/fixtures/python/redis_cluster_service.py`
- Modify: `graph_builder/tests/test_quick_fixes.py`

### Step 1: Create test fixture

- [ ] **3.1: Create Python fixture with RedisCluster usage**

Create `graph_builder/tests/fixtures/python/redis_cluster_service.py`:

```python
"""Python service using RedisCluster."""

try:
    from redis.cluster import RedisCluster
except ImportError:
    from rediscluster import RedisCluster


class GeoService:
    def __init__(self, config):
        self.connection = RedisCluster(
            startup_nodes=config["redis_nodes"],
            decode_responses=True,
        )

    def lookup(self, ip_address):
        cached = self.connection.hget("geo:cache", ip_address)
        if cached:
            return cached
        result = self._resolve_ip(ip_address)
        self.connection.hset("geo:cache", ip_address, result)
        return result

    def _resolve_ip(self, ip):
        return "US"
```

### Step 2: Write tests

- [ ] **3.2: Add 4C tests to test_quick_fixes.py**

Append to `graph_builder/tests/test_quick_fixes.py`:

```python
# ───────────────────────────────────────────────────────────────
# 4C: Python RedisCluster factory
# ───────────────────────────────────────────────────────────────

def test_4c_redis_cluster_detected():
    """RedisCluster with self.connection should detect Redis ops."""
    ast = parse_python_file(str(PY_FIXTURES / "redis_cluster_service.py"))
    assert len(ast.redis_accesses) >= 2, (
        f"Expected >=2 Redis accesses, got {len(ast.redis_accesses)}: "
        f"{[(a.operation, a.access_type) for a in ast.redis_accesses]}"
    )


def test_4c_redis_cluster_read_write():
    """hget should be read, hset should be write."""
    ast = parse_python_file(str(PY_FIXTURES / "redis_cluster_service.py"))
    ops = {a.operation: a.access_type for a in ast.redis_accesses}
    assert ops.get("hget") == "read", f"hget should be read, got {ops.get('hget')}"
    assert ops.get("hset") == "write", f"hset should be write, got {ops.get('hset')}"


def test_4c_redis_cluster_import_detected():
    """RedisCluster should be registered via try/except import."""
    ast = parse_python_file(str(PY_FIXTURES / "redis_cluster_service.py"))
    import_modules = [imp.module_string for imp in ast.imports]
    assert any("redis" in m for m in import_modules), (
        f"Expected redis import, got: {import_modules}"
    )
```

### Step 3: Run tests (expect failure)

- [ ] **3.3: Run tests, confirm they fail**

```bash
python -m pytest graph_builder/tests/test_quick_fixes.py -k "test_4c" -xvs
```

### Step 4: Implement the fix

- [ ] **3.4: Add `RedisCluster` and `StrictRedisCluster` to factories**

In `graph_builder/parsers/python_parser.py`, at line 312, change:

```python
    redis_factories = {"Redis", "StrictRedis", "from_url"}
```

to:

```python
    redis_factories = {"Redis", "StrictRedis", "from_url", "RedisCluster", "StrictRedisCluster"}
```

- [ ] **3.5: Handle `self.connection = RedisCluster(...)` attribute assignment**

In `graph_builder/parsers/python_parser.py`, in `_extract_redis_accesses_python()`, after the existing assignment detection block (lines 313-325), add handling for attribute LHS:

```python
    # Existing block handles: redis_client = redis.Redis(...)
    # where left.type == "identifier"

    # Also handle: self.connection = RedisCluster(...)
    # where left.type == "attribute" and right is a call to a redis factory
    for node in _walk_all(root, "assignment"):
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if not (left and right and right.type == "call"):
            continue

        func = right.child_by_field_name("function")
        if not func:
            continue

        # Direct factory call: self.connection = RedisCluster(...)
        func_text = _text(func, source)
        if func_text in redis_factories or func_text.split(".")[-1] in redis_factories:
            if left.type == "attribute":
                # Extract the full attribute text (e.g., "self.connection")
                redis_vars.add(_text(left, source))
            elif left.type == "identifier":
                redis_vars.add(_text(left, source))
```

Wait -- the existing code already handles `redis_client = redis.Redis(...)` via the `obj in redis_vars and attr in redis_factories` pattern (lines 318-325). We need to also handle the case where the factory is called directly (not as `redis_module.RedisCluster` but just `RedisCluster` from a `from ... import RedisCluster`).

The actual fix requires two changes to the assignment detection loop. Replace the existing assignment detection block (lines 313-325) with an expanded version. Find this code:

```python
    redis_factories = {"Redis", "StrictRedis", "from_url"}
    for node in _walk_all(root, "assignment"):
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if not (left and right and right.type == "call"):
            continue
        func = right.child_by_field_name("function")
        if not func or func.type != "attribute":
            continue
        obj = func.child_by_field_name("object")
        attr = func.child_by_field_name("attribute")
        if obj and attr and _text(obj, source) in redis_vars and _text(attr, source) in redis_factories:
            if left.type == "identifier":
                redis_vars.add(_text(left, source))
```

Replace with:

```python
    redis_factories = {"Redis", "StrictRedis", "from_url", "RedisCluster", "StrictRedisCluster"}
    for node in _walk_all(root, "assignment"):
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        if not (left and right and right.type == "call"):
            continue
        func = right.child_by_field_name("function")
        if not func:
            continue

        is_redis_factory = False

        if func.type == "attribute":
            # Pattern: redis.Redis(...), redis.StrictRedis(...)
            obj = func.child_by_field_name("object")
            attr = func.child_by_field_name("attribute")
            if obj and attr and _text(obj, source) in redis_vars and _text(attr, source) in redis_factories:
                is_redis_factory = True
        elif func.type == "identifier":
            # Pattern: RedisCluster(...) — direct call after from-import
            if _text(func, source) in redis_factories:
                is_redis_factory = True

        if is_redis_factory:
            if left.type == "identifier":
                redis_vars.add(_text(left, source))
            elif left.type == "attribute":
                # Pattern: self.connection = RedisCluster(...)
                redis_vars.add(_text(left, source))
```

### Step 5: Run tests (expect pass)

- [ ] **3.6: Run tests, confirm they pass**

```bash
python -m pytest graph_builder/tests/test_quick_fixes.py -k "test_4c" -xvs
```

### Step 6: Commit

- [ ] **3.7: Commit**

```bash
git add graph_builder/parsers/python_parser.py graph_builder/tests/test_quick_fixes.py graph_builder/tests/fixtures/python/redis_cluster_service.py
git commit -m "fix(4C): detect Python RedisCluster factory and self.attr Redis assignments"
```

---

## Task 4: Fix 4D — Ruby Preprocessor Loading Model

63 preprocessor files are loaded via `Dir.glob` + `require`, and 2 task files via `class_eval(IO.read(entry))`. Neither uses standard `require`, so all appear as orphans.

**Files:**
- Modify: `graph_builder/resolvers/ruby_resolver.py`
- Modify: `graph_builder/ingestion/writer.py`
- Create: `graph_builder/tests/fixtures/ruby/preprocessor_loader.rb`
- Create: `graph_builder/tests/fixtures/ruby/preprocess/strip_whitespace.rb`
- Create: `graph_builder/tests/fixtures/ruby/preprocess/normalize.rb`
- Modify: `graph_builder/tests/test_quick_fixes.py`

### Step 1: Create test fixtures

- [ ] **4.1: Create Ruby preprocessor loader fixture and preprocess directory**

Create `graph_builder/tests/fixtures/ruby/preprocessor_loader.rb`:

```ruby
class Preprocessor
  def initialize(config)
    @config = config
    @preprocessors = []
  end

  def scan_for_preprocess(base_path)
    Dir.glob(File.join(base_path, "preprocess", "*.rb")).each do |file|
      require file
    end
  end

  def load_tasks
    entries = Dir.entries(File.join(@config["base_path"], "tasks"))
    entries.each do |entry|
      next unless entry.end_with?(".rb")
      klass = Class.new
      klass.class_eval(IO.read(entry))
    end
  end
end
```

Create `graph_builder/tests/fixtures/ruby/preprocess/strip_whitespace.rb`:

```ruby
class StripWhitespace
  def process(data)
    data.strip
  end
end
```

Create `graph_builder/tests/fixtures/ruby/preprocess/normalize.rb`:

```ruby
class Normalize
  def process(data)
    data.downcase
  end
end
```

### Step 2: Write tests

- [ ] **4.2: Add 4D tests to test_quick_fixes.py**

Append to `graph_builder/tests/test_quick_fixes.py`:

```python
from graph_builder.parsers.ruby_parser import parse_ruby_file
from graph_builder.resolvers.ruby_resolver import RubyResolver

RB_FIXTURES = Path(__file__).parent / "fixtures" / "ruby"

# ───────────────────────────────────────────────────────────────
# 4D: Ruby preprocessor loading model
# ───────────────────────────────────────────────────────────────

def test_4d_dir_glob_loading_detected():
    """Dir.glob in preprocessor_loader.rb should produce LOADS_DYNAMICALLY targets."""
    ast = parse_ruby_file(str(RB_FIXTURES / "preprocessor_loader.rb"))
    all_asts = {str(RB_FIXTURES / "preprocessor_loader.rb"): ast}
    resolver = RubyResolver(str(RB_FIXTURES))

    edges = resolver.resolve_dynamic_loading(all_asts)
    # Should find strip_whitespace.rb and normalize.rb in preprocess/
    target_names = {Path(e["target"]).name for e in edges}
    assert "strip_whitespace.rb" in target_names, (
        f"strip_whitespace.rb not in loading targets: {target_names}"
    )
    assert "normalize.rb" in target_names, (
        f"normalize.rb not in loading targets: {target_names}"
    )


def test_4d_class_eval_loading_detected():
    """class_eval(IO.read(...)) should be detected as dynamic loading."""
    ast = parse_ruby_file(str(RB_FIXTURES / "preprocessor_loader.rb"))
    # Verify that the AST contains a call matching class_eval pattern
    class_eval_calls = [c for c in ast.calls if "class_eval" in c.callee_string]
    assert len(class_eval_calls) >= 1, (
        f"Expected class_eval call, got: {[c.callee_string for c in ast.calls]}"
    )


def test_4d_loading_edges_have_correct_structure():
    """Loading edges should have source, target, and load_type keys."""
    ast = parse_ruby_file(str(RB_FIXTURES / "preprocessor_loader.rb"))
    all_asts = {str(RB_FIXTURES / "preprocessor_loader.rb"): ast}
    resolver = RubyResolver(str(RB_FIXTURES))

    edges = resolver.resolve_dynamic_loading(all_asts)
    for edge in edges:
        assert "source" in edge, f"Edge missing 'source': {edge}"
        assert "target" in edge, f"Edge missing 'target': {edge}"
        assert "load_type" in edge, f"Edge missing 'load_type': {edge}"
        assert edge["load_type"] in ("dir_glob", "class_eval"), (
            f"Unexpected load_type: {edge['load_type']}"
        )
```

### Step 3: Run tests (expect failure)

- [ ] **4.3: Run tests, confirm they fail**

```bash
python -m pytest graph_builder/tests/test_quick_fixes.py -k "test_4d" -xvs
```

### Step 4: Implement the fix

- [ ] **4.4: Add `resolve_dynamic_loading` method to `RubyResolver`**

In `graph_builder/resolvers/ruby_resolver.py`, add a new method to the `RubyResolver` class (after `stats()`):

```python
    def resolve_dynamic_loading(self, all_asts: dict) -> list[dict]:
        """Detect Dir.glob/Dir.entries/class_eval loading patterns and return edges.

        Returns a list of dicts: {"source": file_path, "target": file_path, "load_type": str}
        """
        from graph_builder.parsers.base import FileAST
        edges: list[dict] = []

        for file_path, ast in all_asts.items():
            if ast.language != "ruby":
                continue

            has_dir_glob = False
            has_class_eval = False

            for call in ast.calls:
                callee = call.callee_string.lower()
                # Dir.glob, Dir.entries, Dir["pattern"]
                if "dir.glob" in callee or "dir.entries" in callee:
                    has_dir_glob = True
                # scan_for_* method definitions containing Dir.glob
                if "scan_for_" in callee:
                    has_dir_glob = True
                # class_eval(IO.read(...))
                if "class_eval" in callee:
                    has_class_eval = True

            if has_dir_glob:
                # Find all .rb files in subdirectories relative to this file
                source_dir = Path(file_path).parent
                for rb_file in source_dir.rglob("*.rb"):
                    rb_str = str(rb_file)
                    if rb_str == file_path:
                        continue
                    edges.append({
                        "source": file_path,
                        "target": rb_str,
                        "load_type": "dir_glob",
                    })

            if has_class_eval:
                # class_eval(IO.read(entry)) — loading .rb files dynamically
                # Mark as dynamic loader; specific targets resolved at integration time
                edges.append({
                    "source": file_path,
                    "target": file_path,  # self-reference as marker
                    "load_type": "class_eval",
                })

        return edges
```

Also add the `Path` import at the top of ruby_resolver.py if not already present (it already is: `from pathlib import Path`).

- [ ] **4.5: Add `upsert_dynamic_load` method to `GraphWriter`**

In `graph_builder/ingestion/writer.py`, add a new method after `upsert_potential_import`:

```python
    def upsert_dynamic_load(self, source_file: str, target_file: str,
                            load_type: str):
        """Create a LOADS_DYNAMICALLY edge from source to target file."""
        self._run("""
            MERGE (src:File {path: $source})
            MERGE (tgt:File {path: $target})
            MERGE (src)-[:LOADS_DYNAMICALLY {load_type: $load_type}]->(tgt)
        """, source=source_file, target=target_file, load_type=load_type)
```

### Step 5: Run tests (expect pass)

- [ ] **4.6: Run tests, confirm they pass**

```bash
python -m pytest graph_builder/tests/test_quick_fixes.py -k "test_4d" -xvs
```

### Step 6: Commit

- [ ] **4.7: Commit**

```bash
git add graph_builder/resolvers/ruby_resolver.py graph_builder/ingestion/writer.py graph_builder/tests/test_quick_fixes.py graph_builder/tests/fixtures/ruby/preprocessor_loader.rb graph_builder/tests/fixtures/ruby/preprocess/strip_whitespace.rb graph_builder/tests/fixtures/ruby/preprocess/normalize.rb
git commit -m "fix(4D): detect Ruby Dir.glob and class_eval dynamic loading patterns"
```

---

## Task 5: Fix 4E — Ruby `module_name` and Health Metric Fix

Two bugs: (1) Health report's `funcs_with_outgoing_calls` is 0 for Ruby because `_find_enclosing` returns `ClassName#method` but `FunctionDef.name` stores bare `method` -- the set intersection always fails. (2) Ruby `FileAST.module_name` is never set, making Ruby files invisible to the global symbol table.

**Files:**
- Modify: `graph_builder/parsers/ruby_parser.py`
- Modify: `graph_builder/validate/graph_health.py`
- Create: `graph_builder/tests/fixtures/ruby/class_with_calls.rb`
- Modify: `graph_builder/tests/test_quick_fixes.py`

### Step 1: Create test fixture

- [ ] **5.1: Create Ruby fixture with class methods making calls**

Create `graph_builder/tests/fixtures/ruby/class_with_calls.rb`:

```ruby
class DataProcessor
  def process(record)
    validated = validate(record)
    transform(validated) if validated
  end

  def validate(record)
    return nil unless record.key?(:id)
    record
  end

  def transform(record)
    record[:name] = record[:name].downcase
    record
  end
end
```

### Step 2: Write tests

- [ ] **5.2: Add 4E tests to test_quick_fixes.py**

Append to `graph_builder/tests/test_quick_fixes.py`:

```python
# ───────────────────────────────────────────────────────────────
# 4E: Ruby module_name + health metric fix
# ───────────────────────────────────────────────────────────────

def test_4e_ruby_module_name_set():
    """Ruby FileAST should have module_name set from the primary class."""
    ast = parse_ruby_file(str(RB_FIXTURES / "class_with_calls.rb"))
    assert ast.module_name is not None, "Ruby FileAST.module_name should be set"
    assert ast.module_name == "DataProcessor", (
        f"Expected module_name='DataProcessor', got '{ast.module_name}'"
    )


def test_4e_ruby_health_metric_caller_matching():
    """Health metric should match callers to functions for Ruby."""
    ast = parse_ruby_file(str(RB_FIXTURES / "class_with_calls.rb"))

    # Simulate what graph_health.py does: collect caller_function names
    # and intersect with function names
    callers_with_calls = {call.caller_function for call in ast.calls}
    all_func_names = {f.name for f in ast.functions}

    # The bug: callers_with_calls has "DataProcessor#process" but
    # all_func_names has "process". They don't intersect.
    # After fix: we normalize caller names by stripping class prefix.
    normalized_callers = set()
    for caller in callers_with_calls:
        if "#" in caller:
            normalized_callers.add(caller.split("#")[-1])
        else:
            normalized_callers.add(caller)

    funcs_that_call = normalized_callers & all_func_names
    assert len(funcs_that_call) >= 1, (
        f"Expected >=1 functions with outgoing calls. "
        f"Callers: {callers_with_calls}, Functions: {all_func_names}, "
        f"Normalized: {normalized_callers}"
    )


def test_4e_ruby_module_name_from_module():
    """Ruby file with top-level module should use module name."""
    ast = parse_ruby_file(str(RB_FIXTURES / "nested_modules.rb"))
    assert ast.module_name is not None, "Module-based file should have module_name"
```

### Step 3: Run tests (expect failure)

- [ ] **5.3: Run tests, confirm they fail**

```bash
python -m pytest graph_builder/tests/test_quick_fixes.py -k "test_4e" -xvs
```

### Step 4: Implement the fix

- [ ] **5.4: Set `module_name` on Ruby FileAST after parsing**

In `graph_builder/parsers/ruby_parser.py`, in `parse_ruby_file()`, before the `return ast` statement (line 354), add:

```python
    # --- Set module_name from primary class or module ---
    # Use the first class name, or first top-level module name, or derive from path
    if ast.classes:
        ast.module_name = ast.classes[0].name
    elif ast.exports:
        # Use first exported module/class constant
        for exp in ast.exports:
            if exp[0].isupper() and "::" not in exp:
                ast.module_name = exp
                break
    if not ast.module_name:
        # Fallback: derive from file path
        rel = Path(file_path).stem
        ast.module_name = rel

    return ast
```

- [ ] **5.5: Fix health metric caller matching for Ruby**

In `graph_builder/validate/graph_health.py`, find the block (around lines 268-272) that computes `funcs_with_outgoing_calls`:

```python
        # Connectivity: functions with outgoing calls vs orphans
        all_func_names = {f.name for f in ast.functions}
        funcs_that_call = callers_with_calls & all_func_names
        d["funcs_with_outgoing_calls"] += len(funcs_that_call)
        d["orphan_functions"] += len(all_func_names - callers_with_calls)
```

Replace with:

```python
        # Connectivity: functions with outgoing calls vs orphans
        all_func_names = {f.name for f in ast.functions}
        # Normalize caller names: Ruby uses "ClassName#method" but
        # FunctionDef.name stores bare "method". Strip class prefix.
        normalized_callers = set()
        for caller in callers_with_calls:
            if "#" in caller:
                normalized_callers.add(caller.split("#")[-1])
            else:
                normalized_callers.add(caller)
        funcs_that_call = normalized_callers & all_func_names
        d["funcs_with_outgoing_calls"] += len(funcs_that_call)
        d["orphan_functions"] += len(all_func_names - normalized_callers)
```

### Step 5: Run tests (expect pass)

- [ ] **5.6: Run tests, confirm they pass**

```bash
python -m pytest graph_builder/tests/test_quick_fixes.py -k "test_4e" -xvs
```

### Step 6: Commit

- [ ] **5.7: Commit**

```bash
git add graph_builder/parsers/ruby_parser.py graph_builder/validate/graph_health.py graph_builder/tests/test_quick_fixes.py graph_builder/tests/fixtures/ruby/class_with_calls.rb
git commit -m "fix(4E): set Ruby module_name and fix health metric caller matching"
```

---

## Task 6: Fix 4F — Go Interface `IMPLEMENTS` Edges

Go has 7 interfaces but no `IMPLEMENTS` edges. After Go parsing, we can compare interface method sets against struct method sets to detect structural implementation. Requires adding `is_interface: bool` to `ClassDef` and setting it in the Go parser.

**Files:**
- Modify: `graph_builder/parsers/base.py`
- Modify: `graph_builder/parsers/go_parser.py`
- Modify: `graph_builder/resolvers/go_resolver.py`
- Modify: `graph_builder/ingestion/writer.py`
- Create: `graph_builder/tests/fixtures/go/interfaces.go`
- Modify: `graph_builder/tests/test_quick_fixes.py`

### Step 1: Create test fixture

- [ ] **6.1: Create Go fixture with interfaces and implementing structs**

Create `graph_builder/tests/fixtures/go/interfaces.go`:

```go
package service

type Task interface {
	Process() error
	Close() error
}

type TasksReader interface {
	ReadTasks() ([]Task, error)
}

type EmptyConfig interface{}

type ModelPredictionTask struct {
	modelName string
}

func (m *ModelPredictionTask) Process() error {
	return nil
}

func (m *ModelPredictionTask) Close() error {
	return nil
}

func (m *ModelPredictionTask) Init() error {
	return nil
}

type GeneralTasksReader struct {
	configPath string
}

func (g *GeneralTasksReader) ReadTasks() ([]Task, error) {
	return nil, nil
}

func (g *GeneralTasksReader) Validate() error {
	return nil
}
```

### Step 2: Write tests

- [ ] **6.2: Add 4F tests to test_quick_fixes.py**

Append to `graph_builder/tests/test_quick_fixes.py`:

```python
from graph_builder.resolvers.go_resolver import GoResolver, resolve_go_interfaces

# ───────────────────────────────────────────────────────────────
# 4F: Go interface IMPLEMENTS edges
# ───────────────────────────────────────────────────────────────

def test_4f_interface_flag_set():
    """Go parser should set is_interface=True for interface type_spec nodes."""
    ast = parse_go_file(str(GO_FIXTURES / "interfaces.go"))
    interfaces = [c for c in ast.classes if c.is_interface]
    structs = [c for c in ast.classes if not c.is_interface]

    interface_names = {c.name for c in interfaces}
    struct_names = {c.name for c in structs}

    assert "Task" in interface_names, f"Task should be an interface: {interface_names}"
    assert "TasksReader" in interface_names
    assert "ModelPredictionTask" in struct_names
    assert "GeneralTasksReader" in struct_names


def test_4f_implements_edges_detected():
    """Struct implementing all interface methods should produce IMPLEMENTS edge."""
    ast = parse_go_file(str(GO_FIXTURES / "interfaces.go"))
    all_asts = {str(GO_FIXTURES / "interfaces.go"): ast}
    implements = resolve_go_interfaces(all_asts)

    impl_pairs = {(s, i) for s, i in implements}
    assert ("ModelPredictionTask", "Task") in impl_pairs, (
        f"ModelPredictionTask should implement Task. Got: {impl_pairs}"
    )
    assert ("GeneralTasksReader", "TasksReader") in impl_pairs, (
        f"GeneralTasksReader should implement TasksReader. Got: {impl_pairs}"
    )


def test_4f_empty_interface_skipped():
    """Empty interfaces (like Config) should not generate IMPLEMENTS edges."""
    ast = parse_go_file(str(GO_FIXTURES / "interfaces.go"))
    all_asts = {str(GO_FIXTURES / "interfaces.go"): ast}
    implements = resolve_go_interfaces(all_asts)

    # EmptyConfig has no methods, should not match anything
    empty_impls = [(s, i) for s, i in implements if i == "EmptyConfig"]
    assert len(empty_impls) == 0, (
        f"EmptyConfig should not have implementors: {empty_impls}"
    )


def test_4f_partial_match_excluded():
    """Struct with only some interface methods should NOT produce an edge."""
    ast = parse_go_file(str(GO_FIXTURES / "interfaces.go"))
    all_asts = {str(GO_FIXTURES / "interfaces.go"): ast}
    implements = resolve_go_interfaces(all_asts)

    # GeneralTasksReader has ReadTasks + Validate, but NOT Process/Close
    # So it should NOT implement Task
    bad_pairs = [(s, i) for s, i in implements
                 if s == "GeneralTasksReader" and i == "Task"]
    assert len(bad_pairs) == 0, (
        f"GeneralTasksReader should NOT implement Task: {bad_pairs}"
    )
```

### Step 3: Run tests (expect failure)

- [ ] **6.3: Run tests, confirm they fail**

```bash
python -m pytest graph_builder/tests/test_quick_fixes.py -k "test_4f" -xvs
```

### Step 4: Implement the fix

- [ ] **6.4: Add `is_interface` field to `ClassDef`**

In `graph_builder/parsers/base.py`, modify `ClassDef` (line 120-129). Add the field after `qualified_name`:

```python
@dataclass
class ClassDef:
    """A class definition."""
    name: str
    line: int
    line_end: int
    parent_class: str | None = None   # superclass name
    mixins: list[str] = field(default_factory=list)  # Ruby include/extend
    methods: list[str] = field(default_factory=list)  # method names defined in this class
    qualified_name: str | None = None  # fully-qualified name (e.g., "module::ClassName")
    is_interface: bool = False  # Go: interface vs struct
```

- [ ] **6.5: Set `is_interface=True` for Go interfaces**

In `graph_builder/parsers/go_parser.py`, in the struct/interface detection block (around line 153-170), when creating `ClassDef`, set `is_interface`:

Find:
```python
            if type_body.type in ("struct_type", "interface_type"):
                methods = []
                # For interfaces, collect method signatures
                if type_body.type == "interface_type":
                    for child in type_body.named_children:
                        if child.type == "method_spec":
                            mn = child.child_by_field_name("name")
                            if mn:
                                methods.append(_text(mn, source))

                type_qn = f"{ast.module_name}.{type_name}" if ast.module_name else type_name
                ast.classes.append(ClassDef(
                    name=type_name,
                    line=type_spec.start_point[0] + 1,
                    line_end=type_spec.end_point[0] + 1,
                    methods=methods,
                    qualified_name=type_qn,
                ))
```

Replace with:
```python
            if type_body.type in ("struct_type", "interface_type"):
                methods = []
                is_iface = type_body.type == "interface_type"
                # For interfaces, collect method signatures
                if is_iface:
                    for child in type_body.named_children:
                        if child.type == "method_spec":
                            mn = child.child_by_field_name("name")
                            if mn:
                                methods.append(_text(mn, source))

                type_qn = f"{ast.module_name}.{type_name}" if ast.module_name else type_name
                ast.classes.append(ClassDef(
                    name=type_name,
                    line=type_spec.start_point[0] + 1,
                    line_end=type_spec.end_point[0] + 1,
                    methods=methods,
                    qualified_name=type_qn,
                    is_interface=is_iface,
                ))
```

- [ ] **6.6: Add `resolve_go_interfaces` function to `go_resolver.py`**

In `graph_builder/resolvers/go_resolver.py`, add at the end of the file:

```python
def resolve_go_interfaces(all_asts: dict) -> list[tuple[str, str]]:
    """Match Go structs to interfaces using structural typing.

    Compares interface method sets against struct method sets.
    A struct implements an interface if the interface's method set
    is a subset of the struct's method set.

    Args:
        all_asts: file_path -> FileAST mapping

    Returns:
        List of (struct_name, interface_name) tuples.
    """
    interfaces: dict[str, set[str]] = {}   # name -> method names
    structs: dict[str, set[str]] = {}       # name -> method names

    for file_path, ast in all_asts.items():
        if ast.language != "go":
            continue
        for cls in ast.classes:
            if cls.is_interface:
                interfaces[cls.name] = set(cls.methods)
            else:
                structs[cls.name] = set(cls.methods)

    implements: list[tuple[str, str]] = []
    for iface_name, iface_methods in interfaces.items():
        if not iface_methods:
            continue  # Skip empty interfaces
        for struct_name, struct_methods in structs.items():
            if iface_methods.issubset(struct_methods):
                implements.append((struct_name, iface_name))

    return implements
```

- [ ] **6.7: Add `upsert_implements` method to `GraphWriter`**

In `graph_builder/ingestion/writer.py`, add a new method after `upsert_dynamic_load`:

```python
    def upsert_implements(self, struct_name: str, interface_name: str,
                          struct_file: str):
        """Create an IMPLEMENTS edge from a struct to an interface."""
        self._run("""
            MERGE (s:Class {name: $struct_name, file: $struct_file})
            MERGE (i:Class {name: $iface_name})
            MERGE (s)-[:IMPLEMENTS]->(i)
        """, struct_name=struct_name, iface_name=interface_name,
             struct_file=struct_file)
```

### Step 5: Run tests (expect pass)

- [ ] **6.8: Run tests, confirm they pass**

```bash
python -m pytest graph_builder/tests/test_quick_fixes.py -k "test_4f" -xvs
```

### Step 6: Commit

- [ ] **6.9: Commit**

```bash
git add graph_builder/parsers/base.py graph_builder/parsers/go_parser.py graph_builder/resolvers/go_resolver.py graph_builder/ingestion/writer.py graph_builder/tests/test_quick_fixes.py graph_builder/tests/fixtures/go/interfaces.go
git commit -m "fix(4F): add Go interface IMPLEMENTS edge detection via structural typing"
```

---

## Task 7: Fix 4G — Ruby Redis Detection

5 Ruby files use Redis but zero detection exists. Need to detect `Redis.new(...)`, `@redis` instance variable tracking, and Redis operation method calls.

**Files:**
- Modify: `graph_builder/parsers/ruby_parser.py`
- Create: `graph_builder/tests/fixtures/ruby/redis_helper.rb`
- Modify: `graph_builder/tests/test_quick_fixes.py`

### Step 1: Create test fixture

- [ ] **7.1: Create Ruby fixture with Redis usage**

Create `graph_builder/tests/fixtures/ruby/redis_helper.rb`:

```ruby
require "redis"

class RedisHelper
  def initialize(config)
    @redis = Redis.new(config)
  end

  def get(key)
    @redis.get(key)
  end

  def set(key, value)
    @redis.set(key, value)
  end

  def get_json(key)
    result = @redis.get(key)
    JSON.parse(result) if result
  end

  def hget(key, sub_key)
    @redis.hget(key, sub_key)
  end

  def eval_script(script, keys, values)
    @redis.eval(script, keys, values)
  end
end
```

### Step 2: Write tests

- [ ] **7.2: Add 4G tests to test_quick_fixes.py**

Append to `graph_builder/tests/test_quick_fixes.py`:

```python
from graph_builder.parsers.base import RedisKeyAccess

# ───────────────────────────────────────────────────────────────
# 4G: Ruby Redis detection
# ───────────────────────────────────────────────────────────────

def test_4g_ruby_redis_detected():
    """Ruby file with @redis = Redis.new should detect Redis operations."""
    ast = parse_ruby_file(str(RB_FIXTURES / "redis_helper.rb"))
    assert len(ast.redis_accesses) >= 4, (
        f"Expected >=4 Redis accesses, got {len(ast.redis_accesses)}: "
        f"{[(a.operation, a.access_type) for a in ast.redis_accesses]}"
    )


def test_4g_ruby_redis_read_write():
    """get/hget should be read, set should be write."""
    ast = parse_ruby_file(str(RB_FIXTURES / "redis_helper.rb"))
    ops = {}
    for a in ast.redis_accesses:
        ops[a.operation] = a.access_type
    assert ops.get("get") == "read", f"get should be read, got {ops.get('get')}"
    assert ops.get("hget") == "read", f"hget should be read, got {ops.get('hget')}"
    assert ops.get("set") == "write", f"set should be write, got {ops.get('set')}"


def test_4g_ruby_redis_eval_is_write():
    """eval (Lua script execution) should be classified as write."""
    ast = parse_ruby_file(str(RB_FIXTURES / "redis_helper.rb"))
    eval_ops = [a for a in ast.redis_accesses if a.operation == "eval"]
    assert len(eval_ops) >= 1, "eval should be detected"
    assert eval_ops[0].access_type == "write", "eval should be classified as write"


def test_4g_ruby_redis_import_detected():
    """require 'redis' should appear in imports."""
    ast = parse_ruby_file(str(RB_FIXTURES / "redis_helper.rb"))
    redis_imports = [imp for imp in ast.imports if imp.module_string == "redis"]
    assert len(redis_imports) >= 1, "require 'redis' should be detected"
```

### Step 3: Run tests (expect failure)

- [ ] **7.3: Run tests, confirm they fail**

```bash
python -m pytest graph_builder/tests/test_quick_fixes.py -k "test_4g" -xvs
```

### Step 4: Implement the fix

- [ ] **7.4: Add Ruby Redis detection to `ruby_parser.py`**

In `graph_builder/parsers/ruby_parser.py`, first add `RedisKeyAccess` to the imports at the top (line 19):

```python
from .base import FileAST, FunctionDef, ImportRef, CallRef, ClassDef, RedisKeyAccess
```

Then add the Redis detection function before the `_extract_ruby_params` function (before line 357):

```python
# --- Ruby Redis detection ---

_RUBY_REDIS_READ_OPS = {"get", "hget", "hgetall", "hmget", "mget", "exists",
                         "keys", "ttl", "type", "lrange", "smembers",
                         "sismember", "zrange", "zrangebyscore", "llen",
                         "scard", "zcard", "get_json"}
_RUBY_REDIS_WRITE_OPS = {"set", "hset", "hmset", "del", "delete", "expire",
                          "lpush", "rpush", "sadd", "srem", "zadd", "zrem",
                          "incr", "decr", "incrby", "decrby", "setex",
                          "mset", "append", "set_json", "eval", "evalsha",
                          "publish"}
_RUBY_ALL_REDIS_OPS = _RUBY_REDIS_READ_OPS | _RUBY_REDIS_WRITE_OPS


def _extract_redis_accesses_ruby(root, source: bytes, ast: FileAST):
    """Detect Redis operations in Ruby code.

    Patterns:
      - @redis = Redis.new(config)
      - @redis.get(key), @redis.hset(key, field, value)
      - redis_var = Redis.new(...); redis_var.set(...)
    """
    redis_vars: set[str] = set()

    # Track Redis.new assignments
    # Pattern: @redis = Redis.new(...) or redis = Redis.new(...)
    for call_node in _walk_all(root, "assignment"):
        left = call_node.child_by_field_name("left")
        right = call_node.child_by_field_name("right")
        if not (left and right and right.type == "call"):
            continue
        method = right.child_by_field_name("method")
        receiver = right.child_by_field_name("receiver")
        if method and receiver:
            if _text(method, source) == "new" and _text(receiver, source) == "Redis":
                var_name = _text(left, source)
                redis_vars.add(var_name)

    # Also check for require "redis" as a signal
    has_redis_import = any(
        imp.module_string == "redis" for imp in ast.imports
    )
    if has_redis_import and not redis_vars:
        # If redis is imported but no Redis.new found yet,
        # check for @redis instance var usage
        redis_vars.add("@redis")

    # Find Redis operation calls
    for call_node in _walk_all(root, "call"):
        method = call_node.child_by_field_name("method")
        receiver = call_node.child_by_field_name("receiver")
        if not (method and receiver):
            continue

        receiver_text = _text(receiver, source)
        method_text = _text(method, source)

        if receiver_text not in redis_vars:
            continue

        if method_text not in _RUBY_ALL_REDIS_OPS:
            continue

        access_type = "read" if method_text in _RUBY_REDIS_READ_OPS else "write"
        enclosing = _find_enclosing(call_node, source)

        # Extract key from first argument if it's a string
        key_name = "<dynamic>"
        args = call_node.child_by_field_name("arguments")
        if args:
            for child in args.named_children:
                if child.type == "string":
                    key_name = _get_string_value(child, source)
                    break
                if child.type != "comment":
                    break

        ast.redis_accesses.append(RedisKeyAccess(
            key_name=key_name,
            operation=method_text,
            access_type=access_type,
            function=enclosing,
            line=call_node.start_point[0] + 1,
        ))
```

Then call the function from `parse_ruby_file()`, before the `return ast` statement. Add it after the module_name assignment block and before `return ast`:

```python
    # --- Redis accesses ---
    _extract_redis_accesses_ruby(root, source, ast)

    return ast
```

### Step 5: Run tests (expect pass)

- [ ] **7.5: Run tests, confirm they pass**

```bash
python -m pytest graph_builder/tests/test_quick_fixes.py -k "test_4g" -xvs
```

### Step 6: Commit

- [ ] **7.6: Commit**

```bash
git add graph_builder/parsers/ruby_parser.py graph_builder/tests/test_quick_fixes.py graph_builder/tests/fixtures/ruby/redis_helper.rb
git commit -m "fix(4G): add Ruby Redis detection for Redis.new and @redis operations"
```

---

## Task 8: Fix 4H — Tornado Route Registration

Python services define routes via `tornado.web.Application(handlers=[...])` tuples. These are detectable route registrations that create Endpoint nodes with handler class names.

**Files:**
- Modify: `graph_builder/parsers/python_parser.py`
- Create: `graph_builder/tests/fixtures/python/tornado_app.py`
- Modify: `graph_builder/tests/test_quick_fixes.py`

### Step 1: Create test fixture

- [ ] **8.1: Create Python Tornado fixture**

Create `graph_builder/tests/fixtures/python/tornado_app.py`:

```python
"""Tornado application with route handlers."""

import tornado.web


class AddMissionHandler(tornado.web.RequestHandler):
    def post(self):
        pass


class MonitorHandler(tornado.web.RequestHandler):
    def get(self):
        pass


class HealthHandler(tornado.web.RequestHandler):
    def get(self):
        return "OK"


application = tornado.web.Application(
    handlers=[
        ("/add_mission", AddMissionHandler),
        ("/monitor", MonitorHandler),
    ],
)


def make_app():
    return tornado.web.Application([
        (r"/health", HealthHandler),
    ])
```

### Step 2: Write tests

- [ ] **8.2: Add 4H tests to test_quick_fixes.py**

Append to `graph_builder/tests/test_quick_fixes.py`:

```python
from graph_builder.parsers.base import HttpCallRef

# ───────────────────────────────────────────────────────────────
# 4H: Tornado route registration
# ───────────────────────────────────────────────────────────────

def test_4h_tornado_routes_detected():
    """tornado.web.Application handler tuples should produce endpoint entries."""
    ast = parse_python_file(str(PY_FIXTURES / "tornado_app.py"))

    # Tornado routes are stored as HttpCallRef with method="HANDLER"
    # to distinguish from outbound HTTP calls
    endpoints = [h for h in ast.http_calls if h.method == "HANDLER"]
    paths = {e.url_or_path for e in endpoints}

    assert "/add_mission" in paths, f"/add_mission not found in {paths}"
    assert "/monitor" in paths, f"/monitor not found in {paths}"
    assert "/health" in paths, f"/health not found in {paths}"


def test_4h_tornado_handler_classes_recorded():
    """Each route should record the handler class name."""
    ast = parse_python_file(str(PY_FIXTURES / "tornado_app.py"))

    endpoints = [h for h in ast.http_calls if h.method == "HANDLER"]
    handler_map = {e.url_or_path: e.function for e in endpoints}

    assert handler_map.get("/add_mission") == "AddMissionHandler", (
        f"Expected AddMissionHandler, got {handler_map.get('/add_mission')}"
    )
    assert handler_map.get("/monitor") == "MonitorHandler"
    assert handler_map.get("/health") == "HealthHandler"


def test_4h_at_least_three_routes():
    """Should detect all 3 routes across both Application() patterns."""
    ast = parse_python_file(str(PY_FIXTURES / "tornado_app.py"))
    endpoints = [h for h in ast.http_calls if h.method == "HANDLER"]
    assert len(endpoints) >= 3, (
        f"Expected >=3 Tornado routes, got {len(endpoints)}: "
        f"{[(e.url_or_path, e.function) for e in endpoints]}"
    )
```

### Step 3: Run tests (expect failure)

- [ ] **8.3: Run tests, confirm they fail**

```bash
python -m pytest graph_builder/tests/test_quick_fixes.py -k "test_4h" -xvs
```

### Step 4: Implement the fix

- [ ] **8.4: Add Tornado route detection to `python_parser.py`**

In `graph_builder/parsers/python_parser.py`, add a new function before the `_extract_http_calls_python` function:

```python
def _extract_tornado_routes_python(root, source: bytes, ast: FileAST):
    """Detect Tornado route registrations.

    Patterns:
      tornado.web.Application(handlers=[(path, Handler), ...])
      tornado.web.Application([(path, Handler), ...])
    """
    for call_node in _walk_all(root, "call"):
        func = call_node.child_by_field_name("function")
        if not func:
            continue
        callee = _text(func, source)
        if "Application" not in callee:
            continue
        # Match tornado.web.Application or just Application
        if callee not in ("tornado.web.Application", "Application"):
            continue

        args = call_node.child_by_field_name("arguments")
        if not args:
            continue

        # Find the handlers list — either as keyword arg or positional
        handler_lists = []
        for arg in args.named_children:
            # keyword_argument: handlers=[...]
            if arg.type == "keyword_argument":
                key = arg.child_by_field_name("name")
                val = arg.child_by_field_name("value")
                if key and _text(key, source) == "handlers" and val and val.type == "list":
                    handler_lists.append(val)
            # Positional list: Application([...])
            elif arg.type == "list":
                handler_lists.append(arg)

        for handler_list in handler_lists:
            for child in handler_list.named_children:
                if child.type != "tuple":
                    continue
                # Extract (path_string, HandlerClass, ...) tuple
                elements = child.named_children
                if len(elements) < 2:
                    continue
                path_node = elements[0]
                handler_node = elements[1]

                # Path should be a string
                if path_node.type != "string":
                    continue
                path = _text(path_node, source).strip("\"'")
                # Remove regex prefix r"..."
                if path.startswith("r"):
                    path = path[1:].strip("\"'")

                # Handler should be an identifier (class name)
                handler_name = _text(handler_node, source)

                ast.http_calls.append(HttpCallRef(
                    url_or_path=path,
                    method="HANDLER",
                    function=handler_name,
                    line=child.start_point[0] + 1,
                ))
```

Then call the function from `parse_python_file()`. Add it right before `return ast` (after the HTTP calls extraction):

```python
    # --- Tornado route detection ---
    _extract_tornado_routes_python(root, source, ast)

    return ast
```

### Step 5: Run tests (expect pass)

- [ ] **8.5: Run tests, confirm they pass**

```bash
python -m pytest graph_builder/tests/test_quick_fixes.py -k "test_4h" -xvs
```

### Step 6: Commit

- [ ] **8.6: Commit**

```bash
git add graph_builder/parsers/python_parser.py graph_builder/tests/test_quick_fixes.py graph_builder/tests/fixtures/python/tornado_app.py
git commit -m "fix(4H): detect Tornado route registrations in Python services"
```

---

## Final Verification

- [ ] **9.1: Run all quick-fix tests together**

```bash
python -m pytest graph_builder/tests/test_quick_fixes.py -v
```

All 24 tests should pass.

- [ ] **9.2: Run full test suite to check for regressions**

```bash
python -m pytest graph_builder/tests/ -v
```

Ensure no existing tests break from the changes to `base.py` (added `is_interface` field with default `False`), `call_resolver.py`, `graph_health.py`, `python_parser.py`, `ruby_parser.py`, or `redis_abstraction_resolver.py`.

- [ ] **9.3: Commit final state**

```bash
git add -A
git commit -m "test: verify all quick-fix tests pass with no regressions"
```

---

## Expected Impact Summary

| Fix | Before | After | Lines Changed |
|-----|--------|-------|---------------|
| 4A Go Redis | 0 ops | ~93 ops | ~5 lines in redis_abstraction_resolver + 2 lines in graph_health |
| 4B Python self | 42 functions w/ calls | ~200+ | ~8 lines in call_resolver |
| 4C Python RedisCluster | 0 ops | 1 op | ~20 lines in python_parser |
| 4D Ruby loading | 88 orphans | ~20-25 orphans | ~40 lines in ruby_resolver + 8 lines in writer |
| 4E Ruby metrics | 0 functions w/ calls | ~800+ | ~10 lines in graph_health + ~10 lines in ruby_parser |
| 4F Go interfaces | 0 IMPLEMENTS edges | ~7-10 edges | ~1 line base.py + ~3 lines go_parser + ~30 lines go_resolver + 8 lines writer |
| 4G Ruby Redis | 0 ops | ~5-10 ops | ~60 lines in ruby_parser |
| 4H Tornado routes | 0 endpoints | ~7-10 endpoint edges | ~50 lines in python_parser |
