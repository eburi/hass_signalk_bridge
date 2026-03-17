# Claude Implementation Brief: Home Assistant SignalK Integration

Implement a Home Assistant custom integration for SignalK that connects to the SignalK websocket delta stream and creates Home Assistant entities for the vessel `self` only.

This brief is intentionally focused on SignalK ingestion, classification, update policy, and Home Assistant integration design. Do not mix in unrelated template sensor or generated text issues, except when using them as brief examples to explain why a certain design choice matters.

## Goals

- Connect to SignalK at `ws://192.168.46.222:3000/signalk/v1/stream`
- Ingest live delta updates for the vessel `self`
- Create Home Assistant entities that belong to a single HA device representing the vessel itself
- Add a `device_tracker` for the vessel self location
- Ignore all other vessels for now, including AIS targets and encountered vessels
- Avoid overwhelming Home Assistant with high-frequency updates
- Provide smart path classification into functional domains
- Make domain throttling/filtering behavior configurable at runtime
- Provide service support plus Developer Tools support for those services
- Provide an options/settings UI for important settings, especially `enable_new_sensors_by_default`, which must default to `false`

## Non-goals for this first implementation

- Do not create devices for other vessels
- Do not create one HA device per AIS target
- Do not try to fully support every obscure or vendor-specific SignalK path on day one
- Do not mirror every incoming SignalK delta directly into HA state updates

## High-level design requirements

### 1. Use websocket deltas, not polling

- Use the SignalK websocket stream for updates
- The integration should be push-based
- Home Assistant entities should use `should_poll = False`
- Maintain an internal in-memory cache of the latest values per canonical SignalK path

### 2. Never publish every delta directly into HA

This is the most important rule.

- Do not call `async_write_ha_state()` for every incoming delta
- Implement a coalescing / publish-policy layer between SignalK updates and HA entity state writes
- SignalK traffic can be much more frequent than Home Assistant should persist or process

### 3. Only handle vessel `self`

- Resolve and subscribe only to the self vessel
- Create exactly one HA device representing the vessel self
- All created entities for self must belong to that device
- Ignore all non-self vessels for now
- Ignore AIS/other vessel paths for now even if present in the SignalK model
- Keep the architecture open for future handling of other vessels, but do not implement that now

### 4. Represent self location as a device tracker

- Implement a `device_tracker` for the vessel self using `navigation.position`
- Raw position sensors may also exist if useful, but the `device_tracker` is the primary self-location representation
- Avoid creating multiple high-churn location representations by default if they are redundant

## Runtime architecture

Implement the integration around a central runtime object:

- One config entry
- One websocket client connection
- One path registry / classifier
- One in-memory latest-value store
- One publish-policy layer
- Entity instances subscribe to canonical path updates from the runtime

Recommended internal layers:

1. SignalK websocket client
2. Delta parser / normalizer
3. Canonical path mapper
4. Smart classifier
5. Publish-policy engine
6. Entity registry / entity factory
7. Runtime settings manager

## Canonical path handling

Classify and expose canonical paths only.

### Ignore these path forms by default

- any `.values.*` branches
- any `.meta.*` branches
- source-specific fanout variants
- raw metadata leaves not suitable as first-class entities
- data that is clearly only useful for debugging unless explicitly enabled

Examples of paths to ignore by default:

- `navigation.position.values.can0.4`
- `environment.wind.speedApparent.values.can0.105`
- `electrical.displays.raymarine.group1.color.meta.possibleValues.0`

### Canonicalization rules

- Strip vessel prefixes such as `vessels.self.` or `vessels.<urn>.`
- Normalize all paths to a canonical self-relative path before classification
- Prefer one HA entity per canonical SignalK path, not per source-specific value branch

## Smart classification

Implement a smart classification system that maps SignalK paths into functional domains. This should use explicit rules first, with a small amount of heuristic matching second.

The classifier should return at least:

- domain
- suggested HA platform
- suggested default enabled state
- suggested publish profile
- suggested entity metadata where possible

### Classification domains to support initially

- `alarm`
- `position`
- `navigation`
- `wind`
- `environment`
- `tank`
- `battery_dc`
- `inverter_ac`
- `engine_propulsion`
- `bilge_pump`
- `watermaker`
- `communications`
- `time`
- `status_metadata`
- `unsupported_ignore`

