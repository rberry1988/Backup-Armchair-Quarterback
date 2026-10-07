import { useState } from "react";
import type { ReactNode } from "react";
import { ApiError, api } from "../api";
import type { AiAnalysis, AiTopic } from "../types";

/** Inline **bold** only. Everything is built as React elements rather than
 * set as HTML — the text comes back from a language model, and there is no
 * version of this where injecting it into the DOM as markup is worth the
 * convenience of three extra formatting features. */
function inline(text: string, keyPrefix: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
      <strong key={`${keyPrefix}-${i}`}>{part.slice(2, -2)}</strong>
    ) : (
      part
    )
  );
}

/** Headings, bullet lists and paragraphs — the subset the system prompt
 * actually asks for (see backend/app/ai_advisor.py). Anything else renders
 * as the plain text it is, which is the right failure mode.
 *
 * Blank lines separate blocks, not newlines: models hard-wrap prose at
 * varying widths, and treating every wrapped line as its own paragraph
 * turns a tight paragraph into a double-spaced column of fragments.
 */
function renderAnalysis(text: string): ReactNode[] {
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  let paragraph: string[] = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const joined = paragraph.join(" ");
    paragraph = [];
    blocks.push(<p key={`p-${blocks.length}`}>{inline(joined, `p-${blocks.length}`)}</p>);
  };

  const flushBullets = () => {
    if (!bullets.length) return;
    const items = bullets;
    bullets = [];
    blocks.push(
      <ul key={`ul-${blocks.length}`}>
        {items.map((item, i) => (
          <li key={i}>{inline(item, `li-${blocks.length}-${i}`)}</li>
        ))}
      </ul>
    );
  };

  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) {
      flushBullets();
      flushParagraph();
      continue;
    }

    const heading = line.match(/^#{1,6}\s+(.*)$/);
    if (heading) {
      flushBullets();
      flushParagraph();
      blocks.push(<h4 key={`h-${blocks.length}`}>{inline(heading[1], `h-${blocks.length}`)}</h4>);
      continue;
    }

    const bullet = line.match(/^[-*•]\s+(.*)$/);
    if (bullet) {
      flushParagraph();
      bullets.push(bullet[1]);
      continue;
    }

    // A plain line while a list is open is that bullet wrapping, not a new
    // paragraph wedged between list items.
    if (bullets.length) {
      bullets[bullets.length - 1] += ` ${line}`;
      continue;
    }
    paragraph.push(line);
  }
  flushBullets();
  flushParagraph();
  return blocks;
}

interface Props {
  leagueId: number;
  topic: AiTopic;
  /** Premium-only, and only useful once a key is connected in Settings →
   * Account. The endpoint 403s basic accounts regardless. */
  isPremium: boolean;
  /** One line saying what this particular analysis will cover, so the
   * button isn't a mystery before it's been pressed. */
  blurb: string;
}

export function AiAnalystPanel({ leagueId, topic, isPremium, blurb }: Props) {
  const [result, setResult] = useState<AiAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (!isPremium) return null;

  async function ask() {
    setLoading(true);
    setError(null);
    try {
      setResult(await api.getAiAnalysis(leagueId, topic));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't get an analysis.");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="ai-analysis">
      <div className="form-row">
        <button onClick={ask} disabled={loading}>
          {loading ? "Thinking..." : result ? "Ask again" : "Ask the AI analyst"}
        </button>
        {result && (
          <span className="hint">
            {result.provider_label} &middot; {result.model}
          </span>
        )}
      </div>
      {!result && !error && <p className="hint">{blurb}</p>}
      {loading && (
        <p className="hint">
          Reasoning models take a little while &mdash; this can be 30 seconds or more.
        </p>
      )}
      {error && <p className="error">{error}</p>}
      {result && <div className="ai-analysis-body">{renderAnalysis(result.analysis)}</div>}
    </div>
  );
}
