# Cross-Language Data Flow — Design Spec

**Date:** 2026-03-31
**Goal:** Detect shared data structures defined in multiple languages and create edges linking corresponding definitions. BOB confirmed 3 shared structures + shared constants across Lua, Go, Python, and Ruby.

---

## Problem

The Pinpoint codebase defines the same data structures in 3+ languages with no formal schema (no protobuf, no JSON Schema). When a field is added/renamed in one language, the others must be updated manually. The graph currently has no edges connecting these corresponding definitions.

BOB confirmed these shared structures:

| Structure | Languages | Use |
|-----------|-----------|-----|
| SessionInfo | Lua, Go, Python | Session tracking across all services |
| ModelPredictionResult | Go, Lua, Python | ML prediction output |
| Event | Ruby, Lua | Event data for processing and upload |
| Constants (MODEL_TYPES, RISK_LEVELS) | Lua, Go, Python | Shared enum-like constants |

---

## 1. SharedDataStructure Node Type

### New Graph Elements

```
Node: SharedDataStructure
  Properties: name, fields (list), serialization_format

Edge: DEFINES_SHARED_STRUCTURE (File → SharedDataStructure)
  Properties: language, field_count

Edge: CONSUMES_SHARED_STRUCTURE (File → SharedDataStructure)
  Properties: language, via (http/redis/cassandra)
```

### Detection Approach

**Static configuration** (like shared Redis patterns) — define known shared structures:

```python
SHARED_DATA_STRUCTURES = [
    {
        "name": "SessionInfo",
        "fields": ["session_id", "user_id", "device_id", "ip_address", "user_agent",
                   "timestamp", "risk_score", "attributes"],
        "definitions": {
            "lua": ["ato/models/session_info.lua"],
            "go": ["core/model_prediction/server/models/session.go"],
            "python": ["deferrer/poller/poller/models/session.py"],
        },
        "serialization": "json",
    },
    {
        "name": "ModelPredictionResult",
        "fields": ["model_type", "score", "features", "model_version", "timestamp"],
        "definitions": {
            "go": ["core/model_prediction/server/models/model_prediction.go"],
            "lua": ["core/model_prediction/client/models/task.lua"],
            "python": ["deferrer/poller/poller/models/prediction.py"],
        },
        "serialization": "json",
    },
    {
        "name": "Event",
        "fields": ["event_type", "session_id", "user_id", "timestamp", "data"],
        "definitions": {
            "ruby": ["common/generator/lib/models/event.rb"],
            "lua": ["ato/events/init.lua"],
        },
        "serialization": "json",
    },
]
```

### Why Static Configuration

Cross-language data structure detection by AST analysis is unreliable — field names like `session_id` appear in hundreds of files without indicating a shared structure. BOB's investigation provides the ground truth. This is the same approach used for shared Redis key patterns and shared config files.

---

## 2. Shared Constants Detection

### What to Detect

BOB confirmed identical constants in 3 languages:

**Lua:**
```lua
local Constants = {
    MODEL_TYPES = { FRAUD_DETECTION = "fraud_detection", ... },
    RISK_LEVELS = { LOW = "low", MEDIUM = "medium", HIGH = "high", CRITICAL = "critical" }
}
```

**Go:**
```go
const (
    ModelTypeFraudDetection = "fraud_detection"
    RiskLevelLow = "low"
    ...
)
```

**Python:**
```python
MODEL_TYPES = { 'FRAUD_DETECTION': 'fraud_detection', ... }
RISK_LEVELS = { 'LOW': 'low', ... }
```

### Detection Approach

Add to the static configuration:
```python
SHARED_CONSTANTS = [
    {
        "name": "MODEL_TYPES",
        "values": ["fraud_detection", "ato_detection", "behavior_analysis"],
        "files": {
            "lua": ["ato/config/init.lua"],
            "go": ["core/model_prediction/server/common/constants/constants.go"],
            "python": ["deferrer/poller/poller/constants.py"],
        },
    },
    {
        "name": "RISK_LEVELS",
        "values": ["low", "medium", "high", "critical"],
        "files": {
            "lua": ["ato/config/init.lua"],
            "go": ["core/model_prediction/server/common/constants/constants.go"],
            "python": ["deferrer/poller/poller/constants.py"],
        },
    },
]
```

