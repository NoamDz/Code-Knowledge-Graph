---

## SECTION B ANSWERS: JavaScript Connection Model

### B1. Final HTML Output

The final HTML output is a **single `<script>` tag that loads a dynamically generated JavaScript file**. The system does NOT concatenate all JS into one inline script, nor does it use multiple script tags.

**Actual HTML Template** (`src/ato/templates/snippets/collector.tpl`):
```html
<script type="text/javascript">
 (function() {
   var bt="text/java",z=document,fh=z.getElementsByTagName('head')[0],k='script';
   var y=z.createElement(k);y.async=true;y.type=bt+k;y.src=window.location.protocol + "//$prefix/$key/$filename?r="+Math.floor(Math.random()*100000);
   fh.appendChild(y);
 })();
</script>
```

This creates a **loader snippet** that:
1. Dynamically creates a `<script>` element
2. Sets `src` to load the pre-generated bundle from the server (e.g., `/prefix/appkey/filename.js`)
3. Appends it to the page `<head>`

The loaded file is a **single concatenated JavaScript bundle** generated at build time.

---

### B2. Generator Output Files

**Output Path Pattern**: `/data/kashmir/pinpoint/{component}/{filename}`

For example:
- Input: `src/common/base/js/container.js.erb` (template)
- Processing: Ruby generator renders ERB with bundle configuration
- Output: `/data/kashmir/pinpoint/ato/snippet_12345.js` (or similar application-specific name)

**Key Points**:
- Output files are named based on `snippet['main_file_name']` from bundle configuration
- Files go directly to component directories (no version subdirectories in new system)
- Each application gets its own customized bundle file
- Files are also uploaded to S3 and Redis for distribution

**From `src/ato/generator/tasks.rb` (lines 75-76)**:
```ruby
generated_files[snippet['main_file_name']] = { :content => content, :options => snippet['options'] || {}}
```

The generator produces **one output file per snippet configuration**, containing all concatenated JavaScript for that snippet.

---

### B3. Global Variable Definitions

**IMPORTANT**: These are **NOT window.* assignments**. The system uses **module pattern with local variables** that are **NOT exposed globally**. This is a key architectural decision.

#### Core Infrastructure Globals:

**1. Net** (`src/lib/js/net.js.erb`, line 2):
```javascript
var Net = (function() {
  // ... implementation
  return {
    _iframe: iframe,
    _xframe: xframe,
    _jsonp: jsonp,
    _image: image,
    _ajax: ajax,
    _request: request,
    // ... more methods
  }
})();
```
**Scope**: Local variable in the IIFE, NOT `window.Net`

**2. Container** (`src/common/base/js/container.js.erb`, line 42):
```javascript
var Container = (function(){
  // ... implementation
  return {
    _sendRequest : sendRequest,
    _collect : collect,
    _bindEvent : bindEvent,
    _emitEvent : emitEvent,
    // ... 40+ methods
  }
})();
```
**Scope**: Local variable in the IIFE, NOT `window.Container`

**3. DeviceContainer** (`src/ato/collectors/device/templates/device_container.js.erb`, line 1):
```javascript
var DeviceContainer = (function() {
  // ... embeds DeviceId and GlobalDeviceId modules
  return {
    // methods
  };
})();
```
**Scope**: Local variable, NOT `window.DeviceContainer`

**4. Behave** (`src/ato/collectors/behave/templates/behave.js.erb`, line 1):
```javascript
var Behave = (function() {
  // ... embeds KeyStrokes, MouseMovements, MetaStrokes
  return {
    _id: id
  };
})();
```
**Scope**: Local variable, NOT `window.Behave`

#### Supporting Globals (all local scope):
- `Utils`, `JSON`, `Base64`, `RC4`, `SHA256`, `AES`, `RSA` (crypto/utility)
- `SessionID`, `Cookie`, `SharedObject` (state management)
- `Jsonp`, `DOMLoadedHelper`, `TaskQueue` (infrastructure)
- `DeviceFeatures`, `UserAgent`, `Referrer`, `Tag` (detection)

**Critical Insight**: The entire bundle runs inside **one giant IIFE** (Immediately Invoked Function Expression):

```javascript
(function(){
  // All modules defined here as local variables
  var Net = ...;
  var Container = ...;
  var DeviceContainer = ...;
  // Collectors rendered here
  Container._setup();  // Initialize
})();
```

