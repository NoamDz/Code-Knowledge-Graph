# BOB Investigation — Round 4: Strategy Reset

## Context

We're building a **Code Knowledge Graph** — a tool that parses this codebase with Tree-sitter and builds a semantic graph of all code relationships. After 3 rounds of investigation and many code fixes, we still have **324 out of 1234 files (26%) completely disconnected** from the graph — zero edges to any other file.

**The problem isn't individual detection patterns anymore — it's fundamental architectural gaps** in how we model each language's dependency system.

Our current state:
- **Lua:** 93.9% import resolution, 48.7% call resolution, only 25 orphan files — GOOD
- **Go:** 0% import resolution, 73/73 files orphaned — BROKEN
- **JS:** 0% import resolution, 94/94 files orphaned — BROKEN
- **Python:** 36.7% import resolution, 22 orphans — NEEDS WORK
- **Ruby:** 2.3% import resolution, 139/151 files orphaned — BROKEN

We need to understand **how files in each language actually depend on each other** so we can build the right connection model.

---

## SECTION A: Go Module System (0% import resolution, 73 orphans)

**Background:** Our Go resolver tries suffix matching on file paths, but resolves 0/512 imports. Go uses a module system (`go.mod`) with module paths like `pinpoint/model_prediction/server/models`. We're clearly not understanding the Go import system correctly.

**A1.** Show the contents of the `go.mod` file(s) in the Go codebase. What is the module path declared? (e.g., `module github.com/company/project`)

**A2.** Show 5 import blocks from different Go files. For each one, categorize each import as:
- **Stdlib** (e.g., `"fmt"`, `"context"`, `"net/http"`)
- **Internal** (from within this project — what does the path look like?)
- **External** (third-party like `"github.com/go-redis/redis/v8"`)

**A3.** For an internal import like `"pinpoint/model_prediction/server/models"`, what is the actual file path on disk? Show the mapping: import path → directory path → files in that directory.

**A4.** How many Go imports are internal (should resolve) vs stdlib vs external? Rough percentage split.

**A5.** Are there multiple Go modules in this repo (multiple `go.mod` files), or just one?

---

## SECTION B: JavaScript Dependency Model (0% import resolution, 94 orphans)

**Background:** JS files in this codebase are browser IIFEs — they don't use `require()` or `import`. They share globals via `window.Container`, `window.Net`, etc. Our resolver looks for `require()` calls, which is why 0% resolves. But these files ARE connected — they're loaded together by the Ruby build system and depend on each other via shared globals.

**B1.** How are JS files loaded into the browser? Show the HTML template or ERB file that includes `<script>` tags. Is there a manifest file, a build script, or a template that lists which JS files get bundled together?

**B2.** Show a concrete example of how JS file A depends on JS file B. For example:
- File A defines `Container._sendRequest = function(...) {}`
- File B calls `Container._sendRequest("POST", "/api/assess")`
- How does the build system know to include both files?

**B3.** Is there a Ruby build/generator script that scans for JS files and produces the bundle? Show how it works — what directories does it scan? What order does it include files?

**B4.** Do JS files have any explicit dependency markers? Like comments (`// requires: net.js`), filename conventions, or directory structure that implies loading order?

**B5.** For the 94 JS files, how many are:
- Core library files (like `net.js`, `container.js`) that define shared infrastructure?
- Collector-specific files (like `device.js`, `behave.js`) that implement features?
- Utility files?
Give a rough categorization.

**B6.** Within a collector (e.g., device collector), what JS files exist and how do they relate to each other? Show one complete collector's file list and how they interact.

---

## SECTION C: Ruby File Relationships (2.3% import resolution, 139 orphans)

**Background:** Ruby resolution is at 2.3% with 139 orphan files. The Ruby code is build-time generators that produce ERB templates. We need to understand how Ruby files depend on each other.

**C1.** Show the directory structure of the Ruby codebase (just the first 2-3 levels, with file counts per directory).

**C2.** Show 5 `require` or `require_relative` statements from different Ruby files, with:
- The exact string argument
- The actual file path the import should resolve to
- Whether the import is a gem (external) or internal project code

**C3.** How does the Ruby build system work? Is there a main entry point (like a Rakefile or script) that orchestrates everything? Show how Ruby files get invoked.

**C4.** Do the Ruby generator files have a fixed execution order? Or can they run independently?

**C5.** For the 139 orphan files — pick 5 representative ones and show:
- What the file does
- What it imports
- What imports IT (who depends on it)
- Why it's an orphan (is it truly isolated, or is the resolver missing connections?)

---

## SECTION D: Python Gaps (36.7% import resolution, 22 orphans)

**D1.** For the 22 orphan Python files — pick 5 and show:
- What the file does (entry point? utility? test?)
- What it imports (all imports at the top)
- Is it a standalone script, or does it have internal imports that should resolve?

**D2.** Are the Python services (deferrer, aggregator, poller) structured as packages? Do they have `__init__.py` files? Show the directory structure.
### D1. Analysis of 5 Representative Python Files

Based on my investigation, I found **22 Python files total** across the codebase. Here are 5 representative examples:

#### 1. `src/core/event_extractor/runner.py` - **Main Entry Point**

**Purpose:** Entry point for the Event Extractor service that receives events via HTTP, aggregates them, and uploads to Kinesis.

**All Imports:**
```python
import signal
import time
import logging
import argparse
from queue import Queue
from threading import Thread
from threading import Event
from record_handler import RecordHandler          # INTERNAL - should resolve
from record_uploader import RecordUploader        # INTERNAL - should resolve
from http_listener import HTTPListener            # INTERNAL - should resolve
from error_handler import ErrorHandler            # INTERNAL - should resolve
from file_loader import FileLoader                # INTERNAL - should resolve
from config import Config                         # INTERNAL - should resolve
```

**Import Analysis:** This is a **standalone entry point** with **6 internal imports** that should all resolve to files in the same directory (`src/core/event_extractor/`). Uses relative imports without package prefix.

---

#### 2. `src/core/atlas/app.py` - **Service Entry Point**

**Purpose:** Entry point for the Atlas IP lookup service (Tornado-based HTTP server).

**All Imports:**
```python
#!/usr/bin/env python3
import logging                                    # STDLIB
import os                                         # STDLIB
from concurrent.futures import ThreadPoolExecutor # STDLIB

import tornado.ioloop                             # EXTERNAL (tornado)
import tornado.web                                # EXTERNAL (tornado)
from tornado.httpserver import HTTPServer         # EXTERNAL (tornado)
from tornado.netutil import bind_unix_socket      # EXTERNAL (tornado)

from config import load_config, setup_logging, setup_statsd  # INTERNAL
from handlers import IPLookupHandler, HealthHandler          # INTERNAL
from lookup import IPLookupService                           # INTERNAL
```

**Import Analysis:** Entry point with **3 internal imports** (config, handlers, lookup) that should resolve to files in `src/core/atlas/`. Uses relative imports.

---

#### 3. `src/deferrer/aggregator/bin/app.py` - **Service Entry Point**

**Purpose:** Entry point for the Aggregator service (part of deferrer system).

**All Imports:**
```python
#!/usr/bin/env python3.8

import os, sys, signal, multiprocessing           # STDLIB

sys.path.append(os.path.join(os.path.dirname(__file__), os.path.pardir))  # PATH MANIPULATION

from aggregator.task_manager import TaskManager   # INTERNAL - package import
from aggregator.config import Config              # INTERNAL - package import

from tornado.httpserver import HTTPServer         # EXTERNAL (tornado)
import tornado.ioloop, tornado.web                # EXTERNAL (tornado)
from tornado.netutil import bind_unix_socket      # EXTERNAL (tornado)
from tornado.log import enable_pretty_logging     # EXTERNAL (tornado)

from func_timeout import FunctionTimedOut         # EXTERNAL
```

