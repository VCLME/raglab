import type { ReactNode } from "react";

export type CodeLanguage = "python" | "sql" | "ts";

const KEYWORDS: Record<CodeLanguage, string[]> = {
  python: [
    "def", "return", "if", "else", "elif", "for", "in", "is", "not", "and", "or", "None", "True", "False",
    "import", "from", "with", "as", "lambda", "yield", "class", "while",
  ],
  sql: [
    "SELECT", "FROM", "JOIN", "ON", "WHERE", "AND", "OR", "ORDER", "BY", "LIMIT", "AS", "GROUP", "SUM", "LN",
    "DESC", "ASC", "WITH",
  ],
  ts: ["const", "let", "return", "if", "else", "function", "new", "true", "false", "null"],
};

const COMMENT: Record<CodeLanguage, string> = { python: "#[^\\n]*", sql: "--[^\\n]*", ts: "//[^\\n]*" };

/**
 * Tiny tokenizer for the learning-mode snippets: comments, strings, numbers,
 * keywords, function calls and operators. Enough for short excerpts; no
 * dependency.
 */
export function highlight(code: string, language: CodeLanguage): ReactNode[] {
  const keywords = new Set(language === "sql" ? KEYWORDS.sql.map((k) => k.toUpperCase()) : KEYWORDS[language]);
  const pattern = new RegExp(
    [
      `(?<comment>${COMMENT[language]})`,
      `(?<string>[rfbu]?"(?:\\\\.|[^"\\\\\\n])*"|[rfbu]?'(?:\\\\.|[^'\\\\\\n])*')`,
      `(?<number>\\b\\d+(?:\\.\\d+)?\\b)`,
      `(?<word>[A-Za-z_][\\w]*)`,
      `(?<op><=>|[=+\\-*/<>@])`,
    ].join("|"),
    "g"
  );
  const out: ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(code)) !== null) {
    if (match.index > last) out.push(code.slice(last, match.index));
    const groups = match.groups ?? {};
    const text = match[0];
    let kind: string | null = null;
    if (groups.comment) kind = "comment";
    else if (groups.string) kind = "string";
    else if (groups.number) kind = "number";
    else if (groups.op) kind = "op";
    else if (groups.word) {
      const probe = language === "sql" ? text.toUpperCase() : text;
      if (keywords.has(probe)) kind = "keyword";
      else if (code[pattern.lastIndex] === "(") kind = "fn";
    }
    out.push(kind ? <span key={match.index} className={`tok-${kind}`}>{text}</span> : text);
    last = pattern.lastIndex;
  }
  if (last < code.length) out.push(code.slice(last));
  return out;
}
