# Provider-independent local website builder

Mark 56 now has a deterministic static-site generator in `plugins/static_site_builder.py`. It does not call Gemini, OpenAI, or any other provider, and it does not need network access or extra packages.

## Supported site types

- `portfolio`: personal/creative portfolio
- `business`: services and business landing page
- `landing`: product or campaign landing page
- `church`: church/community landing page

Generated projects contain `index.html`, `style.css`, `app.js`, and `README.md`. Layout is responsive, includes a mobile navigation toggle, reduced-motion support, a skip link, basic SEO metadata, editable service cards, and a configurable accent color.

## Plugin operations

The existing plugin discovery and function-calling path can invoke this plugin from JARVIS chat/voice when enabled.

1. `catalog`: list site kinds and accents.
2. `preview`: generate a no-write preview and return the planned files.
3. `create`: write the project only when the user has reviewed the preview and passes `confirmed=true`.

Example tool parameters:

```json
{
  "operation": "preview",
  "name": "etech-portfolio",
  "kind": "portfolio",
  "site_title": "E-Tech Graphics",
  "tagline": "Visual stories built to stand out.",
  "about": "A creative design studio for brands, campaigns, and digital experiences.",
  "email": "hello@example.com",
  "services": ["Brand identity", "Flyers and banners", "Web design"],
  "accent": "cyan"
}
```

After inspecting the preview, repeat the same parameters with `"operation": "create"` and `"confirmed": true`.

## Safety and scope

- Project names are validated and paths remain inside `MARK56_WORKSPACE` (or the current working directory).
- Preview never writes files.
- Create refuses an existing destination; it never overwrites a project.
- User-provided text is HTML-escaped.
- Static-only: no backend, database, login, server-side contact form, or deployment is created.
- The generated email link opens the user's email client; it does not submit a form.
- The PyQt controls panel includes a **WEBSITE BUILDER** launcher for a visual form, styled HTML preview, explicit create confirmation, and workspace-folder opening. The same generator is also exposed as a plugin for JARVIS chat/voice when the plugin is enabled. The preview uses the same deterministic generator and creation requires the settings to remain unchanged since preview.
