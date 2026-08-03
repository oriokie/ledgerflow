/**
 * How the briefing was written, in the reader's language.
 *
 * `provider` is an internal identifier — `TemplateNarrator`, or a dotted import
 * path like `apps.intelligence.providers.coach.TemplateNarrator`. It was being
 * printed verbatim, so the one sentence whose whole job is to make the
 * narration trustworthy ended in a class name.
 *
 * What the reader actually needs to know is whether a model wrote this or
 * their own numbers did, so that is what we say. Unknown providers fall back
 * to the claim that is true of all of them.
 */
export function providerLabel(provider: string | undefined): string {
  const written = "Written from your own figures.";
  if (!provider) return written;
  const name = provider.split(".").pop() ?? provider;
  if (/template|rule/i.test(name)) return `${written} No AI involved.`;
  if (/llm|openai|anthropic|claude|gpt/i.test(name)) return "Written by AI from your own figures.";
  return written;
}
