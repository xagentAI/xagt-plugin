import type { Metadata } from 'next';
import Link from 'next/link';
import { Markdown, documentHeadings, documentTitle } from '@/components/Markdown';
import { METHODOLOGY_MARKDOWN } from '@/lib/methodology';

export const metadata: Metadata = {
  title: 'Methodology — Regimen',
  description:
    'How Regimen decides: Probabilistic and Deflated Sharpe, Minimum Track Record Length, stationary bootstrap intervals, regime attribution with a permutation test, and the controls Regimen runs against itself.',
};

/**
 * The methodology, rendered from the single source the MCP resource and the README also
 * quote. Nothing is restated here, so the page cannot drift from what the engine does.
 */
export default function MethodologyPage() {
  const headings = documentHeadings(METHODOLOGY_MARKDOWN);
  const title = documentTitle(METHODOLOGY_MARKDOWN) ?? 'Methodology';

  return (
    <div className="shell">
      <a className="skipLink" href="#document">
        Skip to the document
      </a>

      <header className="masthead">
        <Link className="mark" href="/">
          Regimen
        </Link>
        <span className="markSub">Statistical validation desk · does not trade · holds no funds</span>
        <nav className="mastheadNav">
          <Link className="navLink" href="/">
            Back to the desk
          </Link>
        </nav>
      </header>

      <div className="docHead">
        <p className="docKicker">Methodology · the published decision rule</p>
        <h1 className="docTitle">{title}</h1>
        <p className="docLead">
          Every tier below is a function of the statistics, not a judgement call. The formulae, the thresholds and
          the controls Regimen runs against its own verdict are all here, so a result can be checked rather than
          believed.
        </p>
      </div>

      <div className="docGrid">
        <aside className="docToc" aria-label="Sections">
          <p className="docTocLabel">Contents</p>
          <ul className="docTocList">
            {headings.map((heading) => (
              <li key={heading.id}>
                <a href={`#${heading.id}`}>{heading.text}</a>
              </li>
            ))}
          </ul>
        </aside>

        <main className="docBody" id="document">
          <Markdown source={METHODOLOGY_MARKDOWN} skipTitle />
        </main>
      </div>

      <div className="foot">
        <span>Regimen</span>
        <span>Validation only · no execution · no custody</span>
        <Link href="/">Back to the desk</Link>
      </div>
    </div>
  );
}
