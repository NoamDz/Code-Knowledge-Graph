# BOB Investigation — Round 5: Section A - Ruby Deep Dive

## SECTION A ANSWERS: Ruby Deep Dive

### A1. Ruby Directory Structure (First 2-3 Levels with File Counts)

**Total Ruby Files: 151**

```
src/
├── ato/
│   └── generator/
│       ├── preprocess/          [22 files]
│       └── tasks.rb             [1 file]
│
├── common/
│   └── generator/
│       └── preprocess/          [30 files]
│
├── core/
│   ├── bundles/ruby/            [1 file]
│   ├── generator/               [23 files]
│   │   ├── clients/             [3 files]
│   │   ├── common_items/        [4 files]
│   │   ├── events/              [2 files]
│   │   ├── models/              [2 files]
│   │   └── to_lua/              [3 files]
│   ├── multi_events_uploader/   [14 files]
│   │   ├── bin/                 [1 file]
│   │   ├── lib/                 [7 files]
│   │   │   └── clients/         [4 files]
│   │   └── spec/                [3 files]
│   ├── pii-cleaner/lib/         [3 files]
│   ├── scripts/                 [2 files]
│   ├── unitests_automation/     [1 file]
│   └── utils/ruby/              [14 files]
│       └── redis_lists/         [3 files]
│
├── lib/
│   ├── generator/preprocess/    [2 files]
│   ├── obfuscation/             [8 files]
│   │   ├── arbitrary_code/      [2 files]
│   │   └── templates/           [3 files]
│   └── ruby/                    [1 file]
│
└── malware/
    └── generator/
        ├── preprocess/          [11 files]
        └── tasks.rb             [1 file]
```

**Distribution by Top-Level Directory:**
- `src/common/generator/preprocess/`: 30 files (20%)
- `src/core/generator/`: 23 files (15%)
- `src/ato/generator/preprocess/`: 22 files (15%)
- `src/core/utils/ruby/`: 14 files (9%)
- `src/core/multi_events_uploader/`: 14 files (9%)
- `src/malware/generator/preprocess/`: 11 files (7%)
- `src/lib/obfuscation/`: 8 files (5%)
- Other directories: 29 files (20%)

---

### A2. Ruby File Categorization by Role

#### **1. Generator Preprocessors (63 files, 42%)**

**Purpose:** Transform bundle configurations before JavaScript generation

**ATO Preprocessors (22 files):**
- `src/ato/generator/preprocess/behave.rb` - Behavioral analysis features
- `src/ato/generator/preprocess/carboncopy.rb` - Carbon copy detection
- `src/ato/generator/preprocess/common_fields.rb` - Common field processing
- `src/ato/generator/preprocess/custom_fields.rb` - Custom field handling
- `src/ato/generator/preprocess/device_id.rb` - Device identification
- `src/ato/generator/preprocess/failed_login.rb` - Failed login tracking
- `src/ato/generator/preprocess/fraud_attributes.rb` - Fraud attribute processing
- `src/ato/generator/preprocess/global_device.rb` - Global device tracking
- `src/ato/generator/preprocess/groups.rb` - Group management
- `src/ato/generator/preprocess/ipp.rb` - IPP integration
- `src/ato/generator/preprocess/loopback_api.rb` - Loopback API
- `src/ato/generator/preprocess/mbb_profile.rb` - Mobile banking profile
- `src/ato/generator/preprocess/mobile_behave.rb` - Mobile behavior
- `src/ato/generator/preprocess/mobile_data.rb` - Mobile data processing
- `src/ato/generator/preprocess/model_prediction.rb` - ML model integration
- `src/ato/generator/preprocess/policy.rb` - Policy configuration
- `src/ato/generator/preprocess/rapport_detections_data.rb` - Rapport detection
- `src/ato/generator/preprocess/remote_access_detector.rb` - Remote access detection
- `src/ato/generator/preprocess/structured_policy.rb` - Structured policy
- `src/ato/generator/preprocess/user_flow.rb` - User flow tracking
- `src/ato/generator/preprocess/user_profile.rb` - User profile management
- `src/ato/generator/preprocess/wisp.rb` - WISP integration