### Live SignalK path families observed on the current server

Observed top-level families in `vessels/self`:

- `communication`
- `design`
- `electrical`
- `entertainment`
- `environment`
- `navigation`
- `noforeignland`
- `notifications`
- `performance`
- `sensors`
- `steering`
- vessel identity fields such as `mmsi`, `name`

### Example observed paths

Alarm / notification:

- `notifications.navigation.anchor`
- `notifications.security.accessRequest.readwrite.<uuid>`
- `notifications.ais.unknown113`

Position / device tracker:

- `navigation.position`
- `navigation.gnss.methodQuality`
- `navigation.gnss.integrity`
- `navigation.gnss.horizontalDilution`
- `navigation.gnss.satellites`
- `navigation.gnss.satellitesInView`

Navigation:

- `navigation.courseOverGroundTrue`
- `navigation.courseOverGroundMagnetic`
- `navigation.headingMagnetic`
- `navigation.headingTrue`
- `navigation.speedOverGround`
- `navigation.speedThroughWater`
- `navigation.rateOfTurn`
- `navigation.log`
- `navigation.trip.log`
- `navigation.leewayAngle`
- `navigation.magneticVariation`
- `navigation.course.calcValues.crossTrackError`
- `navigation.course.calcValues.distance`
- `navigation.course.calcValues.velocityMadeGood`
- `navigation.courseGreatCircle.bearingTrackTrue`
- `navigation.courseGreatCircle.nextPoint.distance`

Wind:

- `environment.wind.angleApparent`
- `environment.wind.speedApparent`
- `environment.wind.angleTrueWater`
- `environment.wind.directionTrue`
- `environment.wind.speedTrue`
- `steering.autopilot.target.windAngleApparent`
- `performance.targetAngle`
- `performance.gybeAngle`

Environment / weather:

- `environment.depth.belowKeel`
- `environment.depth.belowSurface`
- `environment.depth.belowTransducer`
- `environment.depth.transducerToKeel`
- `environment.water.temperature`
- `environment.current.drift`
- `environment.current.setTrue`
- `environment.current.setMagnetic`
- `environment.water.waves.significantHeight`
- `environment.water.waves.period`
- `environment.water.waves.windWave.height`
- `environment.water.waves.swell1.height`
- `environment.inside.temperature`
- `environment.inside.humidity`
- `environment.inside.pressure`
- `environment.inside.airquality`
- `environment.inside.gas`
- `environment.heave`
- `environment.sunlight.times.sunrise`
- `environment.sunlight.times.sunset`
- `environment.moon.phaseName`

Communications / network:

- `communication.callsignVhf`
- `noforeignland.status`
- `noforeignland.sent_to_api`
- `noforeignland.source`

Time:

- `navigation.datetime`
- `navigation.course.calcValues.estimatedTimeOfArrival`
- `navigation.course.calcValues.timeToGo`
- `navigation.courseGreatCircle.activeRoute.startTime`
- `navigation.courseGreatCircle.nextPoint.timeToGo`
- `environment.sunlight.times.solarNoon`

Status / metadata:

- `name`
- `mmsi`
- `design.aisShipType`
- `design.draft`
- `design.length`
- `design.beam`
- `design.airHeight`
- `steering.autopilot.state`
- `steering.autopilot.target.headingMagnetic`
- `steering.rudderAngle`
- `electrical.displays.raymarine.helm1.brightness`
- `electrical.displays.raymarine.helm1.color`
- `electrical.displays.raymarine.helm1.nightMode.state`
- `entertainment.device.fusion1.state`

Unsupported / ignore examples:

- `sensors.ais.class`
- `sensors.ais.fromBow`
- `sensors.ais.fromCenter`
- `notifications.ais.*`
- any non-self `vessels.<urn>` data

### Matcher rules

Use explicit matcher rules similar to the following.

#### Alarm domain

- Match `notifications.*`
- Prioritize `notifications.navigation.*`
- `notifications.ais.*` should be ignored by default for now

#### Position domain

