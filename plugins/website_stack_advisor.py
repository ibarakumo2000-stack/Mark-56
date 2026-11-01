"""Deterministic technology-stack advisor for Mark 56 website projects.

This plugin recommends a stack from explicit project requirements. It does not
install dependencies or claim a scaffold exists; it returns a reasoned plan.
"""
from __future__ import annotations

import json
import re
from typing import Any

PROJECT_TYPES = {
    "portfolio", "business", "landing", "church", "blog", "ecommerce",
    "dashboard", "saas", "webapp", "game", "documentation",
}
HOSTING = {"any", "vercel", "static", "self_hosted", "cloudflare"}

def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "required"}
    return bool(value)

def _items(value: Any) -> set[str]:
    if isinstance(value, str):
        parts = re.split(r"[,;\n]", value)
    elif isinstance(value, list):
        parts = value
    else:
        parts = []
    return {str(item).strip().lower().replace("-", "_") for item in parts if str(item).strip()}

def recommend(p: dict[str, Any]) -> dict[str, Any]:
    kind = str(p.get("kind") or p.get("project_type") or "business").strip().lower()
    if kind not in PROJECT_TYPES:
        raise ValueError("kind must be one of: " + ", ".join(sorted(PROJECT_TYPES)))
    features = _items(p.get("features"))
    hosting = str(p.get("hosting") or "any").strip().lower().replace("-", "_")
    if hosting not in HOSTING:
        raise ValueError("hosting must be one of: " + ", ".join(sorted(HOSTING)))
    auth = _bool(p.get("authentication")) or bool(features & {"auth", "authentication", "accounts", "login", "user_accounts"})
    database = _bool(p.get("database")) or bool(features & {"database", "persistent_data", "multi_user_data", "inventory", "orders", "payments"})
    realtime = _bool(p.get("realtime")) or bool(features & {"realtime", "live_updates", "chat", "collaboration", "live_dashboard"})
    commerce = kind == "ecommerce" or bool(features & {"checkout", "payments", "cart", "product_catalog", "subscriptions"})
    dashboard = kind == "dashboard" or bool(features & {"dashboard", "admin_panel", "analytics"})
    game = kind == "game" or bool(features & {"canvas_game", "browser_game", "webgl"})
    content_heavy = kind in {"blog", "documentation"} or _bool(p.get("seo_priority")) or bool(features & {"content_marketing", "many_public_pages", "seo"})
    complexity = sum((auth, database, realtime, commerce, dashboard))
    reasons: list[str] = []
    warnings: list[str] = []

    if game:
        frontend = "TypeScript + Vite"
        rendering = "Canvas/WebGL or a game-specific library chosen for the gameplay"
        reasons.append("A game benefits from a fast client-side loop; use a game engine only if the mechanics justify it.")
        if auth or database or realtime:
            backend = "Node.js/TypeScript API or managed backend, selected for the required accounts, persistence, or multiplayer"
        else:
            backend = "No backend for a local/single-player prototype"
            database = False
    elif kind in {"portfolio", "landing"} and not (auth or database or realtime or commerce):
        frontend = "HTML + modern CSS + JavaScript"
        rendering = "Static, semantic HTML with responsive CSS"
        backend = "None required; add a form service or API only if needed"
        reasons.append("The brief is content-led and does not justify framework or backend overhead.")
    elif content_heavy and not (auth or realtime or commerce):
        frontend = "Next.js + TypeScript"
        rendering = "Server-rendered/static-generated pages with metadata per route"
        backend = "Next.js server routes only for actual server-side features"
        reasons.append("Search visibility and structured content benefit from route-level metadata and server/static rendering.")
    else:
        frontend = "React + TypeScript + Vite"
        rendering = "Component-driven client UI; use SSR/Next.js if public-page SEO is a primary requirement"
        reasons.append("A component framework and TypeScript suit the requested interactive UI without assuming a full-stack framework is necessary.")
        backend = "Node.js/TypeScript API" if (auth or database or realtime or commerce) else "None required initially"

    if content_heavy and kind not in {"portfolio", "landing"}:
        reasons.append("Prioritize descriptive page titles, metadata, sitemap, canonical URLs, and accessible semantic markup.")
    if auth:
        reasons.append("Authentication requires server-side session validation and authorization; do not implement security using frontend-only checks.")
    if database:
        backend += "; PostgreSQL is the default relational database recommendation"
        reasons.append("Persistent or relational records need a database and server-side validation.")
    if realtime:
        backend += "; add WebSockets or a managed realtime service only if live updates are required"
        reasons.append("Realtime behavior should use a dedicated event channel instead of repeated polling where appropriate.")
    if commerce:
        backend += "; use a reputable payment provider and never store raw card details"
        reasons.append("Checkout requires server-verified prices and payment webhooks; payment success must not be trusted from the browser.")
    if hosting == "static" and (auth or database or realtime or commerce):
        warnings.append("Static hosting alone cannot safely provide private server-side logic. Add a trusted API/serverless backend or choose a full-stack host.")
    if hosting == "cloudflare" and frontend.startswith("Next.js"):
        warnings.append("Confirm the chosen Next.js features are supported by the selected Cloudflare deployment adapter before committing to this stack.")
    if kind == "ecommerce" and not commerce:
        warnings.append("E-commerce requirements are not fully specified; clarify catalog size, checkout, taxes, shipping, and payment provider before production.")
    if not p.get("requirements") and kind in {"saas", "webapp", "dashboard"}:
        warnings.append("This is a preliminary recommendation. Confirm user roles, data model, integrations, and deployment target before scaffolding.")
    return {
        "ok": True,
        "kind": kind,
        "recommended_stack": {
            "frontend": frontend,
            "rendering": rendering,
            "backend": backend,
            "styling": "CSS Modules or a small design-token-based CSS system; add Tailwind only if it improves team speed",
            "testing": "Unit/component tests plus browser-level smoke tests for key journeys",
            "quality": ["responsive breakpoints", "keyboard accessibility", "reduced-motion support", "SEO metadata where relevant", "optimized images", "error and empty states"],
        },
        "detected_requirements": {
            "authentication": auth, "database": database, "realtime": realtime,
            "commerce": commerce, "dashboard": dashboard, "seo_priority": content_heavy,
        },
        "reasons": reasons,
        "warnings": warnings,
        "next_step": "Review this recommendation against the full brief, then generate a scaffold only for a stack with a tested build/run workflow.",
        "limitations": ["Recommendation only: this operation does not install packages, provision infrastructure, or create a project."],
    }