**Common Preprocessors (30 files):**
- `src/common/generator/preprocess/_0_master_bundle.rb` - Master bundle handling
- `src/common/generator/preprocess/_1_diagnostic_snippet.rb` - Diagnostic snippet
- `src/common/generator/preprocess/aggregated_collects_with_retry.rb` - Collection retry logic
- `src/common/generator/preprocess/client_info.rb` - Client information
- `src/common/generator/preprocess/collectors_monitor.rb` - Collector monitoring
- `src/common/generator/preprocess/common_api.rb` - Common API
- `src/common/generator/preprocess/concat_base_hosts.rb` - Host concatenation
- `src/common/generator/preprocess/cookies.rb` - Cookie handling
- `src/common/generator/preprocess/customer_session_id.rb` - Session ID management
- `src/common/generator/preprocess/device_features.rb` - Device feature detection
- `src/common/generator/preprocess/dummy_snippet.rb` - Dummy snippet generation
- `src/common/generator/preprocess/embedding_uri.rb` - URI embedding
- `src/common/generator/preprocess/global_cookies.rb` - Global cookie handling
- `src/common/generator/preprocess/inheritance.rb` - Bundle inheritance
- `src/common/generator/preprocess/intelligent_snippet.rb` - Intelligent snippet
- `src/common/generator/preprocess/internal_event_mapping.rb` - Event mapping
- `src/common/generator/preprocess/legacy_jsonpi_support.rb` - Legacy JSONP support
- `src/common/generator/preprocess/loader.rb` - Loader snippet
- `src/common/generator/preprocess/loopback_api.rb` - Loopback API
- `src/common/generator/preprocess/monitoring.rb` - Monitoring features
- `src/common/generator/preprocess/multi_login_metadata.rb` - Multi-login metadata
- `src/common/generator/preprocess/pinpoint_eval.rb` - Pinpoint evaluation
- `src/common/generator/preprocess/provider_bundle.rb` - Provider bundle
- `src/common/generator/preprocess/routing.rb` - Routing configuration
- `src/common/generator/preprocess/session_id.rb` - Session ID
- `src/common/generator/preprocess/session_info.rb` - Session information
- `src/common/generator/preprocess/single_snippet.rb` - Single snippet
- `src/common/generator/preprocess/static_resource.rb` - Static resources
- `src/common/generator/preprocess/unified_callback.rb` - Unified callback
- `src/common/generator/preprocess/user_data.rb` - User data handling

**Malware Preprocessors (11 files):**
- `src/malware/generator/preprocess/actionable_intelligence.rb` - Actionable intelligence
- `src/malware/generator/preprocess/active.rb` - Active malware detection
- `src/malware/generator/preprocess/count_session_id.rb` - Session counting
- `src/malware/generator/preprocess/frontend_api.rb` - Frontend API
- `src/malware/generator/preprocess/header_based_detection.rb` - Header detection
- `src/malware/generator/preprocess/multi.rb` - Multi-detection
- `src/malware/generator/preprocess/passive.rb` - Passive detection
- `src/malware/generator/preprocess/research.rb` - Research features
- `src/malware/generator/preprocess/session_info.rb` - Session info
- `src/malware/generator/preprocess/smart_recording.rb` - Smart recording
- `src/malware/generator/preprocess/stats_log.rb` - Statistics logging

#### **2. Generator Core (25 files, 17%)**

**Main Generator Files:**
- `src/core/generator/generator.rb` - Main generator orchestrator
- `src/core/generator/preprocessor.rb` - Preprocessor coordinator
- `src/core/generator/runner.rb` - Generator runner
- `src/ato/generator/tasks.rb` - ATO task definitions
- `src/malware/generator/tasks.rb` - Malware task definitions

**Template & Rendering:**
- `src/core/generator/templates.rb` - Template engine (base)
- `src/core/generator/templatesv2.rb` - Template engine v2
- `src/core/generator/erb_methods.rb` - ERB helper methods
- `src/lib/ruby/render_erb.rb` - Standalone ERB renderer

**Bundle Management:**
- `src/core/generator/pinpoint_bundle_builder.rb` - Bundle builder
- `src/core/bundles/ruby/bundle.rb` - Bundle data structure
- `src/core/generator/packing_bundle.rb` - Bundle packing
- `src/core/generator/fetcher.rb` - Bundle fetching

**Code Generation:**
- `src/core/generator/to_lua/to_lua.rb` - Ruby-to-Lua converter
- `src/core/generator/to_lua/to_lua/generator.rb` - Lua generator
- `src/core/generator/to_lua/to_lua/helpers.rb` - Lua helpers
- `src/core/generator/generate_binary.rb` - Binary generation
- `src/core/generator/generate_origin.rb` - Origin generation
- `src/core/generator/papyrus_converter.rb` - Papyrus conversion

**Validation & Quality:**
- `src/core/generator/validator.rb` - Bundle validator
- `src/core/generator/jshint.rb` - JavaScript linting
- `src/core/generator/valiate_bundle_js_files.rb` - JS file validation

**Support:**
- `src/core/generator/features.rb` - Feature flags
- `src/core/generator/server_features.rb` - Server features
- `src/core/generator/common_items.rb` - Common items
- `src/core/generator/logger_wrapper.rb` - Logger wrapper

#### **3. Utility Libraries (31 files, 21%)**