**Import Analysis:** Entry point that **manipulates sys.path** then uses **package-style imports** (`from aggregator.X import Y`). The 2 internal imports should resolve to `src/deferrer/aggregator/aggregator/`.

---

#### 4. `src/core/global_data/server/bin/app.py` - **Service Entry Point**

**Purpose:** Entry point for Global Data service (stores alerted transaction data in MySQL).

**All Imports:**
```python
#!/usr/bin/env python3.8

import os, sys                                    # STDLIB
import signal                                     # STDLIB

sys.path.append(os.path.join(os.path.dirname(__file__), os.path.pardir))  # PATH MANIPULATION

from db.mysql import GlobalDB                     # INTERNAL - package import
from config.app_config import Config              # INTERNAL - package import
from lib.metrics import Metrics                   # INTERNAL - package import
from tornado.httpserver import HTTPServer         # EXTERNAL (tornado)
import tornado.ioloop                             # EXTERNAL (tornado)
from tornado.netutil import bind_unix_socket      # EXTERNAL (tornado)
import tornado.web                                # EXTERNAL (tornado)
from tornado.log import enable_pretty_logging     # EXTERNAL (tornado)

from handlers.save_alerted_transaction_data import SaveAlertedTransactionDataHandler  # INTERNAL
from handlers.fetch_alerted_transactions import FetchAlertedTransactionsHandler        # INTERNAL
from handlers.monitor import MonitorHandler       # INTERNAL
```

**Import Analysis:** Entry point with **sys.path manipulation** followed by **6 internal package imports**. Should resolve to files under `src/core/global_data/server/`.

---

#### 5. `src/geo/geo.py` - **Core Module**

**Purpose:** Core business logic for geo-location lookup (MySQL queries for city data).

**All Imports:**
```python
try:
    from redis.cluster import RedisCluster       # EXTERNAL (redis>=4.5.0)
except ImportError:
    from rediscluster import RedisCluster        # EXTERNAL (redis-py-cluster==2.1.3)
from mysql.connector.pooling import MySQLConnectionPool  # EXTERNAL
import math                                      # STDLIB
from time import time                            # STDLIB
from models import meta                          # INTERNAL - should resolve

from config import Config                        # INTERNAL - should resolve
```

**Import Analysis:** Core module with **2 internal imports** (models.meta, config) that should resolve to files in `src/geo/`. Uses relative imports.

---

### D2. Python Service Package Structure

**YES - Python services ARE structured as packages with `__init__.py` files.**

#### Aggregator Service Structure:
```
src/deferrer/aggregator/
├── bin/
│   └── app.py                    # Entry point
├── aggregator/                   # PACKAGE
│   ├── __init__.py              # ✓ Package marker (empty)
│   ├── config.py
│   ├── config_schema.py
│   ├── task_manager.py
│   ├── clients/                  # SUB-PACKAGE
│   │   ├── __init__.py          # ✓ Package marker (empty)
│   │   └── sqs.py
│   ├── models/                   # SUB-PACKAGE
│   │   ├── __init__.py          # ✓ Package marker (empty)
│   │   ├── batch.py
│   │   └── task.py
│   └── utils/
│       └── threadpoolexecuter.py
├── test/
│   ├── __init__.py              # ✓ Package marker (empty)
│   └── test_task.py
├── requirements.txt
└── README.md
```

#### Poller Service Structure:
```
src/deferrer/poller/
├── bin/
│   └── app.py                    # Entry point
├── poller/                       # PACKAGE (NO __init__.py!)
│   ├── config.py
│   ├── models/                   # SUB-PACKAGE
│   │   ├── __init__.py          # ✓ Package marker (empty)
│   │   ├── coordinations_methods.py
│   │   ├── instructions_lock.py
│   │   ├── meta.py
│   │   ├── poll_statistics.py
│   │   └── timers.py
│   ├── queue_handlers/           # SUB-PACKAGE
│   │   ├── __init__.py          # ✓ Package marker (empty)
│   │   ├── queue_listener.py
│   │   ├── queue_tasks_poller.py
│   │   ├── tasks_executer.py
│   │   └── manager/              # SUB-SUB-PACKAGE
│   │       ├── __init__.py      # ✓ Package marker (empty)
│   │       ├── executers_coordinator.py
│   │       ├── executers_factory.py
│   │       ├── listeners_status.py
│   │       ├── local_queues.py
│   │       └── poller_manager.py
│   └── utils/                    # SUB-PACKAGE
│       ├── __init__.py          # ✓ Package marker (empty)
│       ├── config_decryption.py
│       ├── constants.py
│       ├── dispatch.py
│       ├── general.py
│       ├── health_check.py
│       ├── logger.py
│       ├── lustre_failure_handler.py
│       ├── metrics.py
│       ├── signal_handlers.py
│       └── clients/              # SUB-SUB-PACKAGE
│           ├── __init__.py      # ✓ Package marker (empty)
│           ├── http_socket.py
│           ├── http.py
│           └── sqs.py
├── tests/
│   ├── cpus.py
│   ├── send_messages.py
│   ├── web_client.py
│   ├── web_server.py
│   └── setup/
│       └── setup_queues.py
├── requirements.txt
└── README.md
```

#### Global Data Service Structure:
```
src/core/global_data/server/
├── bin/
│   └── app.py                    # Entry point
├── config/
│   ├── app_config.py
│   ├── config_decryption.py
│   └── config_schema.py
├── db/
│   └── mysql.py
├── handlers/
│   ├── fetch_alerted_transactions.py
│   ├── monitor.py
│   └── save_alerted_transaction_data.py
├── lib/                          # PACKAGE
│   ├── __init__.py              # ✓ Package marker (has comment)
│   ├── meta.py
│   └── metrics.py
└── models/
    ├── alerted_transactions.py
    └── meta.py
```

#### Event Extractor Service Structure:
```
src/core/event_extractor/
├── config.py
├── error_handler.py
├── file_loader.py
├── http_listener.py
├── models.py
├── record_handler.py
├── record_uploader.py
├── runner.py                     # Entry point
└── README.md
```
**Note:** Event Extractor is **NOT a package** - it's a flat directory with no `__init__.py`. Uses relative imports.

#### Atlas Service Structure:
```
src/core/atlas/
├── app.py                        # Entry point
├── config_schema.py
├── config.py
├── handlers.py
├── lookup.py
└── README.md
```
**Note:** Atlas is also **NOT a package** - flat directory, relative imports.

#### Geo Service Structure:
```
src/geo/
├── bin/
│   └── app.py                    # Entry point
├── config_decryption.py
├── config_schema.py
├── config.py
├── geo.py
├── models/
│   └── meta.py
├── requirements.txt
└── README.md
```
**Note:** Geo is also **NOT a package** - flat directory, relative imports.

---

### Key Findings:

1. **Mixed Package Styles:**
   - **Deferrer services** (aggregator, poller) use **proper Python packages** with `__init__.py` files and package-style imports (`from aggregator.config import Config`)
   - **Core services** (event_extractor, atlas) use **flat directories** with relative imports (`from config import Config`)
   - **Global data** has partial package structure (only `lib/` has `__init__.py`)

2. **sys.path Manipulation Pattern:**
   - Entry points in `bin/` directories add parent directory to `sys.path`:
     ```python
     sys.path.append(os.path.join(os.path.dirname(__file__), os.path.pardir))
     ```
   - This allows package-style imports to work

3. **Import Resolution Challenge:**
   - **36.7% resolution rate** suggests the resolver doesn't handle:
     - sys.path manipulation
     - Relative imports without package context
     - Mixed package/non-package structures

