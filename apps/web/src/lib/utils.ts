import { createCn } from "cn/config"

/**
 * Named type-scale steps from `index.css`.
 *
 * `cn` resolves `text-<word>` as a color unless the word is a known font
 * size, so without this list a merge such as
 * `cn("text-meta", "text-muted-foreground")` would drop the size and keep
 * only the color. Registering the names keeps size and color independent,
 * exactly as they were when sizes were arbitrary pixel values.
 * Keep this list in step with the `--text-*` tokens in `index.css`.
 */
const typeScale = [
  "3xs",
  "2xs",
  "meta",
  "caption",
  "xs-plus",
  "body",
  "body-plus",
  "subtitle",
  "subtitle-plus",
  "title",
  "title-plus",
]

export const cn = createCn({
  extend: { classGroups: { "font-size": [{ text: typeScale }] } },
})