**Redis Integration (5 files):**
- `src/core/utils/ruby/redis_helper.rb` - Redis operations wrapper
- `src/core/utils/ruby/redis_connection.rb` - Redis connection singleton
- `src/core/utils/ruby/redis_lists.rb` - Redis list operations
- `src/core/utils/ruby/redis_lists/event.rb` - Event list handling
- `src/core/utils/ruby/redis_lists/cache_buffer.rb` - Cache buffer
- `src/core/utils/ruby/redis_lists/event_errors.rb` - Error list handling

**Core Utilities:**
- `src/core/utils/ruby/utils.rb` - General utilities
- `src/core/utils/ruby/string_utils.rb` - String manipulation
- `src/core/utils/ruby/array_utils.rb` - Array operations
- `src/core/utils/ruby/crc16.rb` - CRC16 checksum
- `src/core/utils/ruby/HTTPunix.rb` - Unix socket HTTP client

**Service Integration:**
- `src/core/utils/ruby/scheduler.rb` - Task scheduler
- `src/core/utils/ruby/missioner.rb` - Mission queue client
- `src/core/utils/ruby/run_scripts.rb` - Script runner
- `src/core/utils/ruby/statsd.rb` - StatsD metrics
- `src/core/utils/ruby/team_viewer.rb` - TeamViewer integration
- `src/core/utils/ruby/rulesets.rb` - Ruleset management

**Generator Support (11 files):**
- `src/core/generator/clients/s3.rb` - S3 client
- `src/core/generator/clients/redis.rb` - Redis client
- `src/core/generator/clients/generic_s3.rb` - Generic S3 client
- `src/core/generator/common_items/helpers.rb` - Common helpers
- `src/core/generator/common_items/node.rb` - Node structure
- `src/core/generator/common_items/tree.rb` - Tree structure
- `src/core/generator/common_items/wildcard_matchs.rb` - Wildcard matching
- `src/core/generator/models/cover_config.rb` - Cover configuration
- `src/core/generator/models/storage.rb` - Storage model
- `src/core/generator/monkey_patch_packr.rb` - Packr monkey patch
- `src/core/generator/monkey_patch_redis_helper.rb` - Redis helper patch

**Event Management:**
- `src/core/generator/events/generator_error.rb` - Generator errors
- `src/core/generator/events/js_validation_event.rb` - JS validation events
- `src/core/generator/event_uploader.rb` - Event uploader
- `src/core/generator/log_exporter.rb` - Log exporter

#### **4. Multi-Events Uploader (14 files, 9%)**

**Core Components:**
- `src/core/multi_events_uploader/bin/runner.rb` - Main entry point
- `src/core/multi_events_uploader/lib/runner.rb` - Runner implementation
- `src/core/multi_events_uploader/lib/worker.rb` - Worker threads
- `src/core/multi_events_uploader/lib/watcher.rb` - File watcher
- `src/core/multi_events_uploader/lib/scraper.rb` - File scraper
- `src/core/multi_events_uploader/lib/events.rb` - Event parsers
- `src/core/multi_events_uploader/lib/telegraf.rb` - Telegraf metrics

**Client Implementations:**
- `src/core/multi_events_uploader/lib/clients.rb` - Client factory
- `src/core/multi_events_uploader/lib/clients/base.rb` - Base client
- `src/core/multi_events_uploader/lib/clients/s3.rb` - S3 uploader
- `src/core/multi_events_uploader/lib/clients/kinesis_firehose.rb` - Kinesis uploader
- `src/core/multi_events_uploader/lib/clients/event_processor.rb` - Event processor

**Testing:**
- `src/core/multi_events_uploader/spec/seed.rb` - Test seed data
- `src/core/multi_events_uploader/spec/spec_events.rb` - Event specs
- `src/core/multi_events_uploader/spec/clients/spec_s3.rb` - S3 client specs

#### **5. Obfuscation System (8 files, 5%)**

**Core:**
- `src/lib/obfuscation/obfuscation.rb` - Main obfuscation orchestrator
- `src/lib/obfuscation/arbitrary_code.rb` - Arbitrary code injection
- `src/lib/obfuscation/arbitrary_code/ACHelper.rb` - AC helper
- `src/lib/obfuscation/arbitrary_code/ACLevel.rb` - AC level management

**Templates:**
- `src/lib/obfuscation/arbitrary_code/templates/base.rb` - Base template
- `src/lib/obfuscation/arbitrary_code/templates/vars.rb` - Variable obfuscation
- `src/lib/obfuscation/arbitrary_code/templates/functions.rb` - Function obfuscation

**Encryption:**
- `src/lib/generator/preprocess/collections_encryption.rb` - Collection encryption
- `src/lib/generator/preprocess/evidences_encryption.rb` - Evidence encryption

