import QtQuick
import QtTest
import "../idle"

TestCase {
    name: "PresencePolicy"

    PresencePolicy {
        id: policy
    }

    function init() {
        policy.presenceLease.stop();
        policy.wakeGrace.stop();
        policy.presenceLease.interval = 45000;
        policy.wakeGrace.interval = 30000;
        policy.inputIdle = false;
        policy.presenceState = "unknown";
    }

    function test_reading_without_input_stays_awake() {
        policy.presence("on");
        policy.idle();
        compare(policy.active, false);
    }

    function test_leaving_blanks_without_waiting_for_idle() {
        policy.presence("on");
        policy.presence("off");
        compare(policy.active, true);
        policy.presence("on");
        compare(policy.active, false);
    }

    function test_input_wakes_during_sensor_delay() {
        policy.wakeGrace.interval = 50;
        policy.presence("off");
        policy.input();
        compare(policy.active, false);
        policy.presence("off"); // Heartbeats must not defeat manual wake.
        compare(policy.active, false);
        tryCompare(policy, "active", true);
    }

    function test_presence_ends_manual_override() {
        policy.presence("off");
        policy.input();
        policy.presence("on");
        compare(policy.wakeGrace.running, false);
        policy.presence("off");
        compare(policy.active, true);
    }

    function test_unavailable_uses_idle_fallback() {
        policy.presence("unavailable");
        compare(policy.active, false);
        policy.idle();
        compare(policy.active, true);
        policy.input();
        compare(policy.active, false);
    }

    function test_crashed_reader_expires_presence() {
        policy.presenceLease.interval = 50;
        policy.idle();
        policy.presence("on");
        compare(policy.active, false);
        tryCompare(policy, "presenceState", "unknown");
        compare(policy.active, true);
    }
}