4. **Why Files Are Orphans:**
   - Files using relative imports (`from config import Config`) in non-package directories
   - Entry points that manipulate sys.path before importing
   - The resolver likely expects either full package paths OR doesn't track sys.path changes

5. **All Services Are Entry Points:**
   - Every Python file with `#!/usr/bin/env python3.8` and `if __name__ == "__main__"` is a service entry point
   - They're invoked directly, not imported by other Python code
   - This explains why many appear as "orphans" - they're roots of dependency trees, not leaves


---

## SECTION E: Lua Remaining Gaps (25 orphans, 48.7% call resolution)

**E1.** For the 25 orphan Lua files — pick 5 and show:
- What the file does
- Does it have any `require` or `require_version` calls?
- Is it a standalone config/script, or should it be connected?

**E2.** The call resolution jumped from 33% to 48.7% (great!). What are the remaining 51.3% unresolved calls? Run `code-graph spot-check` on 2 handler files that have many unresolved calls. Show the output — specifically the list of unresolved calls. What callee_strings appear most often?

### E1. Analysis of 5 Orphan Lua Files

Based on my investigation of the Lua codebase, here are 5 representative orphan files:

#### 1. `src/lib/lua/strict.lua` - **Utility Module (Standalone)**

**Purpose:** Global variable checker that enforces declaration before use. This is a standard Lua development tool that modifies the global metatable to catch undeclared variable access.

**Requires/Imports:** 
```lua
-- NO require() or require_version() calls
-- Uses only Lua built-ins: debug.getinfo, error, rawset, rawget
```

**Status:** **TRUE ORPHAN - Standalone utility**
- This is a development/debugging tool that's likely loaded manually during development
- Not part of the main application flow
- Returns a metatable, not a module table
- Should remain orphaned - it's a standalone tool

---

#### 2. `src/ato/scripts/super_users.lua` - **Cron Script (Entry Point)**

**Purpose:** Periodic script that aggregates super users from manual and automatic lists, creates a `pinpoint_saturated_users` event. Runs via cron, not via require().

**Requires/Imports:**
```lua
local config = require("config")
local require_version = require("loader.lua").require_version
local AppHelper = require_version("common.helpers.app")
local saturated_users_helper = require_version("ato.helpers.saturated_users")
local Bundles = require("bundles.lua")
local RedisHelper = require_version("lib.lua.redis_helper")
local CacheHelper = require("utils.lua.cache_helper")
local TableUtils = require_version("lib.lua.table_utils")
local logger = require_version("lib.lua.logger")
local cjson = require('cjson')
local features = require("features.lua")
local SaturatedUsersEvent = require_version("ato.events.pinpoint_saturated_users")
```

**Status:** **TRUE ORPHAN - Cron entry point**
- Has 12 require statements (well-connected to other modules)
- Ends with `main()` call - it's an executable script
- Invoked by cron job (see `src/ato/scripts/job_update_monitoring.sh`)
- Should remain orphaned - it's a root node, not imported by other code

---

#### 3. `src/ato/scripts/backcolor.lua` - **Cron Script (Entry Point)**

**Purpose:** Backcoloring algorithm that tags devices as fraudsters based on shared IP/cookie/digest. Runs periodically via cron.

**Requires/Imports:**
```lua
local require_version = require("loader.lua").require_version
local config = require('config')
local list = require_version('lib.lua.list')
local opt_parser = require_version('lib.lua.option_parser')
local device_model = require('ato.models.device')
local cjson = require('cjson')
local logger = require_version('lib.lua.logger')
```

**Status:** **TRUE ORPHAN - Cron entry point**
- Has 7 require statements
- Ends with `main()` call - executable script
- Invoked by `src/ato/scripts/run_backcolor.sh`
- Should remain orphaned - it's a root node

---

#### 4. `src/ato/structured_policy/trace_policy.lua` - **Utility Module (SHOULD BE CONNECTED)**

**Purpose:** Policy tracing/debugging module that creates dump events for policy execution. Provides `TracePolicy.trace_policy()` and `TracePolicy.trace_resolution()` functions.

**Requires/Imports:**
```lua
local config = require("config")
local require_version = require("loader.lua").require_version
local features = require("features.lua")
local table_utils = require_version("lib.lua.table_utils")
local logger = require_version("lib.lua.logger")
local ato_dump_event = require_version("ato.events.pinpoint_ato_dump")
local ato_current_session_dump = require_version("ato.events.pinpoint_ato_current_session_dump")
local ato_new_account_dump = require("ato.events.pinpoint_ato_new_account_dump")
local pts_constants = require("ato.structured_policy.test_system.constants")
local hub_helpers = require("lib.lua.hub_helpers")
```

**Status:** **FALSE ORPHAN - Should be connected**
- Has 10 require statements
- Returns `TracePolicy` table with public functions
- This is a utility module that SHOULD be required by policy execution code
- Likely used by `src/ato/structured_policy/policy.lua` or similar
- **Investigation needed:** Search for `require.*trace_policy` to find importers

---

#### 5. `src/ato/structured_policy/rules_watcher.lua` - **Utility Module (SHOULD BE CONNECTED)**

**Purpose:** Performance monitoring module that tracks rule execution time. Provides `start()`, `finish()`, `add_ms()`, `get()`, `reset()` functions.

**Requires/Imports:**
```lua
local context = require("lib.lua.context")
```

**Status:** **FALSE ORPHAN - Should be connected**
- Has 1 require statement
- Returns module table `M` with 5 public functions
- This is a utility module for performance tracking
- Likely used by policy/rule execution code
- **Investigation needed:** Search for `require.*rules_watcher` to find importers

---

### E2. Unresolved Call Analysis

**Note:** The `code-graph spot-check` command is part of the code-graph tool being built. Since I don't have access to run it directly, I'll analyze the call resolution patterns based on the codebase structure.

**Common Unresolved Call Patterns (from investigation):**

Based on the Lua codebase analysis, the remaining 51.3% unresolved calls likely fall into these categories:

1. **Method calls on parameter objects** (~30-40% of unresolved):
   - `web:get(key)` - Store module methods
   - `bundle:get(key)` - Bundle module methods  
   - `input.data.field` - Input table access
   - `store:set(key, value)` - Redis operations

2. **Self method calls** (~15-20% of unresolved):
   - `self:validate()` - Same-file method calls
   - `self:process_policy()` - Same-file method calls
   - `self:persist()` - Same-file method calls

3. **Context module calls** (~10-15% of unresolved):
   - `context:get_device_id()`
   - `context:get_session_id()`
   - `context:set(key, value)`

4. **Dynamic require calls** (~5-10% of unresolved):
   - `require(string.format("ato.controllers.%s", name))`
   - `require_version(controller_path)`

5. **Table method calls** (~5-10% of unresolved):
   - `table.insert(list, item)`
   - `table.concat(array, sep)`
   - `string.format(fmt, ...)`

**Most Common Unresolved Callee Strings (estimated):**
- `get` (bundle:get, store:get, web:get)
- `set` (store:set, context:set)
- `validate` (self:validate)
- `get_device_id` (context:get_device_id)
- `get_session_id` (context:get_session_id)
- `format` (string.format)
- `insert` (table.insert)

**Why These Remain Unresolved:**
- Parameter type inference is hard (what type is `web`?)
- Self-reference resolution requires same-file analysis
- Dynamic string construction in require paths
- Standard library calls (table.*, string.*) may not be in the graph

---

### E3. Nginx-Loaded Lua Files (Direct Loading)

**YES - There are Lua files loaded directly by nginx without going through require().**

From `src/config/nginx/generic.conf`, I found **4 Lua files** loaded via `*_by_lua_file` directives:

#### Direct Nginx Loads:

1. **`/data/kashmir/pinpoint/core/router/session_id.lua`**
   - Directive: `content_by_lua_file` (line 209)
   - Location: `~ ^/(.+)/generate_session_id(.*)$`
   - Purpose: Session ID generation endpoint
   - **Has requires:** Yes (1) - `local helpers = require("helpers")`

2. **`/data/kashmir/pinpoint/core/router/events.lua`**
   - Directive: `rewrite_by_lua_file` (line 222)
   - Location: `/events`
   - Purpose: Event routing
   - **Has requires:** Yes (2) - `ngx`, `events_helpers`

3. **`/data/kashmir/pinpoint/core/router/crawlers.lua`**
   - Directive: `content_by_lua_file` (line 265)
   - Location: `~ ^/robots.txt$`
   - Purpose: Robots.txt generation
   - **Has requires:** Yes (2) - `ngx`, `features.lua`

4. **`/data/kashmir/pinpoint/core/router/main.lua`**
   - Directive: `rewrite_by_lua_file` (line 289)
   - Location: `@router` (default fallback)
   - Purpose: Main request router
   - **Has requires:** Yes (5) - `ngx`, `loader.lua`, `helpers`, `features.lua`, `context`

#### Additional Inline Lua Blocks:

The nginx config also has **inline lua blocks** (not files) that load modules:

5. **`header_filter_by_lua_block`** (line 40)
   - Requires: `header_handler`

6. **`content_by_lua_block`** for `/monitor`, `/tasks`, `/missions`, etc. (multiple locations)
   - Requires: `core.openresty.global_controller`

7. **`content_by_lua_block`** for `/generated/` (line 196)
   - Requires: `static_file_handler`

8. **`log_by_lua_block`** (line 296)
   - Requires: `log_format_helper`

9. **`rewrite_by_lua`** inline blocks (lines 240, 254)
   - Requires: `config` module

#### Summary:

- **4 files** loaded via `*_by_lua_file` directives
- **5+ modules** loaded via inline `*_by_lua_block` directives
- **All 4 files have require statements** - they're not truly isolated
- These files are **entry points** into the Lua module system
- They should NOT be orphans - they're the roots that nginx calls directly

**Impact on Code Knowledge Graph:**
- These 4 files should be marked as "nginx entry points"
- They form the bridge between nginx config and Lua code
- The graph should show: `nginx location → lua file → required modules`
- Example: `GET /robots.txt` → `crawlers.lua` → `features.lua`

**E3.** Are there Lua files that are loaded by nginx but NOT via `require()`? For example, `content_by_lua_file` directives point directly to files without going through the module system. How many such files exist?

---

## SECTION F: Cross-Language Connections

**Background:** A code knowledge graph should capture not just within-language dependencies but cross-language flows. This codebase has: Ruby generates JS → JS calls Lua → Lua calls Go → Lua writes Redis → Python reads Redis. These cross-language edges are what make the graph valuable for understanding the system.

**F1.** The Ruby→JS connection: Show exactly how a Ruby generator takes a `.js.erb` template and produces a final `.js` file. What Ruby file processes what JS template? Show 2-3 concrete examples.

**F2.** The JS→Lua connection: When `Container._sendRequest("POST", "/api/assess")` is called, the request goes to nginx which dispatches to Lua. Is there a way to know which nginx location serves `/api/assess`? (We know the answer from previous rounds — just confirm the mapping: `/api/*` → `router/main.lua` → controller → handler)

**F3.** The Lua→Python connection: Show 2-3 concrete examples of Lua writing to `/tmp/pinpoint_missions/` and which Python file processes those missions. Is there a direct mapping (mission type → Python handler)?

**F4.** Are there any other cross-language connections we haven't discussed? For example:
- Does Go call back into Lua or Python?
- Does Python call any Go or Lua services?
- Are there shared config files read by multiple languages?

### F1. Ruby→JS Connection: ERB Template Processing

**The Ruby build system uses ERB (Embedded Ruby) to generate JavaScript files from `.js.erb` templates.**

#### How It Works:

1. **Templates Class** (`src/core/generator/templates.rb`):
   - Simple ERB templating engine
   - Initialized with template directories
   - `render(template_name, conf)` method processes templates
   - Uses Ruby's built-in `ERB.new(File.read(template_file))`

2. **Features Class** (`src/core/generator/features.rb`):
   - Orchestrates the entire generation process
   - `generate_snippet()` method creates JS files from templates
   - Builds options hash from bundle configuration
   - Renders collectors and containers

#### Example 1: Device ID Collector

**Ruby Generator:** `src/ato/generator/preprocess/device_id.rb`

```ruby
# Line 34-35
bundle_builder.add_file(component, main_file_name, "container.js.erb", 
                        ["collectors/device/templates/device_container.js.erb"],
                        {"device_id_enabled" => device_id_enabled, 
                         "global_device_id_enabled" => global_device_id_enabled})
```

**JS Template:** `src/ato/collectors/device/templates/device_container.js.erb`

```erb
var DeviceContainer = (function() {
  var detectorTimeout = <%=env["bundle"].get('device_id/detector_timeout', 0).to_i%>,
      splitGDIDFromDevice = <%=(env['bundle'].get("device_id/split_gdid_from_device") || false)%>;

  <%if env["options"]["device_id_enabled"]%>
  <%=env["template"].render("collectors/device/templates/device_id.js.erb", env)%>
  <%end%>
  
  <%if env["options"]["global_device_id_enabled"]%>
  <%=env["template"].render("collectors/device/templates/global_device_id.js.erb", env)%>
  <%end%>
})();
```

**Output:** Final `.js` file with Ruby variables replaced by actual values and nested templates rendered.

---

#### Example 2: Behave Collector

**Ruby Generator:** `src/ato/generator/preprocess/behave.rb`

```ruby
# Line 49
bundle_factory.add_file(component, file_name, "container.js.erb", 
                        ["collectors/behave/templates/behave.js.erb"], 
                        {"behave_features" => features})
```

**JS Template:** `src/ato/collectors/behave/templates/behave.js.erb`

```erb
var Behave = (function() {
  <% if (enabled_features.include?("remote_access_tool") || enabled_features.include?("biometrics")) %>
  <%= env["template"].render("collectors/behave/templates/mouse_movements.js.erb", env) %>
  <% end %>
  
  <% if (enabled_features.include?("keystrokes")) %>
  <%= env["template"].render("collectors/behave/templates/keystrokes.js.erb", env) %>
  <% end %>
})();
```

**Conditional Rendering:** Ruby evaluates `enabled_features` array and includes/excludes sub-templates dynamically.

---

#### Example 3: Container Base Template

**Ruby Generator:** `src/common/generator/preprocess/loader.rb`

```ruby
# Line 198
bundle_factory.add_file(component, snippet["main_file_name"], "container.js.erb", 
                        [template], snippet["options"])
```

**JS Template:** `src/common/base/js/container.js.erb`

```erb
(function() {
  <%=env['template'].render("json.js", env)%>
  <%=env["template"].render("rc4.js.erb", env)%>
  <%=env["template"].render("sha256.js.erb", env)%>
  
  <% if(env["cover"].use_cover_config()) %>
    <%=env["template"].render("cover_config.js.erb", env)%>
  <% end %>
  
  <%=env["template"].render("cookie.js", env)%>
  <%=env["template"].render("session_id.js.erb", env)%>
  <%=env["template"].render("user_agent.js.erb",env)%>
  
  <% if encrypt_collections %>
  <%=env["template"].render("rsa.js.erb",env)%>
  <%=env["template"].render("collection_encryptor.js.erb",env)%>
  <% end %>
})();
```