#### **6. Specialized Tools (10 files, 7%)**

**PII Cleaner:**
- `src/core/pii-cleaner/lib/runner.rb` - Main runner
- `src/core/pii-cleaner/lib/cleaner.rb` - Data cleaner
- `src/core/pii-cleaner/lib/mapper.rb` - Data mapper

**Scripts:**
- `src/core/scripts/cacher.rb` - Caching script
- `src/core/scripts/malware_stats_processor.rb` - Malware stats processor

**Testing:**
- `src/core/unitests_automation/analyze_tests_output.rb` - Test output analyzer

---

### A3. Representative require/require_relative Statements

#### **1. Relative Path Requires (Generator Pattern)**
```ruby
# src/ato/generator/tasks.rb:1-5
require 'erb'
require "./generator/templatesv2.rb"
require "./generator/models/cover_config.rb"
require "./utils/ruby/utils.rb"
require "yajl"
```
**Pattern:** Uses `./` prefix for project files, assumes execution from `/data/kashmir/pinpoint/core/`

#### **2. Standard Library Requires**
```ruby
# src/core/multi_events_uploader/lib/runner.rb:1-9
require 'trollop'
require 'json'
require 'logger'
require 'fileutils'
require 'tmpdir'
require 'rb-inotify'
require 'thread'
require 'singleton'
require 'etc'
```
**Pattern:** Standard Ruby gems and built-in libraries

#### **3. Local Module Requires**
```ruby
# src/core/multi_events_uploader/lib/runner.rb:10-14
require './lib/events.rb'
require './lib/clients.rb'
require './lib/watcher.rb'
require './lib/worker.rb'
require './lib/scraper.rb'
```
**Pattern:** Relative requires within same component

#### **4. Utils Helper Pattern**
```ruby
# src/lib/obfuscation/obfuscation.rb:1
require Utils.require_component_path("lib", "obfuscation/arbitrary_code.rb")
```
**Pattern:** Dynamic path resolution via Utils helper

#### **5. Cross-Component Requires**
```ruby
# src/core/generator/generator.rb:1-16
require "pp"
require "yajl"
require "fileutils"
require "packr"
require "./generator/templates.rb"
require "./generator/features.rb"
require "./utils/ruby/utils.rb"
require "./generator/logger_wrapper.rb"
require "./generator/monkey_patch_packr.rb"
require "parallel"
require "zlib"
require "tempfile"
require "open3"
require "json"
require "./generator/jshint.rb"
require Utils.require_component_path("lib", "obfuscation/obfuscation.rb")
```
**Pattern:** Mix of standard libs, local files, and dynamic component paths

#### **6. Preprocessor Requires**
```ruby
# src/core/generator/preprocessor.rb:1-4
require "./utils/ruby/utils.rb"
require "./generator/server_features.rb"
require "./generator/pinpoint_bundle_builder.rb"
require "./generator/logger_wrapper.rb"
```
**Pattern:** Generator infrastructure dependencies

#### **7. Database Client Requires**
```ruby
# src/core/pii-cleaner/lib/runner.rb:1-5
require 'pp'
require 'mapper'
require 'logger'
require 'cleaner'
require "sequel"
```
**Pattern:** Local modules without path prefix (same directory)

#### **8. Redis Integration Requires**
```ruby
# src/core/utils/ruby/redis_helper.rb:1-3
require "redis"
require "yajl"
require "./utils/ruby/utils.rb"
```
**Pattern:** External gem + local utility

#### **9. HTTP Client Requires**
```ruby
# src/core/utils/ruby/missioner.rb:1-5
require "json"
require "digest"
require "securerandom"
require "logger"
require "./utils/ruby/HTTPunix.rb"
```
**Pattern:** Standard libs + custom HTTP client

#### **10. Template Rendering Requires**
```ruby
# src/lib/ruby/render_erb.rb:1-4
require 'erb'
require 'ostruct'
require 'yajl'
require 'json'
```
**Pattern:** Pure standard library dependencies

---

### A4. Ruby Class Inheritance Chains

Ruby uses minimal inheritance in this codebase. Only 6 inheritance relationships found:

#### **1. Template Engine Inheritance**
```ruby
# src/core/generator/templatesv2.rb:4
class Templatesv2 < Templates
```
**Purpose:** Extends base template engine for version 10+ compatibility
**Parent:** `Templates` class (src/core/generator/templates.rb)
**Child adds:** Modified `render()` method for new bundle format

#### **2. Logger Wrapper Inheritance**
```ruby
# src/core/generator/logger_wrapper.rb:8
class LoggerWrapper < Logger
```
**Purpose:** Extends Ruby's standard Logger with context tracking
**Parent:** Ruby standard library `Logger`
**Child adds:** Context management (@context hash), application/environment/revision tracking

