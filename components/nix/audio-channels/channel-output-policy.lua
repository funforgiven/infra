local linking_utils = require ("linking-utils")
local log = Log.open_topic ("s-funforgiven-channel-output")

local CHANNEL_PROPERTY = "funforgiven.audio.channel"
local KIND_PROPERTY = "funforgiven.audio.kind"
local CHANNEL_NODE_PREFIX = "funforgiven.audio.channel."
local STATE_NAME = "funforgiven-channel-output-targets"
local TARGET_KEY = "target.object"
local MOVE_REQUEST_KEY = "funforgiven.audio.move-output-target"
local MOVE_ACK_KEY = "funforgiven.audio.move-output-target-ack"
local MOVE_ERROR_KEY = "funforgiven.audio.move-output-target-error"
local RESET_KEY = "funforgiven.audio.reset-output-target"
local RESET_COMMIT_KEY = "funforgiven.audio.reset-output-target-commit"
local RESET_ACK_KEY = "funforgiven.audio.reset-output-target-ack"
local RESET_ERROR_KEY = "funforgiven.audio.reset-output-target-error"

local state = State (STATE_NAME)
local state_table = state:load ()
local pending_moves = {}
local pending_resets = {}

local function starts_with (value, prefix)
  return type (value) == "string" and value:sub (1, #prefix) == prefix
end

local function property_is_true (value)
  return value == true or value == 1 or value == "true" or value == "yes" or
    value == "1"
end

local function canonical_global_id (value)
  if type (value) == "string" then
    if value ~= "0" and not value:match ("^[1-9]%d*$") then
      return nil
    end
  elseif type (value) ~= "number" then
    return nil
  end

  local numeric = tonumber (value)
  if not numeric or numeric < 0 or numeric > 4294967294 or
      numeric % 1 ~= 0 then
    return nil
  end

  return string.format ("%.0f", numeric)
end

local function canonical_object_serial (value)
  if type (value) == "number" then
    if value < 0 or value > 9007199254740991 or value % 1 ~= 0 then
      return nil
    end
    value = string.format ("%.0f", value)
  elseif type (value) ~= "string" then
    return nil
  end

  if value ~= "0" and not value:match ("^[1-9]%d*$") then
    return nil
  end
  if #value > 20 or
      (#value == 20 and value > "18446744073709551615") then
    return nil
  end
  return value
end

local function node_id (node)
  local id = node and node ["bound-id"]
  return canonical_global_id (id)
end

local function get_default_metadata (source)
  local metadata_om = source:call ("get-object-manager", "metadata")
  if not metadata_om then
    return nil
  end

  return metadata_om:lookup {
    Constraint { "metadata.name", "=", "default" },
  }
end

local function bridge_channel (bridge)
  local props = bridge.properties
  if props [KIND_PROPERTY] ~= "bridge" then
    return nil, nil
  end

  local channel = props [CHANNEL_PROPERTY]
  local definition = channels [channel]
  if not definition then
    return nil, "missing or unknown " .. CHANNEL_PROPERTY
  end

  local name = props ["node.name"]
  if name ~= definition.bridge then
    return nil, string.format (
      "bridge for channel '%s' has node.name '%s', expected '%s'",
      channel, tostring (name), definition.bridge)
  end

  if props ["media.class"] ~= "Stream/Output/Audio" then
    return nil, string.format (
      "bridge for channel '%s' is not Stream/Output/Audio", channel)
  end
  if not property_is_true (props ["node.passive"]) or
      not property_is_true (props ["node.dont-fallback"]) or
      not property_is_true (props ["node.linger"]) or
      property_is_true (props ["node.dont-reconnect"]) or
      property_is_true (props ["node.dont-move"]) or
      tostring (props [TARGET_KEY]) ~= "-1" then
    return nil, string.format (
      "bridge for channel '%s' violates passive/linger/moving/-1 safety properties",
      channel)
  end

  return channel, nil
end

local function add_edge (adjacency, output_id, input_id)
  if not output_id or not input_id then
    return false
  end

  adjacency [output_id] = adjacency [output_id] or {}
  table.insert (adjacency [output_id], input_id)
  return true
end

local function would_create_cycle (bridge, candidate, nodes_om, links_om)
  local bridge_id = node_id (bridge)
  local candidate_id = node_id (candidate)
  if not bridge_id or not candidate_id then
    return true
  end
  if bridge_id == candidate_id then
    return true
  end
  if not nodes_om or not links_om then
    return true
  end

  local adjacency = {}
  local live_node_ids = {}
  local loopback_nodes = {}
  for node in nodes_om:iterate () do
    local id = node_id (node)
    if not id or live_node_ids [id] then
      return true
    end
    live_node_ids [id] = true

    local props = node.properties
    local channel = props [CHANNEL_PROPERTY]
    local definition = channels [channel]
    local name = props ["node.name"]
    local kind = props [KIND_PROPERTY]

    if definition and kind == "sink" and name == definition.sink then
      loopback_nodes [channel] = loopback_nodes [channel] or {}
      if loopback_nodes [channel].sink and
          loopback_nodes [channel].sink ~= id then
        return true
      end
      loopback_nodes [channel].sink = id
    elseif definition and kind == "bridge" and name == definition.bridge then
      loopback_nodes [channel] = loopback_nodes [channel] or {}
      if loopback_nodes [channel].bridge and
          loopback_nodes [channel].bridge ~= id then
        return true
      end
      loopback_nodes [channel].bridge = id
    end
  end

  for link in links_om:iterate () do
    local props = link.properties
    local output_id = canonical_global_id (props ["link.output.node"])
    local input_id = canonical_global_id (props ["link.input.node"])
    if not output_id or not input_id or not live_node_ids [output_id] or
        not live_node_ids [input_id] then
      return true
    end
    add_edge (adjacency, output_id, input_id)
  end

  for _, pair in pairs (loopback_nodes) do
    if pair.sink and pair.bridge then
      add_edge (adjacency, pair.sink, pair.bridge)
    end
  end

  local visited = { [candidate_id] = true }
  local queue = { candidate_id }
  local index = 1
  while index <= #queue do
    local current = queue [index]
    index = index + 1

    if current == bridge_id then
      return true
    end

    for _, next_id in ipairs (adjacency [current] or {}) do
      if not visited [next_id] then
        visited [next_id] = true
        table.insert (queue, next_id)
      end
    end
  end

  return false
end

local function resolve_saved_target (saved_name, nodes_om)
  local matches = {}

  for node in nodes_om:iterate () do
    local props = node.properties
    if props ["node.name"] == saved_name or
        props ["object.path"] == saved_name then
      table.insert (matches, node)
    end
  end

  if #matches == 0 then
    return nil, "absent"
  end
  if #matches > 1 then
    return nil, "ambiguous"
  end
  if matches [1].properties ["node.name"] ~= saved_name then
    return nil, "path-alias"
  end
  return matches [1], "unique"
end

local function eligible_physical_sink (
    candidate, bridge, nodes_om, links_om, devices_om)
  if not candidate then
    return false, "target serial does not identify a live node"
  end

  local props = candidate.properties
  local name = props ["node.name"]
  if props ["media.class"] ~= "Audio/Sink" then
    return false, "target is not an Audio/Sink"
  end
  if property_is_true (props ["node.disabled"]) or
      property_is_true (props ["device.disabled"]) then
    return false, "target is disabled or unavailable"
  end
  local node_state = candidate:get_state ()
  if node_state == "error" then
    return false, "target is in the PipeWire error state"
  end
  if type (name) ~= "string" or name == "" then
    return false, "target has no stable node.name"
  end
  if tonumber (name) ~= nil then
    return false, "target node.name would be interpreted as an object serial"
  end

  local resolved, resolution = resolve_saved_target (name, nodes_om)
  if resolution ~= "unique" or resolved ~= candidate then
    return false,
      "target node.name collides with another node.name or object.path"
  end

  local device_id = canonical_global_id (props ["device.id"])
  if not device_id or not devices_om then
    return false, "target is not device-backed"
  end
  local device = devices_om:lookup {
    Constraint { "bound-id", "=", device_id, type = "gobject" },
  }
  if not device then
    return false, "target does not reference one live PipeWire device"
  end
  if not linking_utils.haveAvailableRoutes (props, devices_om) then
    return false, "target has no available hardware route"
  end

  if props [CHANNEL_PROPERTY] ~= nil or props [KIND_PROPERTY] ~= nil or
      starts_with (name, CHANNEL_NODE_PREFIX) then
    return false, "target is a funforgiven channel node"
  end
  if property_is_true (props ["node.virtual"]) or
      property_is_true (props ["wireplumber.is-virtual"]) or
      property_is_true (props ["wireplumber.is-fallback"]) or
      property_is_true (props ["bluez5.loopback"]) then
    return false, "target is virtual or a policy fallback"
  end
  -- WirePlumber implements UCM SplitPCM hardware outputs with loopbacks.
  -- They retain their ALSA device/route identity and are not effect filters.
  local alsa_split = props ["device.api"] == "alsa" and
    props ["api.alsa.pcm.stream"] == "playback" and
    type (props ["api.alsa.split.name"]) == "string" and
    props ["api.alsa.split.name"] ~= "" and
    type (props ["api.alsa.split.position"]) == "string" and
    props ["api.alsa.split.position"] ~= ""
  if (props ["node.link-group"] ~= nil and not alsa_split) or
      props ["filter.smart"] ~= nil or
      props ["filter.smart.name"] ~= nil or
      props ["filter.smart.target"] ~= nil then
    return false, "target is a filter endpoint"
  end
  if props ["factory.name"] == "support.null-audio-sink" then
    return false, "target is a null/virtual sink"
  end
  if would_create_cycle (bridge, candidate, nodes_om, links_om) then
    return false, "target would create an audio graph cycle"
  end

  return true, nil
end

local function choose_neutral_target (bridge, nodes_om, links_om, devices_om)
  local candidates = {}

  for node in nodes_om:iterate {
    Constraint { "media.class", "=", "Audio/Sink", type = "pw-global" },
  } do
    local eligible = eligible_physical_sink (
      node, bridge, nodes_om, links_om, devices_om)
    if eligible then
      local props = node.properties
      table.insert (candidates, {
        node = node,
        name = props ["node.name"],
        priority = tonumber (props ["priority.session"]) or 0,
      })
    end
  end

  table.sort (candidates, function (left, right)
    if left.priority ~= right.priority then
      return left.priority > right.priority
    end
    return left.name < right.name
  end)

  return candidates [1]
end

local function set_target_metadata (source, bridge, target_name)
  local metadata = get_default_metadata (source)
  local subject_id = bridge ["bound-id"]
  if not metadata or not subject_id then
    log:warning (bridge,
      "default metadata is unavailable; the declarative target.object=-1 " ..
      "sentinel keeps this channel bridge unassigned until metadata returns")
    return false
  end

  local value = target_name or "-1"
  local succeeded, result = pcall (
    metadata.set, metadata, subject_id, TARGET_KEY, "Spa:String", value)
  if not succeeded or result == false then
    log:warning (bridge, string.format (
      "could not publish target metadata: %s", tostring (result)))
    return false
  end
  return true
end

local function set_control_metadata (source, bridge, key, value)
  local metadata = get_default_metadata (source)
  local subject_id = bridge ["bound-id"]
  if not metadata or not subject_id then
    return false
  end

  local succeeded, result = pcall (
    metadata.set, metadata, subject_id, key, "Spa:String", value)
  if not succeeded or result == false then
    return false
  end
  return true
end

local function clear_control_metadata (source, bridge, key)
  local metadata = get_default_metadata (source)
  local subject_id = bridge ["bound-id"]
  if not metadata or not subject_id then
    return false
  end

  local succeeded, result = pcall (
    metadata.set, metadata, subject_id, key, nil, nil)
  return succeeded and result ~= false
end

local function clear_subject_control_metadata (source, subject_id)
  local metadata = get_default_metadata (source)
  subject_id = canonical_global_id (subject_id)
  if not metadata or not subject_id then
    return false
  end

  local cleared = true
  for _, key in ipairs {
    MOVE_REQUEST_KEY,
    MOVE_ACK_KEY,
    MOVE_ERROR_KEY,
    RESET_KEY,
    RESET_COMMIT_KEY,
    RESET_ACK_KEY,
    RESET_ERROR_KEY,
  } do
    local succeeded, result = pcall (
      metadata.set, metadata, tonumber (subject_id), key, nil, nil)
    if not succeeded or result == false then
      cleared = false
    end
  end
  return cleared
end

local function report_result (source, bridge, key, value)
  if not set_control_metadata (source, bridge, key, value) then
    log:warning (bridge, "could not publish the output transaction result")
    return false
  end
  return true
end

-- Publishes a transaction result and remembers it so a replayed request can
-- be answered with the same result.
local function publish_pending_result (source, bridge, pending, key, value)
  pending.result_key = key
  pending.result_value = value
  return report_result (source, bridge, key, value)
end

local function publish_pending_error (source, bridge, pending, code)
  return publish_pending_result (
    source, bridge, pending, pending.error_key, pending.nonce .. ":" .. code)
end

local function save_channel_target (channel, target_name, defer_save)
  if state_table [channel] == target_name then
    return
  end

  state_table [channel] = target_name
  if defer_save ~= false then
    state:save_after_timeout (state_table)
  end
end

local function valid_saved_name (name)
  return type (name) == "string" and name ~= "" and name ~= "-1" and
    tonumber (name) == nil and not starts_with (name, CHANNEL_NODE_PREFIX)
end

local function channel_topology_is_unique (channel, nodes_om)
  local definition = channels [channel]
  local sink_count = 0
  local bridge_count = 0

  for node in nodes_om:iterate () do
    local props = node.properties
    if props [CHANNEL_PROPERTY] == channel and
        props [KIND_PROPERTY] == "sink" and
        props ["node.name"] == definition.sink then
      sink_count = sink_count + 1
    elseif props [CHANNEL_PROPERTY] == channel and
        props [KIND_PROPERTY] == "bridge" and
        props ["node.name"] == definition.bridge then
      bridge_count = bridge_count + 1
    end
  end

  return sink_count == 1 and bridge_count == 1
end

local function restore_or_bootstrap (source, bridge, channel, defer_save)
  local nodes_om = source:call ("get-object-manager", "node")
  local links_om = source:call ("get-object-manager", "link")
  local devices_om = source:call ("get-object-manager", "device")
  if not nodes_om or not links_om or not devices_om then
    log:warning (bridge,
      string.format ("cannot inspect graph for channel '%s'; leaving bridge unassigned", channel))
    return set_target_metadata (source, bridge, nil)
  end
  if not channel_topology_is_unique (channel, nodes_om) then
    log:warning (bridge, string.format (
      "channel '%s' does not have exactly one expected sink and bridge; leaving it unassigned",
      channel))
    return set_target_metadata (source, bridge, nil)
  end

  local saved_name = state_table [channel]
  if saved_name ~= nil then
    if not valid_saved_name (saved_name) then
      log:warning (bridge, string.format (
        "saved target '%s' for channel '%s' is malformed or unsafe; " ..
        "leaving it unassigned (use forget-bridge-target to replace this entry)",
        tostring (saved_name), channel))
      return set_target_metadata (source, bridge, nil)
    end

    local live_target, resolution = resolve_saved_target (saved_name, nodes_om)
    if resolution ~= "unique" and resolution ~= "absent" then
      log:warning (bridge, string.format (
        "saved target '%s' for channel '%s' has unsafe %s resolution " ..
        "across node.name/object.path; leaving it unassigned",
        saved_name, channel, resolution))
      return set_target_metadata (source, bridge, nil)
    end
    if live_target then
      local eligible, reason =
        eligible_physical_sink (
          live_target, bridge, nodes_om, links_om, devices_om)
      if not eligible then
        log:warning (bridge, string.format (
          "saved target '%s' for channel '%s' is currently unsafe: %s; " ..
          "leaving it unassigned (use forget-bridge-target to select again)",
          saved_name, channel, reason))
        return set_target_metadata (source, bridge, nil)
      end
    end

    local restored = set_target_metadata (source, bridge, saved_name)
    if restored then
      log:info (bridge, string.format (
        "restored channel '%s' target '%s'%s",
        channel, saved_name, live_target and "" or " (currently absent; waiting)"))
    end
    return restored
  end

  local selected = choose_neutral_target (
    bridge, nodes_om, links_om, devices_om)
  if selected then
    save_channel_target (channel, selected.name, defer_save)
    local selected_target = set_target_metadata (source, bridge, selected.name)
    if selected_target then
      log:info (bridge, string.format (
        "selected first-use target '%s' for channel '%s' " ..
        "(priority.session=%d)", selected.name, channel, selected.priority))
    end
    return selected_target
  else
    local cleared = set_target_metadata (source, bridge, nil)
    log:warning (bridge, string.format (
      "no eligible live physical Audio/Sink for channel '%s'; bridge remains " ..
      "unassigned (use forget-bridge-target after a device becomes available)",
      channel))
    return cleared
  end
end

-- Restores PREVIOUS_TARGET after a failed transaction step, logs FAILURE (and
-- its optional DETAIL) with the rollback outcome, and returns whether the live
-- target and durable state were restored.
local function roll_back_target (
    source, bridge, channel, previous_target, persist_rollback, failure, detail)
  state_table [channel] = previous_target
  local live_restored = restore_or_bootstrap (
    source, bridge, channel, false)

  local durable_saved, save_error = true, nil
  if persist_rollback then
    local saved, rollback_error = state:save (state_table)
    if not saved then
      state:save_after_timeout (state_table)
      durable_saved, save_error = false, rollback_error
    end
  end

  log:warning (bridge, string.format (
    "%s for channel '%s'%s; live target metadata %s; durable state %s%s",
    failure, channel,
    detail ~= nil and ": " .. tostring (detail) or "",
    live_restored and "restored" or "NOT restored",
    durable_saved and "restored" or "NOT restored",
    durable_saved and "" or
      ": " .. tostring (save_error or "unknown error")))
  return live_restored, durable_saved
end

local function rollback_result_code (
    live_restored, durable_saved, complete_code)
  if live_restored and durable_saved then
    return complete_code
  end
  if not live_restored and not durable_saved then
    return "rollback-incomplete"
  end
  if not live_restored then
    return "rollback-live"
  end
  return "rollback-save"
end

local function pending_matches_bridge (pending, bridge)
  if not pending then
    return false
  end
  return pending.subject == node_id (bridge) and
    pending.bridge_serial == canonical_object_serial (
      bridge.properties ["object.serial"])
end

local function purge_stale_pending_transactions (source, bridge, channel)
  local active_move = pending_moves [channel]
  if active_move and not pending_matches_bridge (active_move, bridge) then
    pending_moves [channel] = nil
    clear_subject_control_metadata (source, active_move.subject)
    log:warning (bridge,
      "discarded durable output move after bridge identity teardown")
  end

  local active_reset = pending_resets [channel]
  if active_reset and not pending_matches_bridge (active_reset, bridge) then
    pending_resets [channel] = nil
    clear_subject_control_metadata (source, active_reset.subject)
    log:warning (bridge,
      "discarded output reset after bridge identity teardown")
  end
end

local function quarantine_malformed_bridge (source, bridge, reason)
  set_target_metadata (source, bridge, nil)
  log:warning (bridge,
    "refusing channel-output policy for malformed marked bridge: " .. reason)
end

local function restore_active_bridges (source, trigger)
  local nodes_om = source:call ("get-object-manager", "node")
  if not nodes_om then
    log:warning (string.format (
      "cannot revalidate channel outputs after %s: node object manager is unavailable",
      trigger))
    return
  end

  for bridge in nodes_om:iterate {
    Constraint { KIND_PROPERTY, "=", "bridge", type = "pw" },
  } do
    local channel, reason = bridge_channel (bridge)
    if channel then
      purge_stale_pending_transactions (source, bridge, channel)
      restore_or_bootstrap (source, bridge, channel)
    else
      quarantine_malformed_bridge (source, bridge, reason or "unknown error")
    end
  end
end

SimpleEventHook {
  name = "funforgiven/channel-output/setup-bridge",
  before = { "node/restore-stream", "node/create-item" },
  interests = {
    EventInterest {
      Constraint { "event.type", "=", "node-added" },
      Constraint { KIND_PROPERTY, "=", "bridge" },
    },
  },
  execute = function (event)
    local bridge = event:get_subject ()
    local source = event:get_source ()
    local channel, reason = bridge_channel (bridge)
    if not channel then
      quarantine_malformed_bridge (source, bridge, reason or "unknown error")
      event:stop_processing ()
      return
    end

    purge_stale_pending_transactions (source, bridge, channel)
    restore_or_bootstrap (source, bridge, channel)
  end,
}:register ()

SimpleEventHook {
  name = "funforgiven/channel-output/teardown-bridge",
  interests = {
    EventInterest {
      Constraint { "event.type", "=", "node-removed" },
    },
  },
  execute = function (event)
    local source = event:get_source ()
    local event_props = event:get_properties () or {}
    local subject_id = canonical_global_id (
      event_props ["event.subject.id"])
    if not subject_id then
      return
    end
    local had_transaction = false

    for channel_id in pairs (channels) do
      local active_move = pending_moves [channel_id]
      local active_reset = pending_resets [channel_id]
      if active_move and active_move.subject == subject_id then
        had_transaction = true
        pending_moves [channel_id] = nil
      end
      if active_reset and active_reset.subject == subject_id then
        had_transaction = true
        pending_resets [channel_id] = nil
      end
    end

    if had_transaction and
        not clear_subject_control_metadata (source, subject_id) then
      log:warning (string.format (
        "could not clear output transaction metadata during teardown of subject %s",
        subject_id))
    end
    if had_transaction then
      log:warning (string.format (
        "discarded active output transaction during teardown of bridge subject %s",
        subject_id))
    end
  end,
}:register ()

SimpleEventHook {
  name = "funforgiven/channel-output/revalidate-graph",
  before = "node/create-item",
  interests = {
    EventInterest {
      Constraint { "event.type", "=", "node-added" },
    },
    EventInterest {
      Constraint { "event.type", "=", "node-removed" },
    },
    EventInterest {
      Constraint { "event.type", "=", "device-added" },
    },
    EventInterest {
      Constraint { "event.type", "=", "device-removed" },
    },
    EventInterest {
      Constraint { "event.type", "=", "link-added" },
    },
    EventInterest {
      Constraint { "event.type", "=", "link-removed" },
    },
    EventInterest {
      Constraint { "event.type", "=", "node-state-changed" },
      Constraint { "media.class", "=", "Audio/Sink" },
    },
    EventInterest {
      Constraint { "event.type", "=", "device-params-changed" },
      Constraint { "event.subject.param-id", "c", "Route", "EnumRoute" },
    },
  },
  execute = function (event)
    restore_active_bridges (event:get_source (),
      event:get_properties () ["event.type"] or "graph change")
  end,
}:register ()

-- Metadata handlers run after purge_stale_pending_transactions, so any pending
-- transaction for CHANNEL belongs to the current bridge identity. Each handler
-- returns true when later hooks must not process the event.

local function handle_move_request (source, bridge, channel, value, value_type)
  local active_move = pending_moves [channel]
  if value == nil then
    pending_moves [channel] = nil
    clear_control_metadata (source, bridge, MOVE_ACK_KEY)
    clear_control_metadata (source, bridge, MOVE_ERROR_KEY)
    return true
  end

  local function restore_active_request ()
    if active_move then
      set_control_metadata (
        source, bridge, MOVE_REQUEST_KEY,
        active_move.nonce .. ":" .. active_move.target_serial)
    end
  end

  local move_nonce, nonce_bridge_serial, requested_serial
  if type (value) == "string" then
    move_nonce, nonce_bridge_serial, requested_serial =
      value:match ("^((%d+):%d+:%d+:%d+):(%d+)$")
  end
  local subject = node_id (bridge)
  local bridge_serial = canonical_object_serial (
    bridge.properties ["object.serial"])
  nonce_bridge_serial = canonical_object_serial (nonce_bridge_serial)
  requested_serial = canonical_object_serial (requested_serial)
  if value_type ~= "Spa:String" or not move_nonce or not subject or
      not bridge_serial or not nonce_bridge_serial or not requested_serial then
    log:warning (bridge, "rejected malformed durable output move request")
    restore_active_request ()
    return true
  end

  if nonce_bridge_serial ~= bridge_serial then
    log:warning (bridge, "rejected durable output move with stale bridge identity")
    report_result (
      source, bridge, MOVE_ERROR_KEY, move_nonce .. ":stale-identity")
    restore_active_request ()
    return true
  end

  if pending_resets [channel] then
    log:warning (bridge, "rejected durable output move while a reset is active")
    report_result (source, bridge, MOVE_ERROR_KEY, move_nonce .. ":busy")
    return true
  end

  if active_move then
    if active_move.nonce ~= move_nonce or
        active_move.target_serial ~= requested_serial then
      log:warning (bridge, "rejected overlapping durable output move")
      report_result (source, bridge, MOVE_ERROR_KEY, move_nonce .. ":busy")
      restore_active_request ()
      return true
    end
    report_result (
      source, bridge, active_move.result_key, active_move.result_value)
    return false
  end

  local pending_move = {
    nonce = move_nonce,
    subject = subject,
    bridge_serial = bridge_serial,
    target_serial = requested_serial,
    error_key = MOVE_ERROR_KEY,
  }
  pending_moves [channel] = pending_move
  if not publish_pending_result (
      source, bridge, pending_move, MOVE_ACK_KEY, move_nonce .. ":armed") then
    publish_pending_error (source, bridge, pending_move, "arm-publish")
  end
  return false
end

local function handle_reset_request (source, bridge, channel, value, value_type)
  local active_reset = pending_resets [channel]
  if value == nil then
    pending_resets [channel] = nil
    clear_control_metadata (source, bridge, RESET_COMMIT_KEY)
    clear_control_metadata (source, bridge, RESET_ACK_KEY)
    clear_control_metadata (source, bridge, RESET_ERROR_KEY)
    return true
  end

  local subject = node_id (bridge)
  local bridge_serial = canonical_object_serial (
    bridge.properties ["object.serial"])
  local nonce_bridge_serial = canonical_object_serial (
    type (value) == "string" and value:match ("^(%d+):%d+:%d+:%d+$") or nil)
  if value_type ~= "Spa:String" or not subject or not bridge_serial or
      not nonce_bridge_serial then
    log:warning (bridge, "rejected malformed output reset request")
    if active_reset then
      set_control_metadata (source, bridge, RESET_KEY, active_reset.nonce)
    end
    return true
  end

  if nonce_bridge_serial ~= bridge_serial then
    log:warning (bridge, "rejected output reset with stale bridge identity")
    report_result (source, bridge, RESET_ERROR_KEY, value .. ":stale-identity")
    return true
  end

  if pending_moves [channel] then
    log:warning (bridge, "rejected output reset while a durable move is active")
    report_result (source, bridge, RESET_ERROR_KEY, value .. ":busy")
    return true
  end

  if active_reset then
    if active_reset.nonce ~= value then
      log:warning (bridge, "rejected overlapping output reset")
      report_result (source, bridge, RESET_ERROR_KEY, value .. ":busy")
      set_control_metadata (source, bridge, RESET_KEY, active_reset.nonce)
      return true
    end
    report_result (
      source, bridge, active_reset.result_key, active_reset.result_value)
    return false
  end

  local pending_reset = {
    nonce = value,
    subject = subject,
    bridge_serial = bridge_serial,
    committed = false,
    error_key = RESET_ERROR_KEY,
  }
  pending_resets [channel] = pending_reset
  if not publish_pending_result (
      source, bridge, pending_reset, RESET_ACK_KEY, value .. ":armed") then
    publish_pending_error (source, bridge, pending_reset, "arm-publish")
  end
  return false
end

local function handle_reset_commit (source, bridge, channel, value, value_type)
  if value == nil then
    return true
  end

  local pending_reset = pending_resets [channel]
  if not pending_reset then
    log:warning (bridge, "ignored output reset commit without an active request")
    return true
  end
  if value_type ~= "Spa:String" or value ~= pending_reset.nonce then
    publish_pending_error (source, bridge, pending_reset, "invalid-commit")
    return true
  end
  if pending_reset.committed then
    report_result (
      source, bridge, pending_reset.result_key, pending_reset.result_value)
    return true
  end
  pending_reset.committed = true

  local previous_target = state_table [channel]
  state_table [channel] = nil
  log:info (bridge, string.format (
    "forgot saved target for channel '%s'; running neutral selection", channel))
  if not restore_or_bootstrap (source, bridge, channel, false) then
    local live_restored, durable_saved = roll_back_target (
      source, bridge, channel, previous_target, false,
      "could not publish the neutral output reset")
    publish_pending_error (source, bridge, pending_reset,
      rollback_result_code (live_restored, durable_saved, "metadata-publish"))
    return true
  end

  local saved, save_error = state:save (state_table)
  if not saved then
    local live_restored, durable_saved = roll_back_target (
      source, bridge, channel, previous_target, false,
      "could not persist output reset", save_error)
    publish_pending_error (source, bridge, pending_reset,
      rollback_result_code (live_restored, durable_saved, "state-save"))
    return true
  end

  if not publish_pending_result (
      source, bridge, pending_reset, RESET_ACK_KEY, pending_reset.nonce) then
    local live_restored, durable_saved = roll_back_target (
      source, bridge, channel, previous_target, true,
      "could not acknowledge output reset")
    publish_pending_error (source, bridge, pending_reset,
      rollback_result_code (live_restored, durable_saved, "ack-publish"))
  end
  return true
end

local function handle_target_change (
    source, bridge, channel, value, value_type, nodes_om)
  if value == nil then
    state_table [channel] = nil
    state:save_after_timeout (state_table)
    log:info (bridge, string.format (
      "forgot saved target for channel '%s'; running neutral selection", channel))
    restore_or_bootstrap (source, bridge, channel)
    return true
  end

  local pending_move = pending_moves [channel]
  local links_om = source:call ("get-object-manager", "link")
  local devices_om = source:call ("get-object-manager", "device")

  -- The policy itself publishes the saved node.name; leave it alone while
  -- that target is absent (waiting) or still safe.
  if value_type == "Spa:String" and valid_saved_name (value) and
      state_table [channel] == value then
    local live_target, resolution = resolve_saved_target (value, nodes_om)
    if resolution == "absent" then
      return false
    end
    if resolution == "unique" and eligible_physical_sink (
        live_target, bridge, nodes_om, links_om, devices_om) then
      return false
    end
  end

  local function reject (code, message)
    log:warning (bridge, message)
    local restored = restore_or_bootstrap (source, bridge, channel)
    if pending_move then
      publish_pending_error (source, bridge, pending_move,
        rollback_result_code (restored, true, code))
    end
    return true
  end

  if value_type ~= "Spa:Id" or type (value) ~= "string" or
      not value:match ("^%d+$") then
    return reject ("invalid-target", string.format (
      "rejected target '%s' of type '%s' for channel '%s'; " ..
      "restoring the saved target", tostring (value),
      tostring (value_type), channel))
  end
  if pending_move and pending_move.target_serial ~= value then
    return reject ("superseded",
      "durable output move was superseded before validation")
  end

  local target = nodes_om:lookup {
    Constraint { "object.serial", "=", value, type = "pw-global" },
  }
  local eligible, rejection = eligible_physical_sink (
    target, bridge, nodes_om, links_om, devices_om)
  if not eligible then
    return reject ("unsafe-target", string.format (
      "rejected target serial %s for channel '%s': %s; restoring the saved target",
      value, channel, rejection))
  end

  local target_name = target.properties ["node.name"]
  local saved_message = string.format (
    "saved channel '%s' target '%s' from live serial %s",
    channel, target_name, value)
  if not pending_move then
    save_channel_target (channel, target_name)
    if set_target_metadata (source, bridge, target_name) then
      log:info (bridge, saved_message)
    end
    return true
  end

  local previous_target = state_table [channel]
  state_table [channel] = target_name
  local saved, save_error = state:save (state_table)
  if not saved then
    local live_restored, durable_saved = roll_back_target (
      source, bridge, channel, previous_target, false,
      "could not persist output move", save_error)
    publish_pending_error (source, bridge, pending_move,
      rollback_result_code (live_restored, durable_saved, "state-save"))
    return true
  end

  if not set_target_metadata (source, bridge, target_name) then
    local live_restored, durable_saved = roll_back_target (
      source, bridge, channel, previous_target, true,
      "could not publish normalized output target")
    publish_pending_error (source, bridge, pending_move,
      rollback_result_code (live_restored, durable_saved, "metadata-publish"))
    return true
  end

  if not publish_pending_result (
      source, bridge, pending_move, MOVE_ACK_KEY, pending_move.nonce) then
    local live_restored, durable_saved = roll_back_target (
      source, bridge, channel, previous_target, true,
      "could not acknowledge output move")
    publish_pending_error (source, bridge, pending_move,
      rollback_result_code (live_restored, durable_saved, "ack-publish"))
    return true
  end

  log:info (bridge, saved_message)
  return true
end

local metadata_handlers = {
  [TARGET_KEY] = handle_target_change,
  [MOVE_REQUEST_KEY] = handle_move_request,
  [RESET_KEY] = handle_reset_request,
  [RESET_COMMIT_KEY] = handle_reset_commit,
}

SimpleEventHook {
  name = "funforgiven/channel-output/handle-target-change",
  before = "linking/rescan-trigger-on-target-metadata-changed",
  interests = {
    EventInterest {
      Constraint { "event.type", "=", "metadata-changed" },
      Constraint { "metadata.name", "=", "default" },
      Constraint {
        "event.subject.key", "c",
        TARGET_KEY, MOVE_REQUEST_KEY, RESET_KEY, RESET_COMMIT_KEY,
      },
    },
  },
  execute = function (event)
    local source = event:get_source ()
    local props = event:get_properties ()
    local subject_id = props ["event.subject.id"]
    local key = props ["event.subject.key"]
    local value = props ["event.subject.value"]
    local value_type = props ["event.subject.spa_type"]

    local nodes_om = source:call ("get-object-manager", "node")
    local bridge = nodes_om and nodes_om:lookup {
      Constraint { "bound-id", "=", subject_id, type = "gobject" },
    }

    if not bridge or bridge.properties [KIND_PROPERTY] ~= "bridge" then
      return
    end

    if key == TARGET_KEY and value_type == "Spa:String" and value == "-1" then
      return
    end

    local channel, reason = bridge_channel (bridge)
    if not channel then
      quarantine_malformed_bridge (source, bridge, reason or "unknown error")
      event:stop_processing ()
      return
    end

    purge_stale_pending_transactions (source, bridge, channel)

    if metadata_handlers [key] (
        source, bridge, channel, value, value_type, nodes_om) then
      event:stop_processing ()
    end
  end,
}:register ()

SimpleEventHook {
  name = "funforgiven/channel-output/default-metadata-added",
  interests = {
    EventInterest {
      Constraint { "event.type", "=", "metadata-added" },
      Constraint { "metadata.name", "=", "default" },
    },
  },
  execute = function (event)
    restore_active_bridges (event:get_source (), "default metadata creation")
  end,
}:register ()
