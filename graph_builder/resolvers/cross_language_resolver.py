"""Cross-language data flow resolver: shared structures and constants.

Uses static configuration maps (from BOB investigation) to create edges
linking files that define the same data structures or constants across
languages. Same approach as shared Redis patterns in cross_service_resolver.py.
"""

from __future__ import annotations

from graph_builder.parsers.base import FileAST
from graph_builder.resolvers.cross_service_resolver import (
    _build_suffix_index,
    _match_file_suffix,
)


# =============================================================================
# Section 1: Shared Data Structures
# =============================================================================

SHARED_DATA_STRUCTURES = [
    {
        "name": "SessionInfo",
        "fields": ["session_id", "user_id", "device_id", "ip_address",
                   "user_agent", "timestamp", "risk_score", "attributes"],
        "definitions": {
            "lua": ["ato/models/session_info.lua"],
            "go": ["core/model_prediction/server/models/session.go"],
            "python": ["deferrer/poller/poller/models/session.py"],
        },
        "serialization": "json",
    },
    {
        "name": "ModelPredictionResult",
        "fields": ["model_type", "score", "features", "model_version",
                   "timestamp"],
        "definitions": {
            "go": ["core/model_prediction/server/models/model_prediction.go"],
            "lua": ["core/model_prediction/client/models/task.lua"],
            "python": ["deferrer/poller/poller/models/prediction.py"],
        },
        "serialization": "json",
    },
    {
        "name": "Event",
        "fields": ["event_type", "session_id", "user_id", "timestamp",
                   "data"],
        "definitions": {
            "ruby": ["common/generator/lib/models/event.rb"],
            "lua": ["ato/events/init.lua"],
        },
        "serialization": "json",
    },
]


# =============================================================================
# Section 2: Shared Constants
# =============================================================================

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


# =============================================================================
# Section 3: Resolver Functions
# =============================================================================

def resolve_shared_structures(all_asts: dict[str, FileAST]) -> list[dict]:
    """Create DEFINES_SHARED_STRUCTURE edges from the static config map.

    For each known shared structure, checks if definition file paths match
    any parsed file. Uses suffix matching to handle different repo_root prefixes.

    Returns list of edge dicts:
        [{"structure_name", "fields", "serialization", "file", "language", "field_count"}]
    """
    edges: list[dict] = []
    suffix_index = _build_suffix_index(all_asts)

    for struct_cfg in SHARED_DATA_STRUCTURES:
        name = struct_cfg["name"]
        fields = struct_cfg["fields"]
        serialization = struct_cfg["serialization"]

        for language, file_patterns in struct_cfg["definitions"].items():
            for pattern in file_patterns:
                matched = _match_file_suffix(pattern, suffix_index)
                if matched:
                    edges.append({
                        "structure_name": name,
                        "fields": fields,
                        "serialization": serialization,
                        "file": matched,
                        "language": language,
                        "field_count": len(fields),
                    })

    return edges


def resolve_shared_constants(all_asts: dict[str, FileAST]) -> list[dict]:
    """Create DEFINES_CONSTANT edges from the static config map.

    For each known shared constant set, checks if definition file paths match
    any parsed file. Uses suffix matching to handle different repo_root prefixes.

    Returns list of edge dicts:
        [{"constant_name", "values", "file", "language"}]
    """
    edges: list[dict] = []
    suffix_index = _build_suffix_index(all_asts)

    for const_cfg in SHARED_CONSTANTS:
        name = const_cfg["name"]
        values = const_cfg["values"]

        for language, file_patterns in const_cfg["files"].items():
            for pattern in file_patterns:
                matched = _match_file_suffix(pattern, suffix_index)
                if matched:
                    edges.append({
                        "constant_name": name,
                        "values": values,
                        "file": matched,
                        "language": language,
                    })

    return edges
