import {
  AuthFlowType,
  B2BProducts,
  type PresentationConfig,
  type StytchB2BUIConfig,
} from "@stytch/nextjs/b2b";

export const stytchPresentation: PresentationConfig = {
  options: { hideHeaderText: true },
  theme: {
    "color-scheme": "light",
    "font-family":
      '"Space Grotesk", -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
    "font-family-mono": '"Space Mono", ui-monospace, SFMono-Regular, Menlo, monospace',
    spacing: "4px",
    "container-width": "100%",
    "mobile-breakpoint": "768px",
    "rounded-base": "4px",
    "text-base": "16px",
    "button-radius": "10px",
    "input-radius": "10px",
    "container-radius": "0px",
    shadow: "none",
    "transition-duration": "160ms",
    background: "#ffffff",
    foreground: "#18181b",
    primary: "#4f63f5",
    "primary-foreground": "#ffffff",
    secondary: "#f0f1f3",
    "secondary-foreground": "#18181b",
    muted: "#f0f1f3",
    "muted-foreground": "#71717a",
    accent: "#eef0ff",
    "accent-foreground": "#3547c8",
    border: "#e4e4e7",
    input: "#a1a1aa",
    ring: "#4f63f5",
    destructive: "#b42318",
    "destructive-foreground": "#ffffff",
    warning: "#9a6518",
    success: "#287a58",
    "container-border": "transparent",
  },
};

type StytchConfigInput = {
  appUrl: string;
  destination: string;
  sessionDurationMinutes: number;
};

export function buildStytchConfig({
  appUrl,
  sessionDurationMinutes,
}: StytchConfigInput): StytchB2BUIConfig {
  const normalizedAppUrl = appUrl.replace(/\/$/, "");
  const normalizedDuration =
    Number.isFinite(sessionDurationMinutes) && sessionDurationMinutes >= 5
      ? sessionDurationMinutes
      : 480;

  return {
    authFlowType: AuthFlowType.Discovery,
    products: [B2BProducts.emailMagicLinks],
    emailMagicLinksOptions: {
      discoveryRedirectURL: `${normalizedAppUrl}/authenticate`,
    },
    sessionOptions: { sessionDurationMinutes: normalizedDuration },
    directLoginForSingleMembership: {
      status: true,
      ignoreInvites: false,
      ignoreJitProvisioning: false,
    },
    directCreateOrganizationForNoMembership: false,
    disableCreateOrganization: true,
  };
}
