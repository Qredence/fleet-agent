const BANNED = /(?<![\w-])text-\[[0-9.]+(?:px|rem|em|pt|ch|vw|vh)\]/g;

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
          for (const match of value.matchAll(BANNED)) {
            context.report({
              node,
              message: `Arbitrary Tailwind text size "${match[0]}". Use a named --text-* token.`,
            });
          }
        }
        return { Literal: check, TemplateElement: check };
      },
    },
  },
};