#### **3. Obfuscation Template Inheritance**
```ruby
# src/lib/obfuscation/arbitrary_code/templates/functions.rb:3
class ObfuscationArbitraryCodeFunctions < ObfuscationArbitraryCodeBase

# src/lib/obfuscation/arbitrary_code/templates/vars.rb:3
class ObfuscationArbitraryCodeVars < ObfuscationArbitraryCodeBase
```
**Purpose:** Specialized obfuscation templates
**Parent:** `ObfuscationArbitraryCodeBase` (src/lib/obfuscation/arbitrary_code/templates/base.rb)
**Children add:** Specific obfuscation strategies for functions and variables

#### **4. Custom Exception Classes**
```ruby
# src/core/utils/ruby/redis_helper.rb:5
class RedisError < StandardError

# src/core/generator/papyrus_converter.rb:5
class PapyrusConverterError < Exception
```
**Purpose:** Domain-specific exceptions
**Parents:** Ruby standard `StandardError` and `Exception`
**Children add:** Custom error handling for Redis and Papyrus operations

#### **5. Multi-Events Uploader Client Hierarchy**
```ruby
# src/core/multi_events_uploader/lib/clients/s3.rb:6
class S3 < Base

# src/core/multi_events_uploader/lib/clients/kinesis_firehose.rb:6
class KinesisFirehose < Base
```
**Purpose:** Polymorphic event uploaders
**Parent:** `Base` class (src/core/multi_events_uploader/lib/clients/base.rb)
**Children add:** S3 and Kinesis-specific upload implementations

**Key Observation:** Codebase prefers composition over inheritance. Most classes are standalone or use mixins (include/extend) rather than inheritance chains.

---

### A5. Include/Extend Statements

#### **1. Singleton Pattern (3 instances)**
```ruby
# src/core/multi_events_uploader/lib/events.rb:7
class Events
  include Singleton

# src/core/utils/ruby/redis_connection.rb:6
class RedisConnection
  include Singleton
```
**Purpose:** Ensures single instance of Events parser and Redis connection
**Pattern:** Standard Ruby Singleton mixin

#### **2. ERB Methods Mixin**
```ruby
# src/core/generator/templates.rb:7
class Templates
  include ErbMethods
```
**Purpose:** Adds ERB helper methods to template engine
**Module:** `ErbMethods` (defined in src/core/generator/erb_methods.rb)

#### **3. ToLua Converter Mixins (7 instances)**
```ruby
# src/core/generator/to_lua/to_lua.rb:6-34
class Hash
  include ToLua::Generator::GeneratorMethods::Hash
end

class Array
  include ToLua::Generator::GeneratorMethods::Array
end

class String
  include ToLua::Generator::GeneratorMethods::String
end

class NilClass
  include ToLua::Generator::GeneratorMethods::NilClass
end

class Numeric
  include ToLua::Generator::GeneratorMethods::ToString
end

class TrueClass
  include ToLua::Generator::GeneratorMethods::ToString
end

class FalseClass
  include ToLua::Generator::GeneratorMethods::ToString
end

class Object
  include ToLua::Generator::GeneratorMethods::Object
end
```
**Purpose:** Monkey-patches Ruby core classes to add `.to_lua` method
**Pattern:** Extends built-in types with custom serialization
**Module:** `ToLua::Generator::GeneratorMethods` (src/core/generator/to_lua/to_lua/generator.rb)

#### **4. Preprocessor Feature Validation (2 instances)**
```ruby
# src/common/generator/preprocess/dummy_snippet.rb:9
raise("Dummy snippet should not include other features!")

# src/common/generator/preprocess/loader.rb:201
raise("Loader snippet should include loader feature only!")
```
**Note:** These are validation checks, not actual include statements

**Summary:** 
- **Total include statements:** 10
- **Singleton pattern:** 2 uses
- **Mixin pattern:** 8 uses (7 for ToLua, 1 for ERB)
- **No extend statements found** (all use include)

---

### A6. Analysis of 10 Orphan Ruby Files

"Orphan" files are Ruby files that are not directly required by other Ruby files but are invoked through other mechanisms.

#### **1. src/ato/generator/tasks.rb**
**Status:** Dynamically loaded orphan
**Invocation:** 
```ruby
# src/core/generator/generator.rb:53-54
klass = Class.new
klass.class_eval(IO.read(entry))  # Loads tasks.rb content
```
**Purpose:** Defines `generate(bundle, jsunit)` method for ATO snippet generation
**Dependencies:** templatesv2.rb, cover_config.rb, utils.rb
**Output:** Hash of generated JavaScript files
**Why orphan:** Loaded via `class_eval()` not `require()`

