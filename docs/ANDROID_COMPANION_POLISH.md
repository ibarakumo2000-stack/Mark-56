# Android Companion UX and quality pass

The phone companion now uses a Material 3 dark theme, accessible Material
buttons, a custom JARVIS launcher icon, system bar colors, and a scrollable
layout that remains usable on short screens. The Wear OS bridge and remote
relay controls are explicit opt-ins. Remote relay credentials are encrypted
with Android Keystore AES-GCM, separately from the local desktop pairing token.

The build now supports minified release variants and shared owner-controlled
signing for the phone and watch packages. The rolling preview remains a debug
build and is clearly labelled as such. Production releases are created only by
the tag workflow after the project owner configures the signing secrets.

Before claiming a polished public release, run accessibility checks (TalkBack,
large font/display scaling, contrast), verify on at least one small and one
large Android screen, test Android 13+ notification permission behavior, and
test battery-optimized background execution on real devices.