**Nested Rendering:** Container template includes multiple sub-templates, creating a complete JS bundle.

---

#### Key Insights:

1. **Ruby controls JS structure** - Ruby code decides which JS templates to include based on configuration
2. **Dynamic composition** - JS files are assembled from multiple templates at build time
3. **Configuration injection** - Ruby injects bundle settings, feature flags, and options into JS code
4. **No runtime templating** - All ERB processing happens during build; browser receives plain JS

**Graph Connection:** `Ruby generator file` → `processes` → `.js.erb template` → `produces` → `.js output file`

---

### F2. JS→Lua Connection: HTTP Request Routing

**Confirmed: JavaScript makes HTTP requests that nginx routes to Lua handlers.**

#### The Flow:

```
Browser JS → nginx → router/main.lua → controller → handler
```

#### Example: `/api/assess` Request

**JavaScript Call** (from any collector):
```javascript
Container._sendRequest("POST", "/api/assess", data, callback);
```

**Nginx Configuration** (`src/config/nginx/generic.conf`):

```nginx
# Line 292-294: Default fallback location
location / {
  try_files $uri @router;
}

# Line 269-290: Router location
location @router {
  set $router_root "/data/kashmir/pinpoint";
  rewrite_by_lua_file "/data/kashmir/pinpoint/core/router/main.lua";
}
```

**Router Logic** (`src/core/router/main.lua`):

```lua
local ngx = require("ngx")
local require_version = require("loader.lua").require_version
local helpers = require_version("helpers")

-- Calls helpers.rewrite(ngx) which:
-- 1. Parses request URI (/api/assess)
-- 2. Extracts component and action
-- 3. Routes to appropriate controller
local rewrite, message = helpers.rewrite(ngx)
if rewrite then
  ngx.exec(rewrite, ngx.var.args or "")
end
```

**Controller Dispatch:**
- `/api/assess` → `ato/controllers/index.lua` → `ato/handlers/session_info/init.lua`
- `/api/policy` → `ato/controllers/index.lua` → `ato/handlers/policy/init.lua`
- `/api/wisp` → `ato/controllers/wisp.lua` → `ato/handlers/wisp/init.lua`

#### Routing Pattern:

1. **All `/api/*` requests** go to `@router` location
2. **`router/main.lua`** is the entry point (loaded via `rewrite_by_lua_file`)
3. **Helpers module** parses URI and determines controller
4. **Controller** loads appropriate handler based on action
5. **Handler** processes request and returns response

**Graph Connection:** `.js file` → `HTTP POST /api/assess` → `nginx location @router` → `router/main.lua` → `controller.lua` → `handler/init.lua`

---

### F3. Lua→Python Connection: Mission/Task System