**From `src/common/base/js/container.js.erb` (lines 3, 1308)**:
```javascript
<% unless env["bundle"].get("app_disabled") %>
(function(){
  // ... all code ...
  Container._setup();
})();
<% end %>
```

**Result**: NO global pollution. Everything is encapsulated. The only way to interact is through the initial loader snippet.

---

### B4. Global Variable Consumption

Since these are **local variables within one IIFE**, they reference each other **directly by name**, not via `window.*`.

#### Container Dependencies:

**Files that call `Container._sendRequest(...)`**:
1. `src/malware/collectors/active/templates/active.js.erb` (line 57)
2. `src/malware/collectors/multi/templates/multi.js.erb` (line 24)
3. `src/malware/collectors/smart_recording/templates/smart_recording.js.erb` (line 118)
4. `src/malware/collectors/multi/templates/multi_iframe.js.erb` (line 105)
5. `src/malware/adapters/frontend_api/templates/frontend_api.js.erb` (line 59)

**Files that call `Container._collect(...)`**:
- **30+ collector files** (behave, device, user_data, session_info, etc.)
- Every collector uses this to send data to backend

**Files that call `Container._bindEvent(...)`**:
- **50+ files** - virtually every collector and feature
- Used to hook into lifecycle events (onLoad, onSetup, onCollectDone, etc.)

#### Net Dependencies:

**Container calls `Net._request(...)`** (`src/common/base/js/container.js.erb`, line 729):
```javascript
function sendRequest(type, url, params, callback, data, extra){
  // ... parameter processing
  Net._request(type, url, params, callback, data, extra);
}
```

**DeviceId passes `Container._sendRequest` to sensor** (`src/ato/collectors/device/templates/device_id.js.erb`, line 400):
```javascript
function createBackwardCommunicator(){
  return {
    _sendRequest: Container._sendRequest,
    _Utils: Utils,
    // ... other references
  };
}
```

#### Utility Dependencies:

**Nearly every file references**:
- `Utils._*` methods (serialization, DOM manipulation, etc.)
- `JSON._parse`, `JSON._stringify`
- `Base64._encode`, `Base64._decode`
- `SHA256._digest`, `RC4._encrypt`

**Example from `src/ato/collectors/behave/templates/keystrokes.js.erb` (line 140)**:
```javascript
Container._collect(id, evidence, true);
```

---

### B5. Dependency Hierarchy

**YES, there is a clear layering**:

```
┌─────────────────────────────────────────────────────────┐
│ Layer 4: Collectors (Behave, Device, UserData, etc.)   │
│   - Use Container._collect(), Container._bindEvent()   │
│   - Implement specific data collection logic           │
└────────────────────┬────────────────────────────────────┘
                     │ depends on
┌────────────────────▼────────────────────────────────────┐
│ Layer 3: Container (Application Framework)              │
│   - Manages lifecycle events                            │
│   - Aggregates collection data                          │
│   - Calls Net._request() for communication              │
└────────────────────┬────────────────────────────────────┘
                     │ depends on
┌────────────────────▼────────────────────────────────────┐
│ Layer 2: Net (Network Communication)                    │
│   - Implements transport methods (ajax, jsonp, iframe)  │
│   - Handles cross-domain communication                  │
│   - Uses Utils for serialization                        │
└────────────────────┬────────────────────────────────────┘
                     │ depends on
┌────────────────────▼────────────────────────────────────┐
│ Layer 1: Utilities (Utils, JSON, Base64, Crypto, etc.) │
│   - Pure functions, no dependencies                     │
│   - Shared across all layers                            │
└─────────────────────────────────────────────────────────┘
```

**Initialization Order** (from `src/common/base/js/container.js.erb`, lines 4-40):
```javascript
(function(){
  // Layer 1: Utilities first
  <%=env["template"].render("base64.js", env)%>
  <%=env['template'].render("json.js", env)%>
  <%=env["template"].render("utils.js", env)%>
  
  // Layer 2: Network layer
  <%=env["template"].render("net.js.erb", env)%>
  
  // Layer 3: Container framework
  var Container = (function(){
    // ... implementation
  })();
  
  // Layer 4: Collectors rendered
  <% env['collectors_rendered'].each { |code| %> <%=code%> <% } %>
  
  // Initialize
  Container._setup();
})();
```

**Key Dependencies**:
- `Container` depends on `Net` (calls `Net._request`)
- `Net` depends on `Utils` (serialization, DOM helpers)
- Collectors depend on `Container` (lifecycle, collection)
- `DeviceContainer` depends on `Container` and `Net`
- `Behave` depends on `Container` and `DeviceFeatures`

