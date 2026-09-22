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

call(name, path, interface, "FocusOut")
assert bridge(
    "UpdateSession",
    GLib.Variant("(sis)", ("session-2", 0, "不应输入")),
) == (False,)

print("PASS: session/range guarded native commits and corrections")
print("Two native updates: %.1f ms" % elapsed)
