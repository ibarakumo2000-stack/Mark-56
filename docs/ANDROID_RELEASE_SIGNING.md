# Android production signing and releases

The repository intentionally does not contain a signing key. Production APKs
must be signed with a keystore owned and backed up by the project owner. Losing
the keystore can prevent future in-place updates for the same Android package.

## Create a release keystore (on a trusted computer)

Choose a strong unique password and keep an offline backup. Do not commit the
keystore or its passwords.

```bash
keytool -genkeypair -v \
  -keystore mark56-release.keystore \
  -alias mark56-release \
  -keyalg RSA -keysize 4096 -validity 10000
```

Create the base64 secret value:

```bash
base64 -w 0 mark56-release.keystore
```

In GitHub → Mark-56 → Settings → Secrets and variables → Actions, create:

- `ANDROID_SIGNING_KEYSTORE_BASE64` — the base64 output above
- `ANDROID_KEY_ALIAS` — for example `mark56-release`
- `ANDROID_KEYSTORE_PASSWORD` — the keystore password
- `ANDROID_KEY_PASSWORD` — the key password

Never paste these secrets into issues, source files, workflow logs, or chat.

## Publish

After the signing secrets are configured and a release candidate has passed CI,
create and push a tag:

```bash
git tag companion-v1.1.0
git push origin companion-v1.1.0
```

The `Signed Android Companion Release` workflow builds both phone and Wear OS
release APKs, enables R8 shrinking, signs both with the same app-owner key,
publishes SHA-256 checksums, and attaches the artifacts to a GitHub release.

The rolling `android-companion-preview` remains a debug/testing build. It is
not a replacement for the signed release. The production workflow fails closed
if any signing secret is missing or the keystore cannot be opened.

Before publishing to Google Play, complete Play Console identity, privacy,
data-safety, target SDK, app-content and policy declarations. CI signing alone
does not constitute Play Store approval.
