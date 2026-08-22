import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PrivexaWordmark } from "./privexa-wordmark";

afterEach(cleanup);

describe("PrivexaWordmark", () => {
  it("keeps the stylised lettering exposed as the complete brand name", () => {
    const { container } = render(<PrivexaWordmark />);

    expect(screen.getByRole("img", { name: "Privexa" })).toBeInTheDocument();
    expect(container.querySelector(".privexa-wordmark-glyphs")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  });

  it("accepts sizing and placement classes from each brand surface", () => {
    render(<PrivexaWordmark className="workspace-brand" />);

    expect(screen.getByRole("img", { name: "Privexa" })).toHaveClass(
      "privexa-wordmark",
      "workspace-brand",
    );
  });
});