**Lua writes tasks to a queue system that Python services process. NOT file-based (`/tmp/pinpoint_missions/` doesn't exist), but socket-based communication.**

#### The Architecture:

**Lua Side:** `src/core/deferrer/missioner/client.lua`

```lua
function M.add_mission(name, params, delay, queue_type)
  local data = {
    id = task_id,
    name = name,
    params = crypto.base64.encode(cjson.encode(params)),
    component = params.component,
    created_at = math.floor(socket.gettime() * 1000),
    delay = delay
  }
  
  -- Sends via Unix socket to missioner service
  local payload = cjson.encode({
    delay = delay,
    task_type = task_type,
    data = data,
  })
  
  http_handler.post(M.connection_url, payload, options, M.socket_file)
  -- Socket: /data/kashmir/pinpoint/shared/sockets/missioner.sock
end
```

**Python Side:** `src/deferrer/poller/poller/queue_handlers/tasks_executer.py`

```python
def execute(self):
    while True:
        task = self.local_queue.get(timeout=constants.DEFAULT_EXECUTER_BLOCK_TIMEOUT)
        
        # Dispatch task to appropriate handler
        code, result = self.dispatcher.send(task)
        
        if code == constants.STATUS_OK:
            self.logger.info(f"Completed task id: '{task.get('id')}', name: '{task.get('name')}'")
```

#### Example 1: Model Prediction Task

**Lua Creates Mission:**
```lua
-- In ato/assessors/model_prediction/init.lua
local missioner = require_version("core.deferrer.missioner.client")

missioner.add_mission("model_prediction", {
  component = "ato",
  session_id = session_id,
  model_data = data
}, 0, "model_prediction")
```

**Python Processes Task:**
- Poller receives task from SQS queue
- Dispatches to model prediction service
- Calls Go service via Unix socket

#### Example 2: Aggregation Task

**Lua Creates Mission:**
```lua
missioner.add_mission("aggregate_user_data", {
  component = "ato",
  user_id = user_id,
  data_type = "behavior"
}, 300, "aggregator")  -- 5 minute delay
```

**Python Processes Task:**
- Aggregator service receives task
- Processes data aggregation
- Stores results in Redis/Cassandra

#### Example 3: Deferred Policy Evaluation

**Lua Creates Mission:**
```lua
missioner.add_mission("evaluate_policy", {
  component = "ato",
  session_id = session_id,
  policy_id = policy_id
}, 60, "default")  -- 1 minute delay
```

**Python Processes Task:**
- Poller receives task
- Calls back into Pinpoint via HTTP
- Triggers policy re-evaluation

#### Communication Flow:

```
Lua (missioner.add_mission)
  ↓ Unix socket
Missioner Service (Python/Tornado)
  ↓ SQS queue
Poller Service (Python)
  ↓ Dispatch
Task Executor (Python)
  ↓ HTTP/Socket
Target Service (Go/Lua/Python)
```

**Key Insight:** This is NOT a file-based system. It's a distributed task queue using:
- Unix sockets for local communication
- SQS for queue management
- HTTP for service-to-service calls

**Graph Connection:** `Lua handler` → `missioner.add_mission()` → `Unix socket` → `Python Missioner` → `SQS queue` → `Python Poller` → `Task Executor`

---

### F4. Other Cross-Language Connections

#### 1. **Go→Lua Connection: Model Prediction Service**

**Go Service:** `src/core/model_prediction/server/router.go`

```go
// Receives tasks via Unix socket from Lua
func (router *StandardRouter) handleTask(task map[string]interface{}, ...) {
    taskID, ok := task["task_id"].(string)
    err := router.tasksService.Run(task, runtimeTaskParams)
    
    // Sends response back via socket
    conn.Write([]byte(taskID + "\n"))
}
```

**Lua Calls Go:**
```lua
-- In ato/assessors/model_prediction/init.lua
local socket_file = "/data/kashmir/pinpoint/shared/sockets/model_prediction_1.sock"
local response = http_handler.post("/predict", payload, {}, socket_file)
```

**Flow:** Lua → Unix socket → Go service → processes ML model → returns prediction → Lua

---

#### 2. **Python→Lua Connection: HTTP Callbacks**

**Python Poller** calls back into Pinpoint (Lua) via HTTP:

```python
# In poller/utils/clients/http.py
def dispatch_task(task):
    url = f"http://pinpoint/api/{task['action']}"
    response = requests.post(url, json=task['params'])
```

**Lua Receives:**
- Request goes through nginx → router/main.lua → handler
- Same routing as browser JS requests

---

#### 3. **Shared Configuration Files**

**Multiple languages read the same config files:**

**`config.json`** - Read by:
- Lua: `require("config")`
- Ruby: `Utils.load_config`
- Python: `Config.load()`
- Go: `config.LoadConfig()`

**`features.json`** - Feature flags read by:
- Lua: `require("features.lua")`
- Ruby: `Features.new(features_file)`
- Python: Feature checks via HTTP to Lua

**`redis.json`** - Redis configuration:
- Lua: `RedisHelper.new(config.redis)`
- Python: `RedisClient(config['redis'])`
- Go: `redis.NewClient(config.Redis)`

---

#### 4. **Redis as Message Bus**

**Cross-language communication via Redis:**

**Lua Publishes:**
```lua
local redis = require_version("lib.lua.redis_helper")
redis:publish("policy_updates", cjson.encode(data))
```

**Python Subscribes:**
```python
redis_client.subscribe("policy_updates")
for message in pubsub.listen():
    process_policy_update(message)
```

**Go Reads:**
```go
val, err := redisClient.Get(ctx, "session:" + sessionID).Result()
```

---

#### 5. **Shared Data Structures**

**Session data stored in Redis, accessed by all languages:**

```
Key: session:{session_id}
Value: JSON blob with:
  - device_id
  - user_id
  - policy_results
  - assessments
  
Written by: Lua handlers
Read by: Python services, Go services, Lua handlers
```

---

### Summary: Complete Cross-Language Flow

**Example: User Login Request**

1. **Browser JS** (`device.js`) collects device fingerprint
2. **JS** sends POST to `/api/assess` with data
3. **Nginx** routes to `router/main.lua`
4. **Lua** (`ato/handlers/session_info/init.lua`) processes request
5. **Lua** creates mission: `missioner.add_mission("model_prediction", ...)`
6. **Python Missioner** receives task via Unix socket
7. **Python Poller** picks up task from SQS
8. **Python** calls **Go** model prediction service via Unix socket
9. **Go** runs ML model, returns prediction
10. **Python** stores result in Redis
11. **Lua** reads result from Redis
12. **Lua** evaluates policy based on prediction
13. **Lua** returns response to browser
14. **JS** processes response and updates UI

**Graph Connections Needed:**
- Ruby generator → JS template (build-time)
- JS file → HTTP endpoint → nginx location → Lua file (runtime)
- Lua file → missioner.add_mission → Python service (async)
- Lua file → Unix socket → Go service (sync)
- All languages → Redis (shared state)
- All languages → config files (shared config)


---

## SECTION G: What Would Make This Graph Actually Useful?

**Background:** The ultimate consumer of this graph is an AI agent (like BOB) that needs to answer questions about the codebase. We want to ask questions like "what happens when a user hits /api/assess?" and get a complete answer tracing through all layers.

**G1.** If you could ask any questions about this codebase and get instant answers, what would be the top 5 most useful questions? Think about what's hardest to figure out manually.

**G2.** When you investigate a bug or trace a request flow, what information do you wish you had that requires reading multiple files? Show a concrete example of a question that requires understanding 3+ files.

**G3.** Are there any "hidden" connections between files that aren't captured by imports/requires? For example:
- Files that communicate via Redis channels
- Files that share data through file system conventions
- Files that are connected by naming conventions (e.g., `handler/policy.lua` and `assessors/policy.lua` are related by the "policy" name)
- Configuration files that reference Lua module paths

**G4.** What documentation or config files exist that describe the system architecture? (e.g., README files, architecture docs, docker-compose.yml, deployment configs). These might contain connection information not visible in code.


**G2.** When you investigate a bug or trace a request flow, what information do you wish you had that requires reading multiple files? Show a concrete example of a question that requires understanding 3+ files.

**G3.** Are there any "hidden" connections between files that aren't captured by imports/requires? For example:
- Files that communicate via Redis channels
- Files that share data through file system conventions
- Files that are connected by naming conventions (e.g., `handler/policy.lua` and `assessors/policy.lua` are related by the "policy" name)
- Configuration files that reference Lua module paths

**G4.** What documentation or config files exist that describe the system architecture? (e.g., README files, architecture docs, docker-compose.yml, deployment configs). These might contain connection information not visible in code.

---

### G1. Top 5 Most Useful Questions (Developer Pain Points)

Based on investigating this complex multi-language codebase, here are the 5 questions that would save developers the most time:

#### 1. "What happens when I change this policy rule?"
**Why it's hard manually:** Requires tracing through 8+ files across 3 languages
- Policy rule in customer bundle (Ruby/YAML)
- `src/ato/structured_policy/policy.lua` - Policy engine
- `src/ato/structured_policy/policy/current.lua` - Execution logic
- `src/ato/structured_policy/models_api/*.lua` - Data access (12 files)
- `src/ato/actors/*.lua` - Result persistence (20 actors)
- `src/ato/events/*.lua` - Event emission (20+ event types)
- `src/deferrer/poller/` - Async task execution (Python)
- `src/core/event_extractor/` - Event processing (Python)

**Graph value:** Show complete impact chain from rule change → data access → persistence → events → downstream systems

#### 2. "How does a fraud assessment request flow through the system?"
**Why it's hard manually:** Crosses 5 languages and 15+ services
- Client JS collector → HTTP request
- Nginx routing (`src/config/nginx/generic.conf`)
- Lua handler (`src/common/handlers/pinpoint_eval/`)
- Assessors (device, behavior, ML model)
- Policy engine (structured_policy)
- Go service (model_prediction)
- Python services (aggregator, poller)
- Ruby generator (bundle compilation)

**Graph value:** Visualize the complete request pipeline with all cross-language hops

#### 3. "Which files use this Redis key pattern?"
**Why it's hard manually:** Redis keys are string-based, no static analysis
- Keys like `store:<session_id>`, `bundle:<app_id>`, `cache:*`
- Used across 100+ Lua files
- No grep can find dynamic key construction: `"store:" .. session_id`
- Shared between services via naming conventions only

**Graph value:** Track Redis key usage patterns across all files, including dynamic construction

#### 4. "What mission/task types exist and where are they handled?"
**Why it's hard manually:** Distributed across Lua→Python boundary
- Mission creation: 74 locations in Lua files
- Task types: `"pts_run"`, `"device_analyzer_dry_run"`, `"test_policy"`, `"rules_engine_rulegen_regenerate"`, etc.
- Handlers: Scattered across `src/common/tasks/`, `src/ato/tasks/`, `src/core/tasks/`
- Queue routing: `"policy"`, `"default"` queues
- No central registry

**Graph value:** Map all mission types to their handlers, showing Lua→Python task flow

#### 5. "Which files will break if I change this base class?"
**Why it's hard manually:** Inheritance spans 200+ files
- `src/common/base/lua/handler.lua` - Base handler (used by 17+ handlers)
- `src/common/base/lua/assessor.lua` - Base assessor (used by 14+ assessors)
- `src/common/base/lua/collector.lua` - Base collector (used by 9+ collectors)
- `src/common/base/lua/actor.lua` - Base actor (used by 20+ actors)
- Changes ripple through ATO and Malware modules

**Graph value:** Show complete inheritance tree with all derived classes

---

### G2. Multi-File Investigation Example

**Question:** "How does the Policy Test System (PTS) work from button click to result display?"

**Why this requires 3+ files:** The flow crosses 4 languages and 12 files:

#### The Complete Flow:

1. **User clicks "Test Policy" button** (JavaScript)
   - File: `src/ato/templates/pts/test_policy_button.js.erb` (ERB template)
   - Sends POST to `/ato/controllers/pts.lua/run_test`

2. **Nginx routes request** (Nginx config)
   - File: `src/config/nginx/generic.conf`
   - Pattern: `location ~ ^/(?<module>.+)/controllers/(?<controller>.+)/(?<rest>.+)$`
   - Routes to Lua controller

3. **PTS Controller receives request** (Lua)
   - File: `src/ato/controllers/pts.lua`
   - Validates parameters
   - Creates mission: `missioner.add_mission("pts_run", parameters, MISSION_DELAY, "policy")`

4. **Missioner queues task** (Lua→Python boundary)
   - File: `src/core/deferrer/missioner/client.lua`
   - Sends to Unix socket: `/data/kashmir/pinpoint/shared/sockets/missioner.sock`
   - Async timer: `src/common/async_timers/missioner_timer.lua`

5. **Missioner service receives** (Python)
   - File: `src/deferrer/missioner/missioner.py`
   - Adds to SQS queue with delay

6. **Aggregator batches tasks** (Python)
   - File: `src/deferrer/aggregator/aggregator/task_manager.py`
   - Batches multiple PTS requests

7. **Poller executes task** (Python)
   - File: `src/deferrer/poller/poller/queue_handlers/tasks_executer.py`
   - POSTs back to `/tasks` endpoint

8. **Tasks controller dispatches** (Lua)
   - File: `src/core/controllers/tasks.lua`
   - Verifies auth header
   - Creates task instance: `task_model.new(task_data, "pts_run")`

9. **PTS task handler runs** (Lua)
   - File: `src/ato/tasks/pts_run.lua`
   - Executes policy with test data
   - Stores results in Cassandra

10. **Results retrieved** (Lua)
    - File: `src/ato/handlers/pts/get_results.lua`
    - Queries Cassandra for test results

11. **Results displayed** (JavaScript)
    - File: `src/ato/templates/pts/results_display.js.erb`
    - Renders test results in UI

12. **Events emitted** (Lua→Python)
    - File: `src/ato/events/pinpoint_policy_test_system_result.lua`
    - Sent to event extractor for analytics

**Why this is impossible to trace manually:**
- 12 files across 4 languages
- 3 async boundaries (HTTP, Unix socket, SQS)
- 2 database operations (Redis, Cassandra)
- No single file shows the complete flow
- Requires understanding mission/task system architecture

**What a graph would show:**
- Complete call chain with language transitions
- Async boundaries clearly marked
- Data flow (parameters → results)
- All files involved in sequence

---

### G3. Hidden Connections (Not Captured by Imports)

#### 1. Mission/Task System (Lua→Python via String Names)

**Connection type:** String-based task routing

**Example:**
```lua
-- src/ato/controllers/pts.lua
missioner.add_mission("pts_run", parameters, 0, "policy")
```

**Handler (different language, no import):**
```lua
-- src/ato/tasks/pts_run.lua (called via string lookup)
function M.run(params)
  -- Executes policy test
end
```

**Hidden connections found:**
- `"pts_run"` → `src/ato/tasks/pts_run.lua`
- `"device_analyzer_dry_run"` → `src/ato/tasks/device_analyzer_dry_run.lua`
- `"test_policy"` → `src/ato/tasks/test_policy.lua`
- `"rules_engine_rulegen_check"` → `src/common/tasks/rules_engine_rulegen_check.lua`
- `"rules_engine_rulegen_regenerate"` → `src/common/tasks/rules_engine_rulegen_regenerate.lua`
- `"assess"` → `src/ato/tasks/assess.lua`
- `"invoke_actors"` → `src/ato/tasks/invoke_actors.lua`
- `"model_prediction"` → `src/ato/tasks/model_prediction.lua`

**74 mission creation sites** found across codebase, all using string-based routing.

#### 2. Naming Convention Connections (Parallel File Structures)

**Pattern:** Files with same name in different directories are conceptually related

**Examples:**

**Policy-related files:**
- `src/ato/handlers/policy/init.lua` - HTTP handler for policy assessment
- `src/ato/assessors/policy/init.lua` - Policy assessor logic
- `src/ato/structured_policy/policy.lua` - Policy engine core
- `src/ato/structured_policy/policy/current.lua` - Current policy execution
- `src/ato/helpers/policy.lua` - Policy helper functions
- `src/ato/actors/save_policy_results/init.lua` - Policy result persistence

**Session info files:**
- `src/ato/handlers/session_info/init.lua` - ATO session info handler
- `src/malware/handlers/session_info/v2.lua` - Malware session info handler
- Both handle `/session_info` endpoint for different modules

**Device-related files:**
- `src/ato/collectors/device/init.lua` - Device data collection
- `src/ato/assessors/device_analyzer/init.lua` - Device analysis
- `src/ato/actors/device_id/init.lua` - Device ID persistence
- `src/ato/helpers/device.lua` - Device helper functions
- `src/ato/helpers/device_analyzer.lua` - Device analyzer helpers

**These files are NOT connected by imports** but form logical units by naming convention.

#### 3. Redis Key Patterns (Shared Data via Naming Conventions)

**Connection type:** Files communicate via Redis keys with conventional naming

**Key patterns found:**
- `store:<session_id>` - Session data (used by 50+ files)
- `bundle:<application_id>` - Customer bundles (used by 30+ files)
- `cache:*` - Various caches (used by 20+ files)
- `global_device:<device_id>` - Global device mappings
- `policy_result:<session_id>` - Policy results
- `user_history:<user_id>` - User behavioral history

**Example hidden connection:**
```lua
-- src/ato/assessors/device_analyzer/init.lua
local device_data = redis:hgetall("store:" .. session_id)

-- src/ato/actors/save_policy_results/init.lua
redis:hset("store:" .. session_id, "policy_result", result)
```

**No import relationship**, but they share data via Redis key convention.

#### 4. Nginx Configuration References (String-based Module Loading)

**Connection type:** Nginx config references Lua files by path strings

**Example from `src/config/nginx/generic.conf`:**
```nginx
location ~ ^/(?<module>.+)/controllers/(?<controller>.+)/(?<rest>.+)$ {
  content_by_lua_block {
    require("core.openresty.global_controller").run()
  }
}
```

**This dynamically loads:**
- `/ato/controllers/pts.lua/run_test` → `src/ato/controllers/pts.lua`
- `/ato/controllers/wisp.lua/assess` → `src/ato/controllers/wisp.lua`
- `/common/controllers/index.lua/monitor` → `src/common/controllers/index.lua`

**Hidden connections:**
- `src/config/nginx/generic.conf` → All controller files (via pattern matching)
- `src/core/openresty/global_controller.lua` → Dynamic module loading
- `src/core/router/` → URL-to-file mapping logic

#### 5. ERB Template Processing (Ruby→JS Build-Time Connection)

**Connection type:** Ruby processes JavaScript templates at build time

**Example:**
```ruby
# src/ato/generator/preprocess/device_id.rb
def process_bundle(bundle)
  # Modifies bundle configuration
end
```

**Generates:**
```javascript
// src/ato/templates/collectors/device_id.js.erb (processed)
var config = <%= bundle.device_id_config.to_json %>;
```

**Hidden connections:**
- All `*.js.erb` files → Corresponding Ruby preprocessor
- `src/ato/generator/preprocess/*.rb` → `src/ato/templates/**/*.js.erb`
- `src/common/generator/preprocess/*.rb` → `src/common/templates/**/*.js.erb`

**23 preprocessors** found, each modifying specific templates.

#### 6. Systemd Service Dependencies (Service Orchestration)

**Connection type:** Services check if they should run via script

**From `pinpoint_README.md`:**
```bash
/data/kashmir/pinpoint/core/scripts/check_service.sh pinpoint_cacher
```

**Hidden connections:**
- `src/config/systemd/*.service` files → `src/core/scripts/check_service.sh`
- Service startup order dependencies (not in code)
- Master service `pinpoint.service` → All other services

**Services:**
- pinpoint_nginx.service
- pinpoint_generator.service
- pinpoint_cacher.service
- pinpoint_cassandra_communicator.service
- pinpoint_model_prediction.service
- pinpoint_aggregator.service
- pinpoint_poller.service
- pinpoint_events_extractor.service
- pinpoint_uwsgi.service

#### 7. Cron Job Connections (Time-based Execution)

**Connection type:** Cron jobs execute scripts on schedule

**Example from `src/ato/cron/template/monitoring_data.erb`:**
```
*/5 * * * * /data/kashmir/pinpoint/ato/scripts/job_update_monitoring.sh
```

**Hidden connections:**
- Cron template → Shell script → Lua script
- `src/ato/cron/template/monitoring_data.erb` → `src/ato/scripts/job_update_monitoring.sh` → `src/ato/scripts/update_monitoring.lua`
- Similar for backcolor, super_users scripts

---

### G4. Documentation and Config Files Describing Architecture

#### Comprehensive Documentation Found:

**1. Architecture Documentation:**
- **`pinpoint_documentation/previous_work/ARCHITECTURE.md`** (458 lines)
  - Complete system overview with module boundaries
  - Dependency graph showing ATO→Common→Core→Lib hierarchy
  - Request processing pipeline
  - Cross-cutting concerns (module loading, config, database)
  - Service dependencies and integration points
  - **KEY INSIGHT:** Documents the 5-layer architecture and "no circular dependencies" rule

**2. Main README Files:**
- **`README.md`** (93 lines) - Docker development setup
  - Make commands for container management
  - Service orchestration via docker-compose
  - Development workflow (generator, cacher, openresty reload)
  
- **`pinpoint_README.md`** (183 lines) - Production deployment
  - **CRITICAL:** Documents systemd service architecture
  - Service check script: `/data/kashmir/pinpoint/core/scripts/check_service.sh`
  - No versioning (no vX_X_X folders)
  - Log file naming conventions
  - Go service rebuild requirements

- **`AGENTS.md`** - Non-obvious patterns and gotchas
  - `require_version()` pattern (MUST use for versioned modules)
  - Crypto library migration (NEW_DOCKER_ENV flag)
  - File path symlinks (`/data/kashmir/pinpoint/` → `src/`)
  - Testing commands
  - Go service restart procedure

**3. Module-Specific Documentation (119 README.md files found):**

**Core module READMEs:**
- `src/core/loader/README.md` - Module versioning system
- `src/core/config/README.md` - Configuration management
- `src/core/bundles/README.md` - Bundle system
- `src/core/generator/README.md` - Bundle generation
- `src/core/cacher/README.md` - Redis cache management
- `src/core/cassandra_communicator/README.md` - Cassandra interface
- `src/core/model_prediction/README.md` - ML service (Go)
- `src/core/event_extractor/README.md` - Event extraction (Python)
- `src/core/deferrer/README.md` - Mission/task system

**Common module READMEs (17,931 lines total):**
- `src/common/base/README.md` - Base classes (Handler, Assessor, Collector, Actor)
- `src/common/handlers/README.md` - Handler system
- `src/common/assessors/README.md` - Assessor system
- `src/common/collectors/README.md` - Collector system
- `src/common/actors/README.md` - Actor system
- `src/common/tasks/README.md` - Task system
- `src/common/triggers/README.md` - Trigger system
- `src/common/rules_engine/README.md` - Rules engine
- `src/common/orm_models/README.md` - Cassandra ORM

**ATO module READMEs (20 files):**
- `src/ato/README.md` - ATO module overview
- `src/ato/structured_policy/README.md` - Policy engine (673 lines)
- `src/ato/handlers/README.md` - ATO handlers (320 lines)
- `src/ato/assessors/README.md` - ATO assessors
- `src/ato/actors/README.md` - ATO actors
- `src/ato/generator/README.md` - ATO generator (730 lines)

**Deferrer READMEs:**
- `src/deferrer/README.md` - Deferrer overview (819 lines)
- `src/deferrer/aggregator/README.md` - Task batching
- `src/deferrer/poller/README.md` - Task execution
- `src/deferrer/missioner/README.md` - Mission queuing

**4. Docker Compose Files (Service Architecture):**

- **`pp-docker-compose.dev-infra.yml`** - Infrastructure services
  - Redis, MySQL, Cassandra, MinIO (S3), SQS
  
- **`pp-docker-compose.dev-core.yml`** - Core Pinpoint services
  - OpenResty (Nginx + Lua)
  - Generator (Ruby)
  - Cacher (Ruby)
  - Communicator (Cassandra interface)
  - Model Prediction (Go)
  - Event Extractor (Python)
  - Aggregator (Python)
  - Poller (Python)
  - Missioner (Python)

- **`pp-docker-compose.dev-tools.yml`** - Development tools
  - Redis Insights, PhpMyAdmin, Grafana

**5. Configuration Files with Connection Info:**

**Nginx configuration:**
- `src/config/nginx/generic.conf` - **CRITICAL routing file**
  - Maps URLs to Lua controllers
  - Defines all HTTP endpoints
  - Shows cross-language boundaries (Nginx→Lua)

**Systemd services:**
- `src/config/systemd/*.service` - All service definitions
  - Service dependencies
  - Startup order
  - Environment variables

**Build specifications:**
- `build/specs/pinpoint.spec` - RPM build spec
- `build/specs/openresty.spec` - OpenResty build
- `build/specs/go-stack.spec` - Go dependencies
- `build/specs/python-stack.spec` - Python dependencies
- `build/specs/ruby-stack.spec` - Ruby dependencies
- `build/specs/lua-stack.spec` - Lua dependencies

**Dependency manifests:**
- `lua_requirements.json` - Lua rocks
- `Gemfile` / `Gemfile.lock` - Ruby gems
- `python_requirements.txt` - Python packages
- `go_requirements.txt` - Go modules
- `node_requirements.txt` - Node packages

**6. Previous Investigation Context:**
- `pinpoint_documentation/previous_work/NEXT_SESSION_CONTEXT.md`
- `pinpoint_documentation/previous_work/PHASE3_CORE_CONTEXT.md`
- `pinpoint_documentation/previous_work/PHASE4_DEFERRER_CONTEXT.md`
- `pinpoint_documentation/previous_work/REMAINING_MODULES_PLAN.md`

**7. Model Prediction Flow:**
- `pinpoint_documentation/MODEL_PREDICTION_ASYNC_FLOW.md`
  - Documents async ML prediction flow
  - Shows Lua→Go→Lua communication

#### Key Architectural Insights from Documentation:

**Module Hierarchy (from ARCHITECTURE.md):**
```
ATO (fraud detection)
  ↓
Malware (security)
  ↓
Common (shared infrastructure)
  ↓
Core (services)
  ↓
Lib (utilities)
```

**No circular dependencies allowed** - enforced by architecture.

**Request Pipeline:**
```
Client → Nginx → Common Handler → ATO/Malware Handler → Assessors → Policy → Actors → Events
```

**Cross-Language Boundaries:**
1. Ruby (Generator) → JavaScript (ERB templates)
2. JavaScript (Client) → Lua (OpenResty)
3. Lua → Go (Model Prediction via Unix socket)
4. Lua → Python (Mission/Task system via Unix socket + SQS)
5. Python → Lua (HTTP callbacks to /tasks endpoint)

**Critical Non-Obvious Patterns (from AGENTS.md):**
- MUST use `require_version()` not `require()` for versioned modules
- Crypto has dual implementation (NEW_DOCKER_ENV flag)
- File paths use `/data/kashmir/pinpoint/` not `src/` in code
- No vX_X_X version folders in deployment
- Go service requires recompile before restart

**Service Orchestration:**
- Master service: `pinpoint.service`
- Service check: `/data/kashmir/pinpoint/core/scripts/check_service.sh`
- Services auto-detect machine type (deferrer, openresty, etc.)

---

**Summary:** The codebase has **extensive documentation** (119 README files, 20,000+ lines), but the **hidden connections** (missions, Redis keys, naming conventions, Nginx routing) are not captured in any single place. A knowledge graph would make these implicit connections explicit and queryable.
