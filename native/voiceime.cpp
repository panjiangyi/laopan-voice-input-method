// Native text delivery: no global keymap changes and no clipboard.
#include <fcitx/addonfactory.h>
#include <fcitx/addonmanager.h>
#include <fcitx/inputcontext.h>
#include <fcitx/inputcontextmanager.h>
#include <fcitx/instance.h>
#include <fcitx/surroundingtext.h>
#include <fcitx-utils/dbus/bus.h>
#include <fcitx-utils/dbus/objectvtable.h>
#include <fcitx-utils/log.h>
#include <fcitx-utils/utf8.h>
#include <stdexcept>
#include <string>

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

    bool begin() { return beginImpl(""); }

    bool beginSession(const std::string &session) {
        if (session.empty() || session.size() > 128) {
            return false;
        }
        return beginImpl(session);
    }

    bool update(int32_t remove, const std::string &text) {
        return updateImpl(remove, text);
    }

    bool updateSession(const std::string &session, int32_t remove,
                       const std::string &text) {
        if (!active_ || session.empty() || session != session_) {
            return false;
        }
        return updateImpl(remove, text);
    }

    FCITX_OBJECT_VTABLE_METHOD(begin, "Begin", "", "b");
    FCITX_OBJECT_VTABLE_METHOD(update, "Update", "is", "b");
    FCITX_OBJECT_VTABLE_METHOD(beginSession, "BeginSession", "s", "b");
    FCITX_OBJECT_VTABLE_METHOD(updateSession, "UpdateSession", "sis", "b");

private:
    static size_t byteOffset(const std::string &text, size_t chars) {
        if (chars == 0) {
            return 0;
        }
        const auto total = fcitx::utf8::length(text);
        if (chars >= total) {
            return text.size();
        }
        return static_cast<size_t>(
            fcitx::utf8::ncharByteLength(text.begin(), chars));
    }

    static void eraseLastChars(std::string &text, size_t count) {
        auto total = fcitx::utf8::length(text);
        if (count >= total) {
            text.clear();
            return;
        }
        const auto keep = total - count;
        text.erase(byteOffset(text, keep));
    }

    bool beginImpl(const std::string &session) {
        auto *ic = instance_->inputContextManager().lastFocusedInputContext();
        active_ = ic && ic->hasFocus();
        target_ = active_ ? ic->uuid() : fcitx::ICUUID{};
        inserted_ = 0;
        committed_.clear();
        session_ = session;
        snapshotValid_ = false;
        before_.clear();
        after_.clear();

        if (!active_) {
            return false;
        }

        ic->reset();
        if (ic->capabilityFlags().test(fcitx::CapabilityFlag::SurroundingText)) {
            auto &surrounding = ic->surroundingText();
            if (surrounding.isValid() &&
                surrounding.cursor() == surrounding.anchor() &&
                fcitx::utf8::validate(surrounding.text())) {
                const auto chars = fcitx::utf8::length(surrounding.text());
                if (surrounding.cursor() <= chars) {
                    const auto cursorByte =
                        byteOffset(surrounding.text(), surrounding.cursor());
                    before_ = surrounding.text().substr(0, cursorByte);
                    after_ = surrounding.text().substr(cursorByte);
                    snapshotValid_ = true;
                }
            }
        }
        return true;
    }

    bool snapshotMatches(fcitx::InputContext *ic) const {
        if (!snapshotValid_) {
            return false;
        }
        if (!ic->capabilityFlags().test(fcitx::CapabilityFlag::SurroundingText)) {
            return false;
        }
        const auto &surrounding = ic->surroundingText();
        if (!surrounding.isValid() ||
            surrounding.cursor() != surrounding.anchor()) {
            return false;
        }
        const std::string expected = before_ + committed_ + after_;
        const auto expectedCursor =
            fcitx::utf8::length(before_) + inserted_;
        return surrounding.text() == expected &&
               surrounding.cursor() == expectedCursor;
    }

    bool updateImpl(int32_t remove, const std::string &text) {
        auto *ic = instance_->inputContextManager().lastFocusedInputContext();
        if (!active_ || !ic || !ic->hasFocus() || ic->uuid() != target_) {
            FCITX_WARN() << "VoiceIME: update rejected, focus or session lost";
            active_ = false;
            return false;
        }
        if (remove < 0 || static_cast<size_t>(remove) > inserted_ ||
            remove > 4096 || text.size() > 65536 ||
            (!text.empty() && !fcitx::utf8::validate(text))) {
            FCITX_WARN() << "VoiceIME: update rejected, bad params remove="
                         << remove << " text_bytes=" << text.size();
            return false;
        }

        // Pure appends (remove == 0) are intrinsically safe — they only
        // commit fresh characters and cannot erase user content even if the
        // surrounding-text snapshot has drifted while we waited for the LLM.
        // Skip the snapshot guard for them so late punctuation/space fixes
        // from the corrector still land.
        //
        // Destructive operations (remove > 0) must still match the snapshot
        // exactly, otherwise we cannot prove what BackSpace would delete and
        // we fail closed to avoid erasing unrelated user content.
        if (remove) {
            if (snapshotValid_ && !snapshotMatches(ic)) {
                FCITX_WARN() << "VoiceIME: destructive update rejected, "
                                "snapshot drifted (inserted=" << inserted_
                             << " text_bytes=" << text.size() << ")";
                active_ = false;
                return false;
            }
            if (!snapshotValid_) {
                FCITX_WARN() << "VoiceIME: destructive update rejected, "
                                "no surrounding-text snapshot";
                active_ = false;
                return false;
            }
        }

        if (remove) {
            ic->deleteSurroundingText(-remove, remove);
            eraseLastChars(committed_, static_cast<size_t>(remove));
        }
        if (!text.empty()) {
            ic->commitString(text);
            committed_ += text;
        }
        inserted_ = inserted_ - remove + fcitx::utf8::length(text);

        // Keep our local cache consistent with the changes we initiated.
        // Pure-append updates land at whatever cursor the frontend now sees;
        // the user just finished speaking so cursor movement is unlikely.
        // The snapshot setText here is best-effort and may be overwritten by
        // the next frontend tick — that is fine because we only consult it
        // again on destructive ops above.
        if (snapshotValid_) {
            auto &surrounding = ic->surroundingText();
            const std::string expected = before_ + committed_ + after_;
            const auto cursor = static_cast<unsigned int>(
                fcitx::utf8::length(before_) + inserted_);
            surrounding.setText(expected, cursor, cursor);
        }
        return true;
    }

    fcitx::Instance *instance_;
    fcitx::dbus::Bus bus_;
    fcitx::ICUUID target_{};
    bool active_ = false;
    size_t inserted_ = 0;
    std::string session_;
    std::string committed_;
    bool snapshotValid_ = false;
    std::string before_;
    std::string after_;
};

class VoiceIMEFactory : public fcitx::AddonFactory {
    fcitx::AddonInstance *create(fcitx::AddonManager *manager) override {
        return new VoiceIME(manager->instance());
    }
};

FCITX_ADDON_FACTORY(VoiceIMEFactory);
