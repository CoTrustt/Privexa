type PrivexaWordmarkProps = Readonly<{
  className?: string;
}>;

export function PrivexaWordmark({ className }: PrivexaWordmarkProps) {
  const classes = ["privexa-wordmark", className].filter(Boolean).join(" ");

  return (
    <span className={classes} role="img" aria-label="Privexa">
      <span className="privexa-wordmark-glyphs" aria-hidden="true">
        <span>Pr</span>
        <span className="privexa-wordmark-i" />
        <span>vexa</span>
      </span>
    </span>
  );
}
