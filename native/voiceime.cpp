// Native text delivery: no global keymap changes and no clipboard.
#include <fcitx/addonfactory.h>
#include <fcitx/addonmanager.h>
#include <fcitx/inputcontext.h>
#include <fcitx/inputcontextmanager.h>
#include <fcitx/inputpanel.h>
#include <fcitx/instance.h>
#include <fcitx/surroundingtext.h>
#include <fcitx/text.h>
#include <fcitx/userinterface.h>
#include <fcitx-utils/dbus/bus.h>
#include <fcitx-utils/dbus/objectvtable.h>
#include <fcitx-utils/key.h>
#include <fcitx-utils/keysym.h>
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

    bool finishSession(const std::string &session, const std::string &text) {
        if (!active_ || session.empty() || session != session_ ||
            text.size() > 65536 ||
            (!text.empty() && !fcitx::utf8::validate(text))) {
            return false;
        }
        auto *ic = instance_->inputContextManager().lastFocusedInputContext();
        if (!ic || !ic->hasFocus() || ic->uuid() != target_) {
            active_ = false;
            return false;
        }

        if (preeditMode_) {
            clearPreedit(ic);
            if (!text.empty()) {
                ic->commitString(text);
            }
        } else {
            // A frontend without preedit support has already received the
            // streaming text. Never try to rewrite it destructively here.
            // Append the exact suffix when possible; otherwise salvage the
            // LLM's sentence-ending mark so the result is still punctuated.
            std::string suffix;
            if (text.compare(0, committed_.size(), committed_) == 0) {
                suffix = text.substr(committed_.size());
            } else if (!hasTerminalPunctuation(committed_)) {
                suffix = terminalPunctuation(text);
            }
            if (!suffix.empty()) {
                ic->commitString(suffix);
            }
        }

        committed_ = text;
        inserted_ = fcitx::utf8::length(text);
        active_ = false;
        session_.clear();
        return true;
    }

    bool previewSession(const std::string &session, const std::string &text) {
        if (!active_ || session.empty() || session != session_) {
            return false;
        }
        return previewImpl(text);
    }

    bool commitSession(const std::string &session, const std::string &text) {
        if (!active_ || session.empty() || session != session_) {
            return false;
        }
        return commitImpl(text);
    }

    bool cancelSession(const std::string &session) {
        if (!active_ || session.empty() || session != session_) {
            return false;
        }
        auto *ic = currentInputContext();
        if (ic) {
            clearPreedit(ic);
        }
        active_ = false;
        preview_.clear();
        return true;
    }

    FCITX_OBJECT_VTABLE_METHOD(begin, "Begin", "", "b");
    FCITX_OBJECT_VTABLE_METHOD(update, "Update", "is", "b");
    FCITX_OBJECT_VTABLE_METHOD(beginSession, "BeginSession", "s", "b");
    FCITX_OBJECT_VTABLE_METHOD(updateSession, "UpdateSession", "sis", "b");
    FCITX_OBJECT_VTABLE_METHOD(finishSession, "FinishSession", "ss", "b");
    FCITX_OBJECT_VTABLE_METHOD(previewSession, "PreviewSession", "ss", "b");
    FCITX_OBJECT_VTABLE_METHOD(commitSession, "CommitSession", "ss", "b");
    FCITX_OBJECT_VTABLE_METHOD(cancelSession, "CancelSession", "s", "b");

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

    static bool endsWith(const std::string &text, const std::string &suffix) {
        return text.size() >= suffix.size() &&
               text.compare(text.size() - suffix.size(), suffix.size(), suffix) == 0;
    }

    static std::string terminalPunctuation(const std::string &text) {
        for (const char *mark : {"。", "！", "？", "!", "?", "；", ";", "…"}) {
            if (endsWith(text, mark)) {
                return mark;
            }
        }
        return {};
    }

    static bool hasTerminalPunctuation(const std::string &text) {
        return !terminalPunctuation(text).empty();
    }

    static void setPreedit(fcitx::InputContext *ic, const std::string &text) {
        fcitx::Text preedit(text);
        preedit.setCursor(static_cast<int>(text.size()));
        ic->inputPanel().setClientPreedit(preedit);
        ic->updatePreedit();
    }

    fcitx::InputContext *currentInputContext() const {
        auto *ic = instance_->inputContextManager().lastFocusedInputContext();
        if (!active_ || !ic || !ic->hasFocus() || ic->uuid() != target_) {
            return nullptr;
        }
        return ic;
    }

    static void clearPreedit(fcitx::InputContext *ic) {
        fcitx::Text empty;
        ic->inputPanel().setClientPreedit(empty);
        ic->inputPanel().setPreedit(empty);
        ic->updatePreedit();
        ic->updateUserInterface(fcitx::UserInterfaceComponent::InputPanel);
    }

    bool previewImpl(const std::string &text) {
        auto *ic = currentInputContext();
        if (!ic) {
            FCITX_WARN() << "VoiceIME: preview rejected, focus or session lost";
            active_ = false;
            return false;
        }
        if (text.size() > 65536 ||
            (!text.empty() && !fcitx::utf8::validate(text))) {
            FCITX_WARN() << "VoiceIME: preview rejected, invalid text";
            return false;
        }

        fcitx::Text preedit;
        preedit.append(text);
        preedit.setCursor(fcitx::utf8::length(text));
        if (ic->capabilityFlags().test(fcitx::CapabilityFlag::Preedit)) {
            ic->inputPanel().setClientPreedit(preedit);
            ic->inputPanel().setPreedit(fcitx::Text{});
        } else {
            ic->inputPanel().setClientPreedit(fcitx::Text{});
            ic->inputPanel().setPreedit(preedit);
        }
        ic->updatePreedit();
        ic->updateUserInterface(fcitx::UserInterfaceComponent::InputPanel);
        preview_ = text;
        return true;
    }

    bool commitImpl(const std::string &text) {
        auto *ic = currentInputContext();
        if (!ic) {
            FCITX_WARN() << "VoiceIME: commit rejected, focus or session lost";
            active_ = false;
            return false;
        }
        if (text.size() > 65536 ||
            (!text.empty() && !fcitx::utf8::validate(text))) {
            FCITX_WARN() << "VoiceIME: commit rejected, invalid text";
            return false;
        }

        if (snapshotValid_ && !snapshotMatches(ic)) {
            FCITX_WARN() << "VoiceIME: commit rejected, target text/cursor changed";
            clearPreedit(ic);
            active_ = false;
            preview_.clear();
            return false;
        }

        clearPreedit(ic);
        if (!text.empty()) {
            ic->commitString(text);
        }
        committed_ = text;
        inserted_ = fcitx::utf8::length(text);
        preview_.clear();
        active_ = false;
        return true;
    }

    bool beginImpl(const std::string &session) {
        auto *ic = instance_->inputContextManager().lastFocusedInputContext();

        // If the user starts the next utterance before the asynchronous LLM
        // response returns, preserve the visible previous preedit instead of
        // discarding it. The old session will be rejected when it eventually
        // finishes.
        if (active_ && preeditMode_ && ic && ic->hasFocus() &&
            ic->uuid() == target_ && !committed_.empty()) {
            std::string fallback = committed_;
            if (!hasTerminalPunctuation(fallback)) {
                fallback += "。";
            }
            clearPreedit(ic);
            ic->commitString(fallback);
        }

        active_ = ic && ic->hasFocus();
        target_ = active_ ? ic->uuid() : fcitx::ICUUID{};
        inserted_ = 0;
        committed_.clear();
        preview_.clear();
        session_ = session;
        snapshotValid_ = false;
        before_.clear();
        after_.clear();

        if (!active_) {
            return false;
        }

        ic->reset();
        preeditMode_ =
            ic->capabilityFlags().test(fcitx::CapabilityFlag::Preedit);
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

        // Client preedit is a replaceable composition owned by Fcitx. It lets
        // partial ASR revisions and the later punctuation pass update the
        // visible sentence without deleting already committed application
        // text. FinishSession performs the one and only commit.
        if (preeditMode_) {
            if (remove) {
                eraseLastChars(committed_, static_cast<size_t>(remove));
            }
            committed_ += text;
            inserted_ = inserted_ - remove + fcitx::utf8::length(text);
            setPreedit(ic, committed_);
            return true;
        }

        // Snapshot policy:
        //   * Pure appends (remove == 0): always allowed. They only add fresh
        //     characters and cannot erase user content even if the snapshot
        //     drifted while we waited on the LLM.
        //   * Destructive updates with a valid snapshot that no longer matches:
        //     reject. We cannot prove what BackSpace would delete, and bailing
        //     is the only safe answer for the user's pre-existing text.
        //   * Destructive updates without a snapshot: many frontends (Electron,
        //     Qt widgets, JetBrains editors, some GTK popovers) never advertise
        //     surrounding-text, so the snapshot was never captured. Rejecting
        //     those would make every late refinement in those apps fail.
        //     We instead log a warning and let the patch through, trusting that
        //     the engine computes `remove` from the same committed_ string it
        //     streamed into the IC character by character during this session.
        if (remove) {
            if (snapshotValid_ && !snapshotMatches(ic)) {
                FCITX_WARN() << "VoiceIME: destructive update rejected, "
                                "snapshot drifted (inserted=" << inserted_
                             << " text_bytes=" << text.size() << ")";
                active_ = false;
                return false;
            }
            if (!snapshotValid_) {
                FCITX_WARN() << "VoiceIME: destructive update without "
                                "surrounding-text snapshot; accepting based on "
                                "session-committed state (inserted=" << inserted_
                             << " remove=" << remove
                             << " text_bytes=" << text.size() << ")";
            }
        }

        if (remove) {
            // Forward N physical BackSpace keys to the client instead of
            // using deleteSurroundingText(-N, N). The relative-offset
            // version depends on fcitx's internal cursor tracking the
            // streaming commitString calls, which is unreliable across
            // GTK/Qt/Electron frontends — empirically the delete becomes a
            // no-op while the commitString still appends, leaving the
            // original streaming text followed by the LLM fix. BackSpace
            // is a real key event the client always handles and removes one
            // character before the cursor each time.
            const fcitx::Key bs(FcitxKey_BackSpace);
            for (int32_t i = 0; i < remove; ++i) {
                ic->forwardKey(bs);
            }
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
    bool preeditMode_ = false;
    size_t inserted_ = 0;
    std::string session_;
    std::string committed_;
    std::string preview_;
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
