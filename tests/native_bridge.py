"""Run inside an isolated dbus-run-session with the VoiceIME addon loaded."""
import time
import gi
from gi.repository import Gio, GLib

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
events = []

def call(name, path, interface, method, args=None):
    return bus.call_sync(name, path, interface, method, args, None,
                         Gio.DBusCallFlags.NONE, 2000, None).unpack()

name = 'org.fcitx.Fcitx5'
interface = 'org.fcitx.Fcitx.InputContext1'
path, uuid = call(name, '/org/freedesktop/portal/inputmethod',
                  'org.fcitx.Fcitx.InputMethod1', 'CreateInputContext',
                  GLib.Variant('(a(ss))', ([('program', 'voiceime-test')],)))
bus.signal_subscribe(name, interface, None, path, None, Gio.DBusSignalFlags.NONE,
                     lambda c, s, p, i, member, args, data: events.append((member, args.unpack())), None)
call(name, path, interface, 'FocusIn')

def bridge(method, args=None):
    return call('org.voiceime.Input', '/org/voiceime/Input', 'org.voiceime.Input1', method, args)

assert bridge('Begin') == (True,)
start = time.monotonic()
assert bridge('Update', GLib.Variant('(is)', (0, '你好这是测式'))) == (True,)
assert bridge('Update', GLib.Variant('(is)', (1, '试'))) == (True,)
elapsed = (time.monotonic() - start) * 1000
assert bridge('Update', GLib.Variant('(is)', (100, '不应删除原有文字'))) == (False,)
deadline = time.monotonic() + .1
while time.monotonic() < deadline:
    GLib.MainContext.default().iteration(False)
    time.sleep(.001)
commits = [args[0] for member, args in events if member == 'CommitString']
keys = [args for member, args in events if member == 'ForwardKey']
assert commits == ['你好这是测式', '试'], events
assert len(keys) == 2, events
assert all(args[1] == 0 for args in keys), keys  # No Alt/Ctrl modifiers.
call(name, path, interface, 'FocusOut')
assert bridge('Update', GLib.Variant('(is)', (1, '不应输入'))) == (False,)
print('PASS: native Unicode commits, modifier-free correction and focus-loss protection')
print('Two native updates: %.1f ms' % elapsed)