Create `SharedConstant` nodes and `DEFINES_CONSTANT` edges.

---

## 3. Cross-Language Request/Response Flow

### What BOB Revealed

**Flow 1: Python → Lua (task dispatch)**
```
Python poller → HTTP POST /tasks → Lua TaskController
  Request body: {task_id, task_type, session_id, user_id, priority, data: {features, context}, callback_url}
  Lua extracts: task_data.task_id, task_data.data.features.device_id, etc.
```

**Flow 2: Lua → Go (prediction request)**
```
Lua unix_socket_client → Unix socket → Go ModelPredictionService
  Request body: {session_id, predictions: [{model_type, score, features, metadata}], status}
  Go parses: json.Unmarshal → PredictionResponse struct
```

### Detection Approach

This is already partially handled by:
- Unix socket edges (cross_service_resolver)
- Internal endpoint mapping (endpoint_linker)

The new addition: create `PASSES_DATA_STRUCTURE` edges that link the calling function to the SharedDataStructure being serialized/deserialized:

```python
# When Lua calls cjson.encode(response_data) and response_data matches SessionInfo fields
# → PASSES_DATA_STRUCTURE edge from function to SessionInfo node

# When Go calls json.Unmarshal(body, &response) and response is PredictionResponse
# → PASSES_DATA_STRUCTURE edge from function to ModelPredictionResult node
```

This requires matching the struct/table field names against known SharedDataStructure fields — best-effort heuristic, not 100% accurate.

---

## Implementation File

`graph_builder/resolvers/cross_language_resolver.py` — **new file**

Contains:
- `SHARED_DATA_STRUCTURES` static config
- `SHARED_CONSTANTS` static config
- `resolve_shared_structures(all_asts)` → edges
- `resolve_shared_constants(all_asts)` → edges

---

## Writer Additions

| Method | Edge Type |
|--------|-----------|
| `upsert_shared_data_structure(name, fields, format)` | SharedDataStructure node |
| `upsert_defines_structure(file, structure, language)` | DEFINES_SHARED_STRUCTURE |
| `upsert_shared_constant(name, values)` | SharedConstant node |
| `upsert_defines_constant(file, constant, language)` | DEFINES_CONSTANT |

---

## Schema Additions

- Node: `SharedDataStructure` (name, fields, serialization_format)
- Node: `SharedConstant` (name, values)
- Edge: `DEFINES_SHARED_STRUCTURE` (File → SharedDataStructure)
- Edge: `DEFINES_CONSTANT` (File → SharedConstant)

---

## Testing Strategy

1. **Shared structures:** Verify file path matching creates correct edges
2. **Shared constants:** Verify constant nodes created with correct file associations
3. **Integration:** Run resolver on fixtures and verify edge structure

---

## Expected Impact

| Component | New Edges |
|-----------|-----------|
| SessionInfo structure | ~6 (3 languages × 2 edges each) |
| ModelPredictionResult | ~6 |
| Event structure | ~4 |
| MODEL_TYPES constant | ~6 |
| RISK_LEVELS constant | ~6 |
| **Total** | **~28 cross-language structural edges** |

---

## Files Modified

| File | Change |
|------|--------|
| `graph_builder/resolvers/cross_language_resolver.py` | **New** — shared structures and constants detection |
| `graph_builder/ingestion/writer.py` | New upsert methods for structures and constants |
| `graph_builder/ingestion/schema.py` | SharedDataStructure, SharedConstant nodes + edges |
| `graph_builder/main.py` | Wire cross-language resolver into pipeline |
| `graph_builder/tests/test_cross_language.py` | New test file |
