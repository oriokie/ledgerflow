import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  Illustration,
  IllustrationStyleProvider,
  ILLUSTRATION_NAMES,
  ILLUSTRATION_STYLES,
} from ".";

describe("illustration system", () => {
  it("is hidden from assistive tech unless it carries meaning", () => {
    // An illustration that repeats the heading beside it is noise in a screen
    // reader. Decorative is the default; a title is the opt-in.
    const { container, rerender } = render(<Illustration name="vault" />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).not.toHaveAttribute("role");

    rerender(<Illustration name="vault" title="A locked vault" />);
    const labelled = container.querySelector("svg")!;
    expect(labelled).toHaveAttribute("role", "img");
    expect(labelled).toHaveAttribute("aria-label", "A locked vault");
    expect(labelled).not.toHaveAttribute("aria-hidden");
  });

  it("gives every instance its own gradient ids", () => {
    // Two illustrations sharing a gradient id makes the second silently adopt
    // the first one's fill — a bug that only appears on pages with both.
    const { container } = render(
      <>
        <Illustration name="vault" />
        <Illustration name="growth" />
      </>,
    );
    const ids = [...container.querySelectorAll("linearGradient, radialGradient")].map((g) => g.id);
    expect(ids.length).toBeGreaterThan(0);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("draws entirely from design tokens", () => {
    // The whole reason this is SVG rather than a rendered image: it recolours
    // itself in dark mode with no second asset, and its contrast is gated by
    // the same script as the rest of the palette. A literal colour would break
    // both of those silently.
    const { container } = render(<Illustration name="secure" />);
    const markup = container.innerHTML;
    expect(markup).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(markup).not.toMatch(/rgba?\(/i);
    expect(markup).toContain("var(--lf-");
  });

  it("keeps application-facing illustrations small", () => {
    // The brief's rule: data screens stay data-focused, so artwork inside the
    // workspace is an accent rather than a subject.
    const { container } = render(<Illustration name="no-data" size="spot" />);
    expect(container.querySelector(".lf-illus-frame")).toHaveAttribute("data-size", "spot");
  });
  it("renders every name in both styles", () => {
    // The style switch is only safe because the two sets are interchangeable.
    // A name present in one and missing from the other would blank a surface
    // the moment an operator changed the setting — and it would be a surface
    // nobody thought to check, because the setting is platform-wide.
    for (const name of ILLUSTRATION_NAMES) {
      for (const style of ILLUSTRATION_STYLES) {
        const { container, unmount } = render(<Illustration name={name} style={style} />);
        expect(container.querySelector("svg"), `${name} in ${style}`).not.toBeNull();
        unmount();
      }
    }
  });

  it("follows the platform setting, and falls back to clay without one", () => {
    // An unreachable settings endpoint must degrade to *an* illustration set,
    // never to blank surfaces.
    const { container: fallback } = render(
      <IllustrationStyleProvider style={undefined}>
        <Illustration name="welcome" />
      </IllustrationStyleProvider>,
    );
    expect(fallback.querySelector(".lf-illus-frame")).toHaveAttribute("data-style", "clay");

    const { container: doodle } = render(
      <IllustrationStyleProvider style="doodle">
        <Illustration name="welcome" />
      </IllustrationStyleProvider>,
    );
    expect(doodle.querySelector(".lf-illus-frame")).toHaveAttribute("data-style", "doodle");
  });

  it("draws people in the doodle set", () => {
    // The point of the second set: the clay language draws the thing, this one
    // draws somebody doing something with it.
    const { container } = render(<Illustration name="welcome" style="doodle" />);
    // The figure is a head circle plus limbs — at minimum a circle and paths.
    expect(container.querySelectorAll("circle").length).toBeGreaterThan(0);
    expect(container.querySelectorAll("path").length).toBeGreaterThan(3);
  });

  it("puts a trail and money in every motion motif", () => {
    // The point of the third set: money in transit. A motif with a trail and
    // nothing travelling on it is a person looking at a shape, and a motif
    // with neither is just the clay set drawn thinner.
    for (const name of ILLUSTRATION_NAMES) {
      const { container, unmount } = render(<Illustration name={name} style="motion" />);
      expect(container.querySelector(".lf-motion-trail"), `${name} has no trail`).not.toBeNull();
      expect(
        container.querySelectorAll(".lf-motion-travel").length,
        `${name} has no money travelling`,
      ).toBeGreaterThan(0);
      unmount();
    }
  });

  it("never puts an animation and a transform on the same SVG element", () => {
    // A CSS `transform` from an animation *replaces* the `transform`
    // presentation attribute rather than composing with it. With both on one
    // element every note in the set snapped to the SVG origin and the money
    // piled up invisibly in the top-left corner — which looked, at a glance,
    // exactly like an illustration that simply had no money in it.
    for (const name of ILLUSTRATION_NAMES) {
      const { container, unmount } = render(<Illustration name={name} style="motion" />);
      for (const el of container.querySelectorAll(
        ".lf-motion-travel, .lf-motion-bob, .lf-motion-pulse, .lf-motion-turn",
      )) {
        expect(el.getAttribute("transform"), `${name}: ${el.className}`).toBeNull();
      }
      unmount();
    }
  });

  it("holds still inside the application unless a caller opts in", () => {
    // Spot illustrations sit beside numbers someone is reading. The console's
    // style picker is the one place that must override it — an operator
    // choosing an animated set has to be able to see it move.
    const { container: still } = render(<Illustration name="welcome" style="motion" size="spot" />);
    expect(still.querySelector(".lf-illus-frame")).not.toHaveAttribute("data-animate");

    const { container: moving } = render(
      <Illustration name="welcome" style="motion" size="spot" animate />,
    );
    expect(moving.querySelector(".lf-illus-frame")).toHaveAttribute("data-animate", "true");
  });
});
