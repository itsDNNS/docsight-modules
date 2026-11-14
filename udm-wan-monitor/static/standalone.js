/* UniFi WAN Monitor — standalone page (/udm-wan): icons and theme sync */
if (typeof lucide !== 'undefined') lucide.createIcons();
// Theme sync via cookie/localStorage if DOCSight sets it
try {
  const stored = localStorage.getItem('docsight-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', stored);
} catch(_) {}