**Initialization Flow**:
1. `Net._initialize(Container)` - Net gets Container reference
2. `Container._setup()` - Emits `_onSetup` event
3. Collectors bind to events via `Container._bindEvent()`
4. `Container._init()` - Emits `_onStart`, `_onLoad` events
5. Collectors execute and call `Container._collect()`

---

### B6. Three Concrete `Container._sendRequest` Calls

#### Example 1: Active Malware Collector
**File**: `src/malware/collectors/active/templates/active.js.erb` (lines 50-65)

```javascript
  function getTriggerExtra() {
    return {qs: '<%= env["bundle"].get("active/querystring_suffix") %>'};
  }

  function run() {
    Container._sendRequest(
      "xframe",
      getTriggerUrl(),
      getTriggerParams(),
      reportDone,
      getTriggerData(),
      getTriggerExtra()
    );
  }

  function initialize() {
    if (Container._isSmartSnippet) {
```

**Context**:
- **Location**: Inside `run()` function, called from `initialize()`
- **URL**: `getTriggerUrl()` - ERB template generates URL
- **Type**: `"xframe"` - cross-domain iframe communication
- **Callback**: `reportDone` - named function in same file

#### Example 2: Multi Collector
**File**: `src/malware/collectors/multi/templates/multi.js.erb` (lines 16-26)

```javascript
  function getHashData() {
    return {
      bu: baseUrl,
      e: encodeURI(location.protocol + "//" + location.host)
    };
  }

  function run() {
    Container._sendRequest("xframe", iframePath, {}, reportDone, getHashData());
  }

  function initialize() {
    if (Container._isSmartSnippet) {
      var collectorRunningState = Container._getSmartSnippetState(id);
```

**Context**:
- **Location**: Inside `run()` function
- **URL**: `iframePath` - variable defined earlier in file
- **Type**: `"xframe"` literal string
- **Data**: `getHashData()` - function call returns object

#### Example 3: Smart Recording Collector
**File**: `src/malware/collectors/smart_recording/templates/smart_recording.js.erb` (lines 110-120)

```javascript
    result.ti = (new Date() - startTime)/1000;
    result.s = result.d.length;
    result.u = win.location.href;
    result.ta = Container._getCurrentTag();
    result.tr = false;
    if (prevHash != result.h) {
      prevHash = result.h;
      var Data = {h: prevHash, s: result.s, ti: result.ti};
      Container._sendRequest(null, hashRequestPath, Data, getShouldCollectCallback(result));
    }
  }

  function initialize() {
```

**Context**:
- **Location**: Inside conditional block within function
- **URL**: `hashRequestPath` - variable (likely ERB-generated)
- **Type**: `null` - lets Container choose default type
- **Data**: Inline object literal `{h: prevHash, s: result.s, ti: result.ti}`
- **Callback**: `getShouldCollectCallback(result)` - function call

**Common Patterns**:
1. **URLs**: Mix of ERB templates and JavaScript variables
2. **Context**: Always inside named functions, never top-level
3. **Types**: String literals ("xframe", "ajax") or `null` for default
4. **Data**: Function calls returning objects or inline object literals
5. **Callbacks**: Named functions defined in same file

---

### B7. Other JS→Backend Communication Patterns

#### 1. Image Pixel Tracking
**File**: `src/lib/js/net.js.erb` (lines 384-397)

```javascript
function image(url, params, callback) {
  var img = new Image();

  if(Utils._isFunction(callback)) {
    Utils._attachCrossBrowserEvent(img, "load", function(e) { callback(); });
  }
  params = addEmbeddingUriData(params);
  img.src = [url, params].join("?");
  img.style.display = "none";
  img.alt = "";
  img.width = 0; img.height = 0; img.style.border = "none";

  doc.body.appendChild(img);
}
```

**Usage**: Called via `Net._request("image", ...)` or `Container._collectImmediateWithType("image", ...)`

**From `src/malware/collectors/passive/templates/passive.js.erb` (line 49)**:
```javascript
if (immediate) {
  Container._collectImmediateWithType("image", id, data);
}
```

#### 2. JSONP (Script Tag Injection)
**File**: `src/lib/js/net.js.erb` (lines 326-333)

```javascript
function jsonp(url, params, callback) {
  var s = doc.createElement('script');
  s.type = "text/javascript"; s.async = true;
  params += getCallbackQueryParams(callback);
  params = addEmbeddingUriData(params);
  s.src = [url, params].join("?");
  doc.getElementsByTagName('head')[0].appendChild(s);
}
```

