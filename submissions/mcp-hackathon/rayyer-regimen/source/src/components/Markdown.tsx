import type { ReactNode } from 'react';
import styles from './Markdown.module.css';

/**
 * A deliberately small Markdown renderer.
 *
 * It handles exactly what the methodology document uses — ATX headings, paragraphs with
 * soft wraps, fenced code blocks, pipe tables, dash lists with indented continuations,
 * and inline bold, emphasis and code — and nothing else. It builds React elements, so
 * the source is never handed to `dangerouslySetInnerHTML`: an unsupported construct
 * degrades to visible literal text rather than to injected markup.
 */

export interface DocumentHeading {
  readonly id: string;
  readonly text: string;
}

type Block =
  | { readonly kind: 'heading'; readonly level: number; readonly text: string; readonly id: string }
  | { readonly kind: 'paragraph'; readonly text: string }
  | { readonly kind: 'code'; readonly text: string }
  | { readonly kind: 'list'; readonly items: readonly string[] }
  | { readonly kind: 'table'; readonly head: readonly string[]; readonly rows: ReadonlyArray<readonly string[]> };

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function splitRow(line: string): string[] {
  return line
    .replace(/^\s*\|/, '')
    .replace(/\|\s*$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

const HEADING = /^(#{1,6})\s+(.*)$/;
const LIST_ITEM = /^[-*]\s+(.*)$/;
const TABLE_DIVIDER = /^\s*\|?[\s:-]*-[\s|:-]*\|?\s*$/;

function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n/g, '\n').split('\n');
  const blocks: Block[] = [];
  let index = 0;

  const line = (at: number): string => lines[at] ?? '';

  while (index < lines.length) {
    const current = line(index);

    if (current.trim() === '') {
      index += 1;
      continue;
    }

    if (current.trimStart().startsWith('```')) {
      const body: string[] = [];
      index += 1;
      while (index < lines.length && !line(index).trimStart().startsWith('```')) {
        body.push(line(index));
        index += 1;
      }
      index += 1; // the closing fence
      blocks.push({ kind: 'code', text: body.join('\n') });
      continue;
    }

    const heading = HEADING.exec(current);
    if (heading) {
      const text = (heading[2] ?? '').trim();
      blocks.push({ kind: 'heading', level: (heading[1] ?? '#').length, text, id: slugify(text) });
      index += 1;
      continue;
    }

    if (current.trimStart().startsWith('|')) {
      const rows: string[][] = [];
      while (index < lines.length && line(index).trimStart().startsWith('|')) {
        rows.push(splitRow(line(index)));
        index += 1;
      }
      const head = rows[0] ?? [];
      const body = rows.slice(1).filter((row) => !TABLE_DIVIDER.test(`|${row.join('|')}|`));
      blocks.push({ kind: 'table', head, rows: body });
      continue;
    }

    if (LIST_ITEM.test(current.trimStart()) && !current.startsWith('  ')) {
      const items: string[] = [];
      while (index < lines.length) {
        const raw = line(index);
        if (raw.trim() === '') break;
        const item = LIST_ITEM.exec(raw.trimStart());
        if (item && !raw.startsWith('  ')) {
          items.push(item[1] ?? '');
          index += 1;
          continue;
        }
        if (raw.startsWith('  ') && items.length > 0) {
          items[items.length - 1] = `${items[items.length - 1] ?? ''} ${raw.trim()}`;
          index += 1;
          continue;
        }
        break;
      }
      blocks.push({ kind: 'list', items });
      continue;
    }

    const paragraph: string[] = [];
    while (index < lines.length) {
      const raw = line(index);
      if (raw.trim() === '') break;
      if (HEADING.test(raw) || raw.trimStart().startsWith('```') || raw.trimStart().startsWith('|')) break;
      if (LIST_ITEM.test(raw.trimStart()) && !raw.startsWith('  ')) break;
      paragraph.push(raw.trim());
      index += 1;
    }
    blocks.push({ kind: 'paragraph', text: paragraph.join(' ') });
  }

  return blocks;
}

const INLINE = /`([^`]+)`|\*\*([^*]+)\*\*|\*([^*\n]+)\*/g;

/** Inline spans, produced as elements. Anything unmatched stays literal text. */
function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let key = 0;
  INLINE.lastIndex = 0;

  for (let match = INLINE.exec(text); match !== null; match = INLINE.exec(text)) {
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index));
    const [, code, bold, emphasis] = match;
    key += 1;
    if (code !== undefined) {
      nodes.push(
        <code key={`${keyPrefix}-c${key}`} className={styles.inlineCode}>
          {code}
        </code>,
      );
    } else if (bold !== undefined) {
      nodes.push(<strong key={`${keyPrefix}-b${key}`}>{bold}</strong>);
    } else if (emphasis !== undefined) {
      nodes.push(<em key={`${keyPrefix}-e${key}`}>{emphasis}</em>);
    }
    cursor = match.index + match[0].length;
  }

  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

/** The document's own level-1 title, so a page never has to restate it. */
export function documentTitle(source: string): string | null {
  for (const block of parseBlocks(source)) {
    if (block.kind === 'heading' && block.level === 1) return block.text;
  }
  return null;
}

export function documentHeadings(source: string): DocumentHeading[] {
  return parseBlocks(source)
    .filter((block): block is Extract<Block, { kind: 'heading' }> => block.kind === 'heading')
    .filter((block) => block.level === 2)
    .map((block) => ({ id: block.id, text: block.text }));
}

export interface MarkdownProps {
  readonly source: string;
  /** Headings at or below this level are rendered; the level-1 title is usually shown separately. */
  readonly skipTitle?: boolean;
}

export function Markdown({ source, skipTitle = false }: MarkdownProps) {
  const blocks = parseBlocks(source);

  return (
    <>
      {blocks.map((block, index) => {
        const key = `b${index}`;
        switch (block.kind) {
          case 'heading': {
            if (block.level === 1) {
              return skipTitle ? null : (
                <h1 key={key} className={styles.h1}>
                  {renderInline(block.text, key)}
                </h1>
              );
            }
            if (block.level === 2) {
              return (
                <h2 key={key} id={block.id} className={styles.h2}>
                  {renderInline(block.text, key)}
                </h2>
              );
            }
            return (
              <h3 key={key} id={block.id} className={styles.h3}>
                {renderInline(block.text, key)}
              </h3>
            );
          }
          case 'paragraph':
            return (
              <p key={key} className={styles.p}>
                {renderInline(block.text, key)}
              </p>
            );
          case 'code':
            return (
              <pre key={key} className={styles.pre}>
                <code>{block.text}</code>
              </pre>
            );
          case 'list':
            return (
              <ul key={key} className={styles.ul}>
                {block.items.map((item, itemIndex) => (
                  <li key={`${key}-i${itemIndex}`}>{renderInline(item, `${key}-i${itemIndex}`)}</li>
                ))}
              </ul>
            );
          case 'table':
            return (
              <div key={key} className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      {block.head.map((cell, cellIndex) => (
                        <th key={`${key}-h${cellIndex}`} scope="col">
                          {renderInline(cell, `${key}-h${cellIndex}`)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, rowIndex) => (
                      <tr key={`${key}-r${rowIndex}`}>
                        {row.map((cell, cellIndex) => (
                          <td key={`${key}-r${rowIndex}c${cellIndex}`}>
                            {renderInline(cell, `${key}-r${rowIndex}c${cellIndex}`)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
        }
      })}
    </>
  );
}
