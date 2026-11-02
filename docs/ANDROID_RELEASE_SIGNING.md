# Android production signing and releases

The repository intentionally does not contain a signing key. Production APKs
must be signed with a keystore owned and backed up by the project owner. Losing
the keystore can prevent future in-place updates for the same package names.

## Create a release keystore

On a trusted computer, choose a strong unique password and keep an offline
backup. Do not commit the keystore or its passwords.

```bash
keytool -genkeypair -v \
  -keystore mark56-release.keystore \
  -alias mark56-release \
  -keyalg RSA -keysize 4096 -validity 10000
base64 -w 0 mark56-release.keystore
```

In GitHub → Mark-56 → Settings → Secrets and variables → Actions, create:

- `ANDROID_SIGNING_KEYSTORE_BASE64` — the base64 output
- `ANDROID_KEY_ALIAS` — for example `mark56-release`
- `ANDROID_KEYSTORE_PASSWORD` — the keystore password
- `ANDROID_KEY_PASSWORD` — the key password

Never paste these secrets into issues, source files, workflow logs, or chat.

## Moving from the old debug preview to the first signed release

Older public preview APKs used the production package ID but were signed with
the Android debug certificate. Android does not permit an APK signed with a
different certificate to replace an installed package in place.

Before installing the first owner-signed release, uninstall the old
`JARVIS Companion` debug preview from the phone. This removes that old
installation's local app data and pairing credential; pair the phone again
after installing the signed build. Future signed releases use the same
owner-managed keystore and can update in place without this uninstall step.

New CI debug APKs now use a separate `.debug` application ID and are not
published as public downloads.

## Publish

After the signing secrets are configured and a release candidate has passed CI,
create and push a version tag:

```bash
git tag companion-v1.1.0
git push origin companion-v1.1.0
```

The `Signed Android Companion Release` workflow runs both phone and Wear OS
unit tests, builds minified release APKs, validates the keystore, verifies both
APK signatures with `apksigner`, confirms both packages share the same
certificate, generates SHA-256 checksums, and attaches both APKs and checksums
to the GitHub release. It fails closed if signing secrets are missing or
invalid.

The rolling `android-companion-preview` is a debug/testing build, not a
production-signed public release. A successful workflow definition does not
mean a signed release exists until the owner configures secrets and pushes a
release tag.

Before publishing to Google Play, complete Play Console identity, privacy,
data-safety, target SDK, app-content and policy declarations. CI signing alone
does not constitute Play Store approval.