**Usage**: Default collection method for small requests

#### 3. XMLHttpRequest (AJAX)
**File**: `src/lib/js/net.js.erb` (lines 270-316)

```javascript
function ajax(path, params, callback, data, options) {
  var fullPath, k, xhr = createXHR(), method = "GET", headers = {};
  var serializedData;
  // ... setup
  xhr.open(method, fullPath, true);
  for(k in headers) {
    xhr.setRequestHeader(k, headers[k]);
  }
  xhr.onreadystatechange = function() {
    if(xhr.readyState == 4 && (xhr.status == 200 || invokeCallbackOnFailure)) {
      callback(xhr.responseText, xhr.status);
    }
  };
  xhr.send(serializedData);
}
```

#### 4. Cross-Domain Iframe (xframe)
**File**: `src/lib/js/net.js.erb` (lines 201-227)

```javascript
function xframe(url, params, callback, data, use_fragment_params) {
  var icid = [new Date().getTime(), Math.floor((Math.random()*100000))].join(""),
      frameData = { "icid":  icid };
  // ... setup
  var fullURL = [url, Utils._serialize(params)].join((use_fragment_params)? "#" : "?"),
  id = createIframe(fullURL, data);     
  if(Utils._isPostMessageCompatible()) {
    postMessageData[frameData.icid] = { callback: callback, data: data, iframeId: id };
  } else {
    intervals[id] = win.setInterval(function() { pollIframe(id, callback); }, 200);
  }
  return { _id: id, _icid: icid };
}
```

**Uses postMessage for modern browsers, polling for legacy**

#### 5. XPost (POST via Iframe)
**File**: `src/lib/js/net.js.erb` (lines 365-382)

```javascript
function xpost(url, params, callback, data){
  var xPostData = {
    qp : Utils._serialize(params),
    pd : Utils._serialize(data),
    u : url
  };
  // ... setup
  xframe(xpostUrl, frameData, function(response){
      if(callback){
        callback(JSON._parse(response.r));
      }
    }, xPostData, true);
}
```

#### 6. JSONPI (JSONP Improved with CORS fallback)
**File**: `src/lib/js/net.js.erb` (lines 336-363)

```javascript
function jsonpi(url, params, callback) {
  var fullUrl, xhr,
      xhrString = "XMLHttpRequest";

  if(win[xhrString] && (xhr = new win[xhrString]()).withCredentials !== undefined) {
    // Try CORS first
    xhr.open("GET", fullUrl, true);
    xhr.withCredentials = true;
    xhr.onreadystatechange = function(e) {
      if (xhr.readyState == 4 && xhr.status == 200){
        callback(JSON._parse(xhr.responseText));
      } else if (xhr.readyState == 4 && xhr.status == 0) {
        // Fallback to JSONP
        params = replaceURLParam(params, "t", "jsonp");
        jsonp(url, params, callback);
      }
    };
    xhr.send();
  } else {
    // No CORS support, use JSONP
    jsonp(url, params, callback);
  }
}
```

**NO WebSocket or sendBeacon usage found in codebase.**

---

### B8. File Inclusion Order

**From `src/ato/generator/tasks.rb` and `src/common/base/js/container.js.erb`**:

#### Order for One Bundle (ATO Component):

```
1. IIFE Start: (function(){

2. Core Utilities (in container.js.erb, lines 4-40):
   - base64.js
   - json.js
   - rc4.js.erb
   - sha256.js.erb
   - cover_config.js.erb (conditional)
   - utils.js
   - jsonp.js
   - cookie.js
   - session_id.js.erb
   - jenkins.js
   - user_agent.js.erb
   - referrer.js.erb
   - tag.js.erb
   - team_viewer_constants.js.erb
   - rsa.js.erb (conditional)
   - collection_encryptor.js.erb (conditional)

3. Shuffled Templates (lines 33-40, shuffled if arbitrary_code=true):
   - DOMLoadedHelper.js.erb
   - task_queue.js
   - error_parser.js
   - net.js.erb
   - shared_object.js.erb
   - evidences_encryption.js.erb
   - strict.js

4. Container Definition (line 42):
   var Container = (function(){ ... })();

5. Collectors (line 1304, from tasks.rb lines 44-56):
   For each collector in snippet['collectors']:
     - device/templates/device_container.js.erb
       - device/templates/device_id.js.erb
       - device/templates/global_device_id.js.erb
       - device/templates/device_utils.js.erb
       - device/templates/sensor.js.erb
     - behave/templates/behave.js.erb
       - behave/templates/mouse_movements.js.erb
       - behave/templates/keystrokes.js.erb
       - behave/templates/metastrokes.js.erb
     - user_flow/templates/user_flow.js.erb
     - carboncopy/templates/carboncopy.js.erb
     - wisp/templates/wisp.js.erb
     - ... (other collectors as configured)

6. Initialization (line 1307):
   Container._setup();

7. IIFE End: })();
```