- Match `navigation.position`
- Match `navigation.gnss.*`
- Primary HA representation should be `device_tracker` for self

#### Navigation domain

- Match `navigation.heading*`
- Match `navigation.course*`
- Match `navigation.speed*`
- Match `navigation.rateOfTurn`
- Match `navigation.log`
- Match `navigation.trip.log`
- Match `navigation.magneticVariation`

#### Wind domain

- Match `environment.wind.*`
- Match `steering.autopilot.target.wind*`
- Match `performance.targetAngle`
- Match `performance.gybe*`

#### Environment domain

- Match `environment.depth.*`
- Match `environment.water.*`
- Match `environment.current.*`
- Match `environment.inside.*`
- Match `environment.heave`
- Match `environment.sunlight.*`
- Match `environment.moon*`

#### Tank domain

- Match `tanks.*`
- Match `tank.*`

#### Battery / DC electrical domain

- Match `electrical.batteries.*`
- Match `electrical.dc.*`
- Match `electrical.solar.*`
- Match `electrical.alternators.*`
- Do not treat `electrical.displays.*` as battery/DC telemetry

#### Inverter / AC electrical domain

- Match `electrical.inverters.*`
- Match `electrical.ac.*`
- Match `electrical.shorePower.*`
- Match `electrical.generators.*`

#### Engine / propulsion domain

- Match `propulsion.*`
- Match `engines.*`

#### Bilge / pump domain

- Match `bilge.*`
- Match `pumps.*`
- Also allow notification paths containing bilge semantics to map here if needed later

#### Watermaker domain

- Match `watermaker.*`
- Match `watermakers.*`

#### Communications domain

- Match `communication.*`
- Optional vendor/app-specific communication-related branches like `noforeignland.*` can map here or to status/metadata depending on value type

#### Time domain

- Match `navigation.datetime`
- Match `*.estimatedTimeOfArrival`
- Match `*.timeToGo`
- Match `*.startTime`
- Match `environment.sunlight.times.*`
- Match `environment.moon.times.*`

#### Status / metadata domain

- Match `name`
- Match `mmsi`
- Match `design.*`
- Match `steering.autopilot.state`
- Match `steering.rudderAngle`
- Match `entertainment.*`
- Match `electrical.displays.*`

#### Unsupported / ignore domain

- Match any `.values.*`
- Match any `.meta.*`
- Match `sensors.ais.*`
- Match `notifications.ais.*`
- Match any non-self `vessels.<urn>` data

### Smart classification behavior

Implement classification in layers:

1. explicit exact-path matches
2. explicit prefix matches
3. segment-based heuristics
4. fallback to `unsupported_ignore`

Also:

- Store the classification result so services/options can operate per domain
- Make the classifier easy to extend with additional path families later
- Keep ignored-path reporting available for debugging, but do not create entities for ignored paths by default

## Entity creation policy

### Default behavior for new entities

- `enable_new_sensors_by_default` must exist
- Default value must be `false`
- When `false`, newly discovered eligible sensor entities should be created disabled by default
- Critical alarms may be treated specially if needed, but keep the default conservative

### Suggested HA entity handling

- Self vessel should be one HA device
- All created self entities belong to that device
- Position should also create/update a `device_tracker`
- Consider creating regular sensor entities only for high-value canonical data, not raw source fanout branches

### Important principle

Prefer useful operational entities over full raw-path mirroring.

## Update / publish policy

Each domain must support configurable throttling and filtering.

Implement both:

- minimum publish interval
- deadband / significant-change threshold
- maximum refresh interval

This means an entity is published when:

- the value changed enough, and the minimum interval is satisfied, or
- the maximum refresh interval has elapsed, or
- availability/state transition semantics require immediate publication

### Suggested default profiles

Provide at least these domain-oriented defaults:

- `alarm`: publish immediately
- `position`: publish every `5-10s` or when moved more than `10-25m`
- `navigation`: publish every `1-2s` with sensible deadband
- `wind`: publish every `1-2s` with sensible deadband
- `environment`: publish every `5-30s` depending on subtype
- `tank`: publish every `15-60s`
- `battery_dc`: publish every `5-30s`
- `inverter_ac`: publish every `2-10s`
- `engine_propulsion`: publish every `1-5s`
- `bilge_pump`: publish immediately for state changes, slower for counters/telemetry
- `watermaker`: publish every `10-30s`
- `communications`: publish on change or slow refresh
- `time`: publish on change with cautious throttling for countdown/ETA-type values
- `status_metadata`: publish slowly or on meaningful change

