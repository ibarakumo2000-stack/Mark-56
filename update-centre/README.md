# JARVIS Update Centre

A lightweight, static release portal for Mark 56 JARVIS. It reads public release metadata from the GitHub REST API and displays published stable releases, notes, and release asset links.

## Deploy to Vercel

1. Import the `ibarakumo2000-stack/Mark-56` GitHub repository into Vercel.
2. Set **Root Directory** to `update-centre`.
3. Leave the framework preset as **Other** (static site). No build command or environment variables are required.
4. Deploy a preview first. Review the preview, then merge the approved branch to the production branch configured in Vercel.
5. Vercel will assign a free `*.vercel.app` URL. Update the canonical URL, Open Graph URL, and sitemap in `index.html`, `robots.txt`, and `sitemap.xml` if the generated project URL differs.

Vercel Git integration can create preview deployments for branch pushes and deploy the configured production branch when changes are merged. See https://vercel.com/docs/git/vercel-for-github.

## Local preview

From this directory, run a local static server, for example:

```bash
python3 -m http.server 4173
```

Then open http://localhost:4173. The release list requires internet access to GitHub's public API.

## Current scope and security

- No database, login, token, or secret is required.
- Release metadata comes from the public GitHub Releases API for `ibarakumo2000-stack/Mark-56`.
- Drafts and prereleases are excluded from the stable channel.
- The site is informational: it does not remotely control the user's computer and is not an update installer.
- Asset links are displayed from GitHub's release metadata. The presence of an asset is not itself proof of a signature or checksum; verify artifacts in the local updater before installation.
- The app's verified update installation, signing keys, packaged Linux artifacts, rollback, and restart handoff must be implemented and tested separately.