**Key Points**:
- **Deterministic order** except for the 7 shuffled templates (anti-fingerprinting)
- **Utilities first**, then **network layer**, then **container**, then **collectors**
- **Collectors order** determined by bundle configuration
- **Sub-templates** rendered inline (e.g., device_id.js.erb inside device_container.js.erb)

**From `src/ato/generator/tasks.rb` (lines 44-56)**:
```ruby
snippet['collectors'].each { |collector_path|
  @logger.info "Generating collector = #{collector_path}"
  content = template.render(collector_path, env)
  generated << content
}
env['collectors_rendered'] = generated
```

---

### B9. Bundle Count and File Distribution

**ONE bundle per snippet configuration**, NOT one bundle for all 94 files.

#### Bundle Structure:

**Multiple bundles exist**, one for each:
- Application (identified by `key`)
- Component (`ato`, `malware`, `common`)
- Snippet configuration within that application

**Example**:
- Application "bank_app" might have:
  - `ato_snippet_1.js` (ATO detection bundle)
  - `malware_snippet_1.js` (Malware detection bundle)
  - `ato_snippet_2.js` (Different ATO configuration)

**From `src/core/generator/generator.rb` (lines 103-110)**:
```ruby
bundles.compact.each do |bundle|
  @components.each do |component|
    next unless bundle.get(component)
    # Generate for this component
    results[bundle][:files].merge!(@tasks[component].generate(*arguments))
  end
end
```

**File Distribution**:
- **28 files** in `src/lib/js` → Included in EVERY bundle (utilities)
- **6 files** in `src/ato/collectors/behave/templates` → Included if behave enabled
- **5 files** in `src/ato/collectors/device/templates` → Included if device enabled
- **4 files** in `src/malware/collectors/research/templates` → Included if research enabled
- etc.

**Bundle Composition**:
```
Bundle = Core Utilities (always)
       + Network Layer (always)
       + Container Framework (always)
       + Selected Collectors (per configuration)
       + Selected Features (per configuration)
```

**NOT all 94 files in one bundle**. Each bundle is **customized** based on:
- Application requirements
- Enabled features
- Component (ato/malware/common)
- Performance constraints

---

### B10. Directory File Counts

```
28 files - src/lib/js
 7 files - src/common/collectors/user_data/templates/hooks
 6 files - src/ato/collectors/behave/templates
 5 files - src/ato/collectors/device/templates
 4 files - src/malware/collectors/research/templates
 4 files - src/common/templates/intelligent_snippet
 4 files - src/common/collectors/user_data/templates
 3 files - src/common/templates/intelligent_snippet/estimated_tag
 3 files - src/common/templates
 3 files - src/common/base/js
 3 files - src/ato/collectors/wisp/templates/helper
 2 files - src/malware/collectors/smart_recording/templates
 2 files - src/malware/collectors/passive/templates
 2 files - src/malware/collectors/multi/templates
 2 files - src/malware/collectors/active/templates
 2 files - src/lib/obfuscation/evidences_encryption/js
 1 file  - src/malware/adapters/frontend_api/templates
 1 file  - src/malware/actions/status/templates
 1 file  - src/common/collectors/unified_callback/templates
 1 file  - src/common/collectors/session_info/templates
 1 file  - src/common/collectors/global_cookies/templates
 1 file  - src/common/collectors/diagnostic_snippet/templates
 1 file  - src/common/collectors/customer_session_id/templates
 1 file  - src/common/collectors/client_info/templates
 1 file  - src/ato/collectors/wisp/templates
 1 file  - src/ato/collectors/user_flow/templates
 1 file  - src/ato/collectors/remote_access_detector/templates
 1 file  - src/ato/collectors/model_prediction/templates
 1 file  - src/ato/collectors/ipp/templates
 1 file  - src/ato/collectors/carboncopy/templates

TOTAL: 94 JavaScript files (.js and .js.erb)
```