def run(parameters: dict, **_context) -> str:
    p = parameters or {}
    operation = str(p.get("operation") or "recommend").strip().lower()
    if operation not in {"recommend", "catalog"}:
        return json.dumps({"ok": False, "message": "Use recommend or catalog."})
    if operation == "catalog":
        return json.dumps({"ok": True, "project_types": sorted(PROJECT_TYPES), "hosting_targets": sorted(HOSTING)})
    try:
        return json.dumps(recommend(p), ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"ok": False, "message": str(exc)})

PLUGIN = {
    "name": "website_stack_advisor",
    "description": (
        "Recommend a technology stack from a website brief before scaffolding. "
        "Use for choosing frontend, rendering, backend, database, SEO and hosting approach. "
        "Deterministic rules; returns rationale and warnings; does not install dependencies or create files."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "operation": {"type": "STRING", "description": "recommend | catalog"},
            "kind": {"type": "STRING", "description": "portfolio | business | landing | church | blog | ecommerce | dashboard | saas | webapp | game | documentation"},
            "features": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Required features such as authentication, database, realtime, payments, SEO, dashboard, chat"},
            "authentication": {"type": "BOOLEAN", "description": "Whether user accounts/sign-in are required"},
            "database": {"type": "BOOLEAN", "description": "Whether persistent structured data is required"},
            "realtime": {"type": "BOOLEAN", "description": "Whether live updates or collaboration are required"},
            "seo_priority": {"type": "BOOLEAN", "description": "Whether search visibility is a priority"},
            "hosting": {"type": "STRING", "description": "any | vercel | static | self_hosted | cloudflare"},
            "requirements": {"type": "STRING", "description": "Short summary of the project requirements"},
        },
        "required": ["operation"],
    },
}
