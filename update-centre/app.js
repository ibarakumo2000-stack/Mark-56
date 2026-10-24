const RELEASES_URL = "https://api.github.com/repos/ibarakumo2000-stack/Mark-56/releases?per_page=20";
const RELEASES_PAGE = "https://github.com/ibarakumo2000-stack/Mark-56/releases";
const ISSUE_PAGE = "https://github.com/ibarakumo2000-stack/Mark-56/issues";
const $ = (id) => document.getElementById(id);
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const formatDate = (value) => { const date = new Date(value); return Number.isNaN(date.getTime()) ? "Date unavailable" : new Intl.DateTimeFormat(undefined,{year:"numeric",month:"short",day:"numeric"}).format(date); };
const stableReleases = (items) => items.filter((release) => !release.draft && !release.prerelease);
function releaseSummary(body, max = 260) {
  const plain = String(body || "").replace(/<[^>]*>/g,"").replace(/\r/g,"").trim();
  if (!plain) return "No release notes were provided for this release.";
  return plain.length > max ? plain.slice(0,max).trimEnd() + "…" : plain;
}
function releaseAssetLinks(release) {
  const assets = Array.isArray(release.assets) ? release.assets : [];
  const linuxAssets = assets.filter((asset) => /linux|ubuntu|\.appimage$|\.deb$|\.tar\.(gz|xz)$|\.zip$/i.test(asset.name));
  const chosen = linuxAssets.length ? linuxAssets : assets;
  return chosen.slice(0,4).map((asset) => '<a href="'+escapeHTML(asset.browser_download_url)+'" target="_blank" rel="noreferrer">'+escapeHTML(asset.name)+' · '+formatBytes(asset.size)+' ↗</a>').join("");
}
function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "size unknown";
  const units = ["B","KB","MB","GB"]; let size = bytes; let unit = 0;
  while (size >= 1024 && unit < units.length-1) { size /= 1024; unit++; }
  return size.toFixed(unit === 0 ? 0 : 1)+" "+units[unit];
}
function renderFeatured(release) {
  $("latest-version").textContent = release.tag_name || release.name || "Published release";
  $("release-date").textContent = "Published "+formatDate(release.published_at || release.created_at);
  $("connection-status").textContent = "Release metadata loaded";
  const assets = releaseAssetLinks(release);
  $("release-feature").innerHTML =
    '<div class="card-icon" aria-hidden="true">◈</div><div><div class="release-meta"><span class="tag">LATEST STABLE</span><span class="tag neutral">'+escapeHTML(release.tag_name || "VERSION NOT TAGGED")+'</span></div>'+
    '<h3>'+escapeHTML(release.name || release.tag_name || "Mark 56 release")+'</h3><p>'+escapeHTML(releaseSummary(release.body,520))+'</p>'+
    '<div class="release-actions"><a href="'+escapeHTML(release.html_url || RELEASES_PAGE)+'" target="_blank" rel="noreferrer">Full release notes ↗</a>'+
    (assets || '<a href="'+RELEASES_PAGE+'" target="_blank" rel="noreferrer">View release assets ↗</a>')+'</div></div>';
}
function renderReleaseList(items) {
  if (!items.length) {
    $("release-list").innerHTML = '<p class="muted">No published stable releases were found yet. Visit GitHub to see tags and development activity.</p>';
    $("release-count").textContent = "0 STABLE RELEASES";
    return;
  }
  $("release-count").textContent = items.length+" STABLE RELEASE"+(items.length===1?"":"S");
  $("release-list").innerHTML = items.slice(0,8).map((release) =>
    '<article class="release-row"><div><strong>'+escapeHTML(release.name || release.tag_name || "Mark 56 release")+'</strong><small>'+escapeHTML(releaseSummary(release.body,105))+'</small></div>'+
    '<time datetime="'+escapeHTML(release.published_at || release.created_at || "")+'">'+formatDate(release.published_at || release.created_at)+'</time>'+
    '<a href="'+escapeHTML(release.html_url || RELEASES_PAGE)+'" target="_blank" rel="noreferrer">Release details ↗</a></article>'
  ).join("");
}
async function loadReleases() {
  try {
    const response = await fetch(RELEASES_URL,{headers:{Accept:"application/vnd.github+json"},cache:"no-store"});
    if (!response.ok) throw new Error(response.status === 403 || response.status === 429 ? "GitHub is temporarily rate-limiting requests. Open the official releases page to continue." : "GitHub returned status "+response.status+".");
    const data = await response.json();
    if (!Array.isArray(data)) throw new Error("The release service returned an unexpected response.");
    const stable = stableReleases(data).sort((a,b)=>new Date(b.published_at || b.created_at || 0)-new Date(a.published_at || a.created_at || 0));
    if (!stable.length) {
      $("latest-version").textContent = "No stable release yet";
      $("release-date").textContent = "No published stable release is available";
      $("connection-status").textContent = "Connected · no stable releases";
      $("release-feature").innerHTML = '<div class="card-icon">◈</div><div><h3>Release channel is ready</h3><p>No published stable GitHub release was found. This page will display the latest stable version once one is published.</p><div class="release-actions"><a href="'+RELEASES_PAGE+'" target="_blank" rel="noreferrer">View GitHub releases ↗</a><a href="'+ISSUE_PAGE+'" target="_blank" rel="noreferrer">Development and issues ↗</a></div></div>';
      renderReleaseList([]);
      return;
    }
    renderFeatured(stable[0]);
    renderReleaseList(stable);
    $("release-error").classList.add("hidden");
  } catch (error) {
    $("latest-version").textContent = "Release status unavailable";
    $("release-date").textContent = "Could not retrieve live release information";
    $("connection-status").textContent = "Offline or service unavailable";
    $("release-feature").innerHTML = '<div class="card-icon">!</div><div><h3>Could not connect to GitHub</h3><p>'+escapeHTML(error.message || "Check your connection and try again.")+'</p><div class="release-actions"><a href="'+RELEASES_PAGE+'" target="_blank" rel="noreferrer">Open official releases ↗</a></div></div>';
    $("release-list").innerHTML = '<p class="muted">Live release history could not be loaded. Use the official GitHub page for current information.</p>';
    $("release-error").textContent = "This page does not invent or cache a version when the release service is unavailable. Check GitHub directly for the authoritative status.";
    $("release-error").classList.remove("hidden");
  }
}
loadReleases();