---

### B11. File Categorization

#### Core Infrastructure (28 files - src/lib/js):
- **Network**: `net.js.erb`, `xhr.js`, `jsonp.js`
- **Crypto**: `aes.js.erb`, `rc4.js.erb`, `sha256.js.erb`, `rsa.js.erb`, `bigint.js`
- **Encoding**: `base64.js`, `json.js`, `evidences_encryption.js.erb`, `collection_encryptor.js.erb`
- **Utilities**: `utils.js`, `cookie.js`, `jenkins.js`, `error_parser.js`
- **DOM**: `DOMLoadedHelper.js.erb`, `iframe_utils.js`, `task_queue.js`
- **Detection**: `user_agent.js.erb`, `referrer.js.erb`, `device_features.js.erb`, `casper_ext.js`
- **State**: `session_id.js.erb`, `shared_object.js.erb`, `tag.js.erb`
- **Other**: `strict.js`, `team_viewer_constants.js.erb`

#### Container Framework (3 files - src/common/base/js):
- `container.js.erb` - Main application framework
- `dummy_container.js.erb` - Stub for testing
- `cover_config.js.erb` - Configuration obfuscation

#### ATO Collectors (19 files - src/ato/collectors/*/templates):
- **Behave** (6): `behave.js.erb`, `keystrokes.js.erb`, `mouse_movements.js.erb`, `metastrokes.js.erb`, `behave_utils.js.erb`, `hook_inputs.js.erb`
- **Device** (5): `device_container.js.erb`, `device_id.js.erb`, `global_device_id.js.erb`, `device_utils.js.erb`, `sensor.js.erb`
- **WISP** (4): `wisp.js.erb`, `constants.js`, `wisp_generator.js`, `serializer.js`
- **Other** (4): `user_flow.js.erb`, `carboncopy.js.erb`, `ipp.js.erb`, `remote_access_detector.js.erb`, `model_prediction.js.erb`

#### Malware Collectors (14 files - src/malware/collectors/*/templates):
- **Research** (4): `research.js.erb`, `research_snippet_api.js.erb`, `research_snippet_environment.js.erb`, `task_executor.js.erb`
- **Active** (2): `active.js.erb`, `active_iframe.js.erb`
- **Passive** (2): `passive.js.erb`, `parser.js.erb`
- **Smart Recording** (2): `smart_recording.js.erb`, `parser.js.erb`
- **Multi** (2): `multi.js.erb`, `multi_iframe.js.erb`
- **Adapters** (1): `frontend_api.js.erb`
- **Actions** (1): `status.js.erb`

#### Common Collectors (15 files - src/common/collectors/*/templates):
- **User Data** (11): `general.js.erb`, `cookies.js.erb`, `reporting.js.erb`, `user_data_utils.js`, + 7 hook files
- **Other** (4): `session_info.js.erb`, `customer_session_id.js.erb`, `client_info.js.erb`, `unified_callback.js.erb`, `diagnostic_snippet.js.erb`, `global_cookies_iframe.js.erb`

#### Intelligent Snippet/Loader (10 files - src/common/templates):
- **Intelligent Snippet** (7): `tag.js.erb`, `wrapper.js.erb`, `helper.js.erb`, `research.js.erb`, + 3 estimated_tag files
- **Other** (3): `research_wrapper.js.erb`, `cookies_monitor.js.erb`, `collectors_monitor.js.erb`

#### Obfuscation (2 files - src/lib/obfuscation/evidences_encryption/js):
- `evidences_rc4.js.erb`
- `evidences_base64.js.erb`

---

## Key Architectural Insights

1. **No Global Pollution**: Everything runs in one IIFE, no `window.*` assignments
2. **Module Pattern**: Each component is a self-contained module with public API
3. **Dependency Injection**: Container passes itself to Net via `Net._initialize(Container)`
4. **Event-Driven**: Collectors communicate via `Container._bindEvent()` / `Container._emitEvent()`
5. **Build-Time Customization**: Each application gets a tailored bundle
6. **Layered Architecture**: Utils → Net → Container → Collectors
7. **Single Bundle Output**: One concatenated JS file per snippet configuration
8. **Dynamic Loading**: HTML snippet loads the bundle asynchronously
9. **Multiple Transport Methods**: Image, JSONP, AJAX, iframe, xpost, jsonpi
10. **No WebSocket/Beacon**: Traditional HTTP-based communication only