### Suggested deadband examples

- position: movement in meters rather than tiny coordinate changes
- heading / course / wind angle: degrees threshold
- speed: speed delta threshold
- tank / battery / temperature: domain-appropriate numeric threshold

Make these configurable per domain.

## Services and Developer Tools support

Provide integration services so runtime settings can be adjusted without restarting HA.

These services must appear in Home Assistant Developer Tools.

### Required service capabilities

Implement service support for at least:

1. update domain policy
2. reset domain policy to defaults
3. enable entity/entities
4. disable entity/entities
5. rescan/reclassify known paths
6. list current classifier or policy state for debugging

### Example service concepts

These are conceptual requirements; exact service names may vary, but keep them clear and integration-scoped.

- `signalk.set_domain_policy`
  - inputs such as:
    - `domain`
    - `min_interval_seconds`
    - `max_interval_seconds`
    - `deadband`
    - `enabled_by_default`

- `signalk.reset_domain_policy`
  - inputs:
    - `domain`

- `signalk.set_discovery_defaults`
  - inputs such as:
    - `enable_new_sensors_by_default`

- `signalk.rescan_paths`
- `signalk.reclassify_paths`
- `signalk.dump_runtime_state`

### Developer Tools support expectations

- Register services with proper field selectors and descriptions
- Make service schemas usable from Developer Tools without needing internal knowledge
- Include good descriptions for domains and fields
- Expose current policies and settings clearly enough that a user can inspect what the integration is doing

## Integration options / menu support

Provide a settings UI via the integration options flow.

At minimum, expose:

- `enable_new_sensors_by_default` (default `false`)
- default publish profile (`conservative`, `balanced`, `realtime`) or equivalent
- domain-level overrides for important domains like:
  - `position`
  - `navigation`
  - `wind`
  - `environment`
  - `battery_dc`
  - `tank`
  - `alarm`
- whether raw/diagnostic entities should be created at all
- whether ignored/unsupported paths should be logged for diagnostics

This can be implemented with an options flow rather than a custom frontend panel. The UI only needs to cover the most important settings cleanly.

## Discovery behavior

Implement discovery carefully.

- Discover candidate canonical paths from incoming deltas and/or initial data snapshot if available
- Classify each candidate path
- Only create entities for supported domains and supported value types
- New entities should obey `enable_new_sensors_by_default`
- Ignored paths should be tracked internally for debug purposes, but not exposed as active entities by default

## Availability and reconnect behavior

- Reconnect websocket automatically with backoff
- Mark entities unavailable on true connection loss
- On reconnect, rebuild or refresh the latest in-memory state in a controlled way
- Do not flood Home Assistant with a burst of state writes after reconnect
- Reapply publish policies after reconnect before writing entity states

## Notes about ignored vessels and AIS

This is important:

- Do not create entities or devices for other vessels right now
- Do not create devices for AIS targets
- If other-vessel data exists in SignalK, ignore it at the integration level for now
- Keep future architecture open for later support, but the current version must stay self-only

## Implementation quality expectations

- Keep the classifier modular and testable
- Keep publish-policy logic independent of entity classes so it can be unit tested
- Make domain defaults explicit in code, not implicit magic numbers scattered across files
- Use clear typing and data models for classifier results and policy objects
- Add logging that is useful for debugging classification and throttling decisions without being noisy by default

## Concrete design intent summary

Build a self-vessel-only SignalK integration for Home Assistant that:

- consumes websocket deltas
- classifies canonical SignalK paths into smart domains
- creates a single self vessel device plus related entities
- creates a `device_tracker` for self position
- ignores other vessels and AIS targets for now
- never mirrors raw delta frequency directly into HA
- exposes runtime-configurable domain policies via services
- supports those services cleanly in Developer Tools
- provides an integration options UI for the most important settings
- defaults to conservative discovery behavior, especially `enable_new_sensors_by_default = false`