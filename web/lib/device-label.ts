/** A browser hint, never a verified device identity or geolocation. */
export function deviceLabel(userAgent: string): string {
  const browser = /Edg\//.test(userAgent) ? "Edge" : /Firefox\//.test(userAgent) ? "Firefox" : /(?:Chrome|CriOS)\//.test(userAgent) ? "Chrome" : /Safari\//.test(userAgent) ? "Safari" : "Browser";
  const system = /iPhone|iPad/.test(userAgent) ? "iOS" : /Android/.test(userAgent) ? "Android" : /Windows/.test(userAgent) ? "Windows" : /Macintosh|Mac OS/.test(userAgent) ? "macOS" : /Linux/.test(userAgent) ? "Linux" : null;
  return system ? `${browser} on ${system}` : browser;
}