#### **2. src/malware/generator/tasks.rb**
**Status:** Dynamically loaded orphan
**Invocation:** Same pattern as ATO tasks.rb
**Purpose:** Defines `generate(bundle, jsunit)` method for Malware snippet generation
**Dependencies:** Identical to ATO tasks.rb
**Output:** Hash of generated JavaScript files
**Why orphan:** Loaded via `class_eval()` not `require()`

#### **3. src/core/multi_events_uploader/bin/runner.rb**
**Status:** Shell-invoked orphan
**Invocation:**
```bash
# src/core/multi_events_uploader/bin/job_runner.sh:4
ruby bin/runner.rb

# dockers/multi_events_uploader/resources/healthcheck.sh:2
pgrep -f "ruby.*runner.rb"
```
**Purpose:** Main entry point for multi-events uploader service
**Dependencies:** lib/runner.rb, lib/telegraf.rb, utils.rb
**Output:** Runs continuous file watcher and uploader threads
**Why orphan:** Executed directly by shell, not required

#### **4. src/core/scripts/cacher.rb**
**Status:** Shell-invoked orphan
**Invocation:**
```bash
# test_cacher_s3_operations.sh:130,134,161,241
ruby -c scripts/cacher.rb  # Syntax check
ruby ./scripts/cacher.rb   # Execution
```
**Purpose:** Cache management script
**Dependencies:** Unknown (file not fully examined)
**Output:** Cache operations
**Why orphan:** Executed directly by shell scripts

#### **5. src/lib/ruby/render_erb.rb**
**Status:** CLI tool orphan
**Invocation:** Command-line usage
```bash
ruby render_erb.rb <erb_path> <conf_json>
```
**Purpose:** Standalone ERB template renderer
**Dependencies:** erb, ostruct, yajl, json
**Output:** Rendered template to STDOUT
**Why orphan:** Standalone CLI tool, not part of require chain

#### **6. src/core/unitests_automation/analyze_tests_output.rb**
**Status:** Test automation orphan
**Invocation:** Referenced in documentation
```markdown
# src/core/unitests_automation/README.md:17
### analyze_tests_output.rb
```
**Purpose:** Analyzes test output for reporting
**Dependencies:** Unknown (file not examined)
**Output:** Test analysis results
**Why orphan:** Test utility, invoked by test framework

#### **7. src/core/scripts/malware_stats_processor.rb**
**Status:** Cron/scheduled orphan
**Invocation:** Likely via cron or scheduler
**Purpose:** Processes malware statistics
**Dependencies:** Unknown (file not examined)
**Output:** Processed statistics
**Why orphan:** Scheduled task, not part of require chain

#### **8. src/core/pii-cleaner/lib/runner.rb**
**Status:** CLI tool orphan
**Invocation:** Likely via command-line with options
**Purpose:** PII data cleaning orchestrator
**Dependencies:** mapper.rb, cleaner.rb, sequel (MySQL)
**Output:** Cleaned database records
**Why orphan:** Standalone tool with CLI options

#### **9. src/common/generator/preprocess/_0_master_bundle.rb**
**Status:** Convention-based orphan
**Invocation:** Loaded by preprocessor via directory scan
```ruby
# src/core/generator/preprocessor.rb:15
scan_for_preprocess(@config["base_path"])
```
**Purpose:** Master bundle configuration (runs first due to _0_ prefix)
**Dependencies:** None (defines methods only)
**Output:** Modifies bundle_builder
**Why orphan:** Loaded by convention, not explicit require

#### **10. src/common/generator/preprocess/_1_diagnostic_snippet.rb**
**Status:** Convention-based orphan
**Invocation:** Same as _0_master_bundle.rb
**Purpose:** Diagnostic snippet generation (runs second due to _1_ prefix)
**Dependencies:** None (defines methods only)
**Output:** Modifies bundle_builder
**Why orphan:** Loaded by convention, not explicit require

**Common Patterns:**
1. **Dynamic loading:** tasks.rb files loaded via `class_eval()`
2. **Shell invocation:** runner.rb, cacher.rb executed by shell
3. **Convention-based:** Preprocessors loaded by directory scan
4. **CLI tools:** render_erb.rb, pii-cleaner standalone utilities
5. **Scheduled tasks:** Stats processors run via cron/scheduler

---

### A7. Ruby Files Invoked by Shell/Docker/Cron/Makefiles

#### **1. Shell Script Invocations**

**Multi-Events Uploader:**
```bash
# src/core/multi_events_uploader/bin/job_runner.sh:3-4
cd /data/kashmir/pinpoint/core/multi_events_uploader
ruby bin/runner.rb
```

**Policy Error Events:**
```bash
# src/core/scripts/job_start_upload_policy_error_events.sh:3-4
cd /data/kashmir/pinpoint/core/scripts/multi_events_uploader
ruby bin/run.rb --name policy_error --log /data/kashmir/pinpoint/shared/log/policy_error_events_v1.log
```

