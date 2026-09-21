// Native text delivery: no global keymap changes and no clipboard.
#include <fcitx/addonfactory.h>
#include <fcitx/addonmanager.h>
#include <fcitx/inputcontext.h>
#include <fcitx/inputcontextmanager.h>
#include <fcitx/instance.h>
#include <fcitx-utils/dbus/bus.h>
#include <fcitx-utils/dbus/objectvtable.h>
#include <fcitx-utils/key.h>
#include <fcitx-utils/utf8.h>
#include <stdexcept>

class VoiceIME : public fcitx::AddonInstance,
                 public fcitx::dbus::ObjectVTable<VoiceIME> {
public:
    explicit VoiceIME(fcitx::Instance *instance)
        : instance_(instance), bus_(fcitx::dbus::BusType::Session) {
        bus_.attachEventLoop(&instance_->eventLoop());
        if (!bus_.requestName("org.voiceime.Input", fcitx::dbus::RequestNameFlag::None) ||
            !bus_.addObjectVTable("/org/voiceime/Input", "org.voiceime.Input1", *this)) {
            throw std::runtime_error("Cannot register VoiceIME input bridge");
        }
    }

    bool begin() {
        auto *ic = instance_->inputContextManager().lastFocusedInputContext();
        active_ = ic && ic->hasFocus();
        if (active_) {
            target_ = ic->uuid();
            inserted_ = 0;
            ic->reset();
        }
        return active_;
    }

    bool update(int32_t remove, const std::string &text) {
        auto *ic = instance_->inputContextManager().lastFocusedInputContext();
        if (!active_ || !ic || !ic->hasFocus() || ic->uuid() != target_) {
            active_ = false;
            return false;
        }
        if (remove < 0 || static_cast<size_t>(remove) > inserted_ ||
            remove > 4096 || text.size() > 65536 ||
            (!text.empty() && !fcitx::utf8::validate(text))) {
            return false;
        }
        if (remove && ic->capabilityFlags().test(fcitx::CapabilityFlag::SurroundingText)) {
            // GTK4 does not implement ForwardKey; use its native editing API.
            ic->deleteSurroundingText(-remove, remove);
        } else {
            // Terminals generally lack surrounding-text support. Forward to
            // this input context directly, without global Alt/Ctrl state.
            for (int32_t n = 0; n < remove; ++n) {
                ic->forwardKey(fcitx::Key(FcitxKey_BackSpace), false);
                ic->forwardKey(fcitx::Key(FcitxKey_BackSpace), true);
            }
        }
        if (!text.empty()) {
            ic->commitString(text);
        }
        inserted_ = inserted_ - remove + fcitx::utf8::length(text);
        return true;
    }

    FCITX_OBJECT_VTABLE_METHOD(begin, "Begin", "", "b");
    FCITX_OBJECT_VTABLE_METHOD(update, "Update", "is", "b");

private:
    fcitx::Instance *instance_;
    fcitx::dbus::Bus bus_;
    fcitx::ICUUID target_{};
    bool active_ = false;
    size_t inserted_ = 0;
};

class VoiceIMEFactory : public fcitx::AddonFactory {
    fcitx::AddonInstance *create(fcitx::AddonManager *manager) override {
        return new VoiceIME(manager->instance());
    }
};

FCITX_ADDON_FACTORY(VoiceIMEFactory);
