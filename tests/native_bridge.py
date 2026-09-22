"""Run inside an isolated dbus-run-session with the VoiceIME addon loaded."""
import time
import gi
from gi.repository import Gio, GLib

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
events = []


def call(name, path, interface, method, args=None):
    return bus.call_sync(
        name, path, interface, method, args, None,
        Gio.DBusCallFlags.NONE, 2000, None
    ).unpack()


name = "org.fcitx.Fcitx5"
interface = "org.fcitx.Fcitx.InputContext1"
path, uuid = call(
    name, "/org/freedesktop/portal/inputmethod",
    "org.fcitx.Fcitx.InputMethod1", "CreateInputContext",
    GLib.Variant("(a(ss))", ([("program", "voiceime-test")],)),
)
bus.signal_subscribe(
    name, interface, None, path, None, Gio.DBusSignalFlags.NONE,
    lambda c, s, p, i, member, args, data: events.append(
        (member, args.unpack())
    ),
    None,
)
# Preedit + surrounding text: live recognition is replaceable composition,
# and only FinishSession commits application text.
call(
    name, path, interface, "SetCapability",
    GLib.Variant("(t)", ((1 << 1) | (1 << 6),)),
)
call(
    name, path, interface, "SetSurroundingText",
    GLib.Variant("(suu)", ("已有文字", 4, 4)),
)
call(name, path, interface, "FocusIn")


def bridge(method, args=None):
    return call(
        "org.voiceime.Input", "/org/voiceime/Input",
        "org.voiceime.Input1", method, args
    )


assert bridge(
    "BeginSession", GLib.Variant("(s)", ("session-1",))
) == (True,)
start = time.monotonic()
assert bridge(
    "UpdateSession",
    GLib.Variant("(sis)", ("session-1", 0, "你好这是测式")),
) == (True,)
assert bridge(
    "UpdateSession",
    GLib.Variant("(sis)", ("session-1", 1, "试")),
) == (True,)
assert bridge(
    "FinishSession",
    GLib.Variant("(ss)", ("session-1", "你好，这是测试。")),
) == (True,)
elapsed = (time.monotonic() - start) * 1000

# A late result from an old utterance must be rejected after a new session.
assert bridge(
    "BeginSession", GLib.Variant("(s)", ("session-2",))
) == (True,)
assert bridge(
    "UpdateSession",
    GLib.Variant("(sis)", ("session-1", 0, "旧结果")),
) == (False,)

# Simulate a user cursor move after session-2 begins. The addon must reject
# any correction rather than deleting at the new cursor position.
call(
    name, path, interface, "SetSurroundingTextPosition",
    GLib.Variant("(uu)", (0, 0)),
)
assert bridge(
    "UpdateSession",
    GLib.Variant("(sis)", ("session-2", 1, "错")),
) == (False,)

deadline = time.monotonic() + .1
while time.monotonic() < deadline:
    GLib.MainContext.default().iteration(False)
    time.sleep(.001)

commits = [args[0] for member, args in events if member == "CommitString"]
deletes = [args for member, args in events if member == "DeleteSurroundingText"]
assert commits == ["你好，这是测试。"], events
assert len(deletes) == 0, events

# Replay the exact signals an application receives and assert the final
# input-buffer content, not just the recognizer/bridge return values.
buffer = "已有文字"
cursor = len(buffer)
for member, args in events:
    if member == "CommitString":
        text = args[0]
        buffer = buffer[:cursor] + text + buffer[cursor:]
        cursor += len(text)
    elif member == "DeleteSurroundingText":
        offset, size = args
        start = cursor + offset
        assert 0 <= start <= cursor <= len(buffer), (buffer, cursor, args)
        buffer = buffer[:start] + buffer[start + size:]
        cursor = start
assert buffer == "已有文字你好，这是测试。", (buffer, events)

# Preedit mode: live revisions must never enter the application document.
call(
    name, path, interface, "SetSurroundingText",
    GLib.Variant("(suu)", ("前文", 2, 2)),
)
assert bridge("BeginSession", GLib.Variant("(s)", ("session-3",))) == (True,)
before_preview = len(events)
assert bridge(
    "PreviewSession",
    GLib.Variant("(ss)", ("session-3", "帮我看 GitHub")),
) == (True,)
assert bridge(
    "PreviewSession",
    GLib.Variant("(ss)", ("session-3", "帮我看 GitHub Actions")),
) == (True,)

deadline = time.monotonic() + .05
while time.monotonic() < deadline:
    GLib.MainContext.default().iteration(False)
    time.sleep(.001)
preview_events = events[before_preview:]
assert not [
    e for e in preview_events
    if e[0] in ("CommitString", "ForwardKey", "DeleteSurroundingText")
], preview_events

assert bridge(
    "CommitSession",
    GLib.Variant("(ss)", ("session-3", "帮我看 GitHub Actions")),
) == (True,)
deadline = time.monotonic() + .05
while time.monotonic() < deadline:
    GLib.MainContext.default().iteration(False)
    time.sleep(.001)
final_events = events[before_preview:]
final_commits = [args[0] for member, args in final_events if member == "CommitString"]
assert final_commits == ["帮我看 GitHub Actions"], final_events
assert not [args for member, args in final_events if member == "ForwardKey"], final_events
assert not [args for member, args in final_events if member == "DeleteSurroundingText"], final_events

# Session closes after the atomic commit; late final results fail closed.
assert bridge(
    "CommitSession",
    GLib.Variant("(ss)", ("session-3", "迟到结果")),
) == (False,)

call(name, path, interface, "FocusOut")
assert bridge(
    "UpdateSession",
    GLib.Variant("(sis)", ("session-2", 0, "不应输入")),
) == (False,)

print("PASS: legacy guards + preedit atomic final commit")
print("Two native updates: %.1f ms" % elapsed)