**Cacher Operations:**
```bash
# test_cacher_s3_operations.sh:130,134,161,241
ruby -c scripts/cacher.rb  # Syntax check
timeout 300 ruby ./scripts/cacher.rb 2>&1 | tee "$TEST_LOG"
timeout 1800 ruby ./scripts/cacher.rb 2>&1 | tee "$TEST_LOG"
```

#### **2. Docker Healthcheck**
```bash
# dockers/multi_events_uploader/resources/healthcheck.sh:2
if ! pgrep -f "ruby.*runner.rb" > /dev/null; then
    echo "ERROR: process not found"
```
**Purpose:** Monitors multi_events_uploader service

#### **3. Systemd Service (Implied)**
Based on patterns, these Ruby scripts likely have systemd services:
- `src/core/multi_events_uploader/bin/runner.rb` → `pinpoint_multi_events_uploader.service`
- `src/core/scripts/cacher.rb` → `pinpoint_cacher.service`

#### **4. Generator Invocation (Indirect)**
```bash
# Pattern from documentation
cd /data/kashmir/pinpoint/core
ruby -c generator/generator.rb  # Syntax check
# Actual invocation via Lua calling Ruby
```

#### **5. No Makefile Invocations Found**
Search for `.rb` in Makefiles returned 0 results. Ruby is not invoked directly from Makefiles.

#### **6. Cron Jobs (Inferred)**
Based on scheduler.rb and file patterns, likely cron jobs:
- `src/core/scripts/malware_stats_processor.rb` - Periodic stats processing
- Preprocessor updates - Scheduled bundle regeneration

**Summary:**
- **Direct shell invocations:** 3 files (runner.rb, cacher.rb, run.rb)
- **Healthcheck monitoring:** 1 file (runner.rb)
- **Systemd services:** 2+ files (inferred)
- **Makefile invocations:** 0 files
- **Cron jobs:** 2+ files (inferred from scheduler pattern)

---

### A8. Ruby Communication via Non-Require Mechanisms

#### **1. Redis Communication**

**RedisHelper Class:**
```ruby
# src/core/utils/ruby/redis_helper.rb:13
@redis = Redis.new(redis_cluster_config)

# Operations:
def get(key)           # Read from Redis
def set(key, value)    # Write to Redis
def get_json(key)      # Parse JSON from Redis
def set_json(key, value) # Store JSON to Redis
def hget(key, sub_key) # Hash operations
def eval(script, keys, values) # Lua script execution
```

**Usage Pattern:**
```ruby
# src/core/generator/clients/redis.rb
# Stores generated bundles in Redis
# Keys: "bundles/<origin>/<revision>/<environment>/<key>"

# src/core/utils/ruby/redis_lists.rb
# Manages Redis lists for events, errors, cache buffers
```

**Communication Flow:**
- Ruby Generator → Redis → Lua (OpenResty reads bundles)
- Ruby Cacher → Redis → Lua (cache invalidation)
- Ruby Scripts → Redis Lists → Lua (event queues)

#### **2. AWS S3 Communication**

**S3 Client:**
```ruby
# src/core/multi_events_uploader/lib/clients/s3.rb:13-14
client = Aws::S3::Client.new(get_client_opts(client_config))
resource = Aws::S3::Resource.new(:client => client)

# Upload operation:
obj = bucket.object(s3_key)
obj.upload_file(file_name, server_side_encryption: 'AES256')
```

**Generator S3 Client:**
```ruby
# src/core/generator/clients/s3.rb
# Uploads generated bundles to S3
# Pattern: s3://<bucket>/<origin>/<revision>/<environment>/<key>/
```

**Communication Flow:**
- Ruby Generator → S3 → CloudFront → Browsers
- Ruby Multi-Events Uploader → S3 → Analytics systems

#### **3. AWS Kinesis Firehose Communication**

**Kinesis Client:**
```ruby
# src/core/multi_events_uploader/lib/clients/kinesis_firehose.rb
client = Aws::Firehose::Client.new(get_client_opts(client_config))

# Stream upload:
response = client.put_record({
  delivery_stream_name: stream,
  record: { data: event }
})
```

**Communication Flow:**
- Ruby Multi-Events Uploader → Kinesis Firehose → S3/Redshift → Analytics

#### **4. HTTP/HTTPS Communication**

**Unix Socket HTTP:**
```ruby
# src/core/utils/ruby/HTTPunix.rb
# Custom HTTP client for Unix sockets
# Used by Missioner client

# src/core/utils/ruby/missioner.rb:80
def send_message(message, delay, task_type, query_parameters)
  # Sends HTTP POST to unix:///data/kashmir/pinpoint/shared/sockets/missioner.sock
```

