/** Getting a user's ESPN session out of their browser and into this app.
 *
 * The app can't read espn.com's cookies itself — a page on one origin
 * reading another's is exactly what the same-origin policy exists to stop,
 * and no amount of app code changes that. So the user has to carry them
 * across, and all this module does is make that carry as close to one
 * click as the browser allows.
 *
 * Everything here runs in the browser on purpose: a cookie dump pasted
 * from ESPN contains far more than the two values this app wants, and the
 * server has no business seeing the rest.
 */

/** A bookmarklet the user runs while signed in on fantasy.espn.com. ESPN
 * doesn't mark espn_s2 or SWID HttpOnly, so a script on an ESPN page can
 * read both and put them on the clipboard — which is all this does. It
 * sends nothing anywhere; the user pastes the result into this app by
 * hand. Kept as one line because that's what a bookmark URL has to be. */
export const ESPN_BOOKMARKLET =
  "javascript:(function(){" +
  "var g=function(n){var m=document.cookie.match(new RegExp('(?:^|;\\\\s*)'+n+'=([^;]*)'));" +
  "return m?decodeURIComponent(m[1]):''};" +
  "var s=g('espn_s2'),w=g('SWID');" +
  "if(!s||!w){alert('Couldn\\\\'t find your ESPN cookies on this page. Open fantasy.espn.com, " +
  "make sure you are signed in, and click this bookmark there.');return}" +
  "var t='espn_s2='+s+'; SWID='+w;" +
  "var d=function(){window.prompt('Copy this, then paste it into Backup Armchair Quarterback:',t)};" +
  "if(navigator.clipboard&&navigator.clipboard.writeText){" +
  "navigator.clipboard.writeText(t).then(function(){" +
  "alert('ESPN cookies copied. Paste them into Backup Armchair Quarterback.')},d)}else{d()}" +
  "})()";

export interface ParsedEspnCookies {
  espnS2: string;
  swid: string;
}

function findCookie(text: string, name: string): string {
  // Tolerant of whatever the value was pasted out of: a `name=value; ...`
  // cookie string, a devtools row, or a JSON blob. Stops at the delimiters
  // a cookie value can't contain itself.
  const match = text.match(new RegExp(`${name}\\s*[=:]\\s*"?([^;,"'\\s]+)`, "i"));
  return match ? match[1].trim() : "";
}

/** Pull espn_s2 and SWID out of whatever the user pasted.
 *
 * Handles the bookmarklet's output, a whole `document.cookie` dump (which
 * is dozens of unrelated ESPN cookies), and a single value pasted on its
 * own — a bare `{...}` is a SWID, and anything else long and opaque is an
 * espn_s2, since neither is ever mistakable for the other.
 */
export function parseEspnCookies(text: string): ParsedEspnCookies {
  const trimmed = text.trim();
  if (!trimmed) return { espnS2: "", swid: "" };

  const espnS2 = findCookie(trimmed, "espn_s2");
  const swid = findCookie(trimmed, "SWID");
  if (espnS2 || swid) return { espnS2, swid };

  // No name= prefix anywhere, so this is one bare value.
  if (/^\{?[0-9A-F-]{30,}\}?$/i.test(trimmed)) return { espnS2: "", swid: trimmed };
  return { espnS2: trimmed, swid: "" };
}
