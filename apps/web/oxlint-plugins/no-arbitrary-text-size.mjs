/**
 * Ban arbitrary Tailwind text-SIZE utilities so sizes stay on the named
 * `--text-*` scale in `src/index.css`.
 *
 * Sizes are caught in every form Tailwind accepts:
 *   text-[13px]  text-[13.5rem]  text-[100%]
 *   text-[length:13px]      (explicit type hint)
 *   text-(length:--fs)      (v4 parenthesis form)
 *   text-[clamp(...)]  text-[min(...)]  text-[max(...)]  text-[calc(...)]
 *   text-[var(--fs)]        (variable whose name reads as a size)
 *
 * Colors stay valid, because a false positive that blocks a legitimate color
 * is worse than missing a size: text-[#fff], text-[rgb(...)],
 * text-[oklch(...)], text-[hsl(...)], text-[color-mix(...)], and
 * text-[var(--color-x)] all pass.
 *
 * Intentionally out of scope, since a literal scan cannot see the value:
 *   - runtime interpolation, e.g. text-[${n}px] or text-[" + n + "px]
 *   - a bare CSS variable whose name gives no size hint, e.g.
 *     text-[var(--thing)] — Tailwind cannot type it either, so it is left
 *     alone rather than guessed at. Write text-(length:--thing) instead,
 *     which this rule flags.
 */
const SIZE_UNITS = /^[0-9.]+(?:px|rem|em|pt|ch|vw|vh|ex|lh|%)$/;
const MATH_SIZE = /^(?:clamp|min|max|calc)\(/;
const VAR = /^var\(\s*--([\w-]+)/;
// A variable name that reads as a font size rather than a color.
const SIZE_VAR = /(?:^|-)(?:fs|font-size|text-size|size|length|lh)(?:-|$)/i;
const START = /(?<![\w-])text-([[(])/g;

/** Classify the inside of an arbitrary `text-*` value. */
function isSize(content) {
  const value = content.trim();
  if (/^(?:length|size):/.test(value)) return true;
  if (SIZE_UNITS.test(value)) return true;
  if (MATH_SIZE.test(value)) return true;
  if (value.startsWith("var(")) {
    const name = value.match(VAR)?.[1];
    // Unknown variable: assume color, since blocking a color is worse.
    return Boolean(name && SIZE_VAR.test(name));
  }
  return false;
}

/** Every arbitrary text-size utility in a class string. */
function findSizes(value) {
  const found = [];
  for (const match of value.matchAll(START)) {
    const open = match[1];
    const close = open === "[" ? "]" : ")";
    const start = match.index;
    let depth = 0;
    let end = -1;
    for (let i = start + match[0].length - 1; i < value.length; i += 1) {
      if (value[i] === open) depth += 1;
      else if (value[i] === close) {
        depth -= 1;
        if (depth === 0) {
          end = i;
          break;
        }
      }
    }
    if (end === -1) continue;
    const content = value.slice(start + match[0].length, end);
    if (isSize(content)) found.push(value.slice(start, end + 1));
  }
  return found;
}

export default {
  meta: { name: "fleet" },
  rules: {
    "no-arbitrary-text-size": {
      meta: {
        type: "problem",
        docs: {
          description:
            "Ban arbitrary Tailwind text-size utilities; use a named --text-* token.",
        },
        schema: [],
      },
      create(context) {
        function check(node) {
          const value =
            node.type === "TemplateElement" ? node.value?.cooked : node.value;
          if (typeof value !== "string") return;
          for (const size of findSizes(value)) {
            context.report({
              node,
              message: `Arbitrary Tailwind text size "${size}". Use a named --text-* token.`,
            });
          }
        }
        return { Literal: check, TemplateElement: check };
      },
    },
  },
};