**HTTPS with Client Certificates:**
```ruby
# src/core/multi_events_uploader/lib/clients/event_processor.rb:28-30
http = Net::HTTP.new(uri.host, uri.port)
http.cert = OpenSSL::X509::Certificate.new(File.read client_config["certificate_file_location"])
http.key = OpenSSL::PKey::RSA.new(File.read client_config["key_file_location"])
```

**Communication Flow:**
- Ruby Scheduler → Unix Socket → Missioner (Lua) → Task execution
- Ruby Event Processor → HTTPS → External event processors

#### **5. File I/O Communication**

**File Watching:**
```ruby
# src/core/multi_events_uploader/lib/watcher.rb:6
require 'rb-inotify'

# Watches directory for new files:
# /data/kashmir/pinpoint/shared/queues/events/incoming
```

**File Scraping:**
```ruby
# src/core/multi_events_uploader/lib/scraper.rb
# Periodically scans directories for files
# Processes and uploads to S3/Kinesis
```

**Log File Writing:**
```ruby
# src/core/multi_events_uploader/bin/runner.rb:9
logger = Logger.new(File.join(shared_dir, "log", "multi_events_uploader.log"))

# src/core/generator/logger_wrapper.rb
# Writes to /data/kashmir/pinpoint/shared/log/generator.log
```

**Communication Flow:**
- Lua → File Write → Ruby Watcher → S3/Kinesis upload
- Ruby Generator → Log Files → Monitoring systems

#### **6. MySQL Database Communication**

**PII Cleaner:**
```ruby
# src/core/pii-cleaner/lib/runner.rb:15
@db = Sequel.connect("mysql://#{host}:#{port}/#{db_name}?username=#{user}&password=#{pass}")

# Operations:
@mapper.map           # Reads from MySQL
@cleaner.clean_by_*   # Writes to MySQL
```

**Communication Flow:**
- Ruby PII Cleaner → MySQL → Data anonymization

#### **7. StatsD/Telegraf Metrics**

**Telegraf Client:**
```ruby
# src/core/multi_events_uploader/lib/telegraf.rb
# Sends metrics to Telegraf via UDP

# src/core/utils/ruby/statsd.rb
# StatsD client for metrics
```

**Communication Flow:**
- Ruby Services → Telegraf → InfluxDB → Grafana

#### **8. Process Signals & Threading**

**Thread Communication:**
```ruby
# src/core/multi_events_uploader/lib/runner.rb:27
@queue = Queue.new  # Thread-safe queue

# Worker threads:
@threads << Thread.new {
  worker = Worker.new(@config, i, @queue, @logger, @telegraf, @features)
  worker.run!
}
```

**Communication Flow:**
- Watcher Thread → Queue → Worker Threads → S3/Kinesis

#### **9. Shell Command Execution**

**Subprocess Communication:**
```ruby
# src/core/generator/generator.rb:13
require "open3"

# Likely used for:
# - Running jshint validation
# - Executing packr minification
# - Running external tools
```

**Communication Flow:**
- Ruby Generator → Shell Commands → External tools → Results

#### **10. Configuration File Communication**

**JSON Configuration Loading:**
```ruby
# src/core/utils/ruby/utils.rb
def self.load_config_file(filename, logger = nil)
  # Reads from /data/kashmir/pinpoint/shared/config/<filename>
end

# Loaded configs:
# - features.json
# - cacher.json
# - multi_events_uploader.json
# - stats.json
# - central_env.json
# - preprocess.json
```

**Communication Flow:**
- Config Files → Ruby Services → Runtime behavior changes

---

## Summary Statistics

**Total Ruby Files:** 151

**By Category:**
- Generator Preprocessors: 63 files (42%)
- Generator Core: 25 files (17%)
- Utility Libraries: 31 files (21%)
- Multi-Events Uploader: 14 files (9%)
- Obfuscation System: 8 files (5%)
- Specialized Tools: 10 files (7%)

**Invocation Mechanisms:**
- Dynamic loading (class_eval): 2 files
- Shell scripts: 3 files
- Convention-based loading: 63 files (preprocessors)
- Direct require: 73 files
- CLI tools: 3 files
- Systemd services: 2+ files
- Cron jobs: 2+ files (inferred)

**Communication Patterns:**
- Redis: 5 files
- AWS S3: 3 files
- AWS Kinesis: 1 file
- HTTP/Unix sockets: 2 files
- File I/O: 3 files
- MySQL: 3 files
- Metrics (StatsD/Telegraf): 2 files
- Threading/Queues: 1 file
- Shell execution: 1 file
- Config files: All services

**Inheritance Chains:** 6 (minimal use)
**Include/Extend Statements:** 10 (focused use)

---