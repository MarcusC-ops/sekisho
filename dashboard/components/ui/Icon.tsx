import type { SVGProps } from "react";

/** Stroke icons on a 24px grid, drawn in currentColor. */
const PATHS = {
  allow: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M7.8 12.4l2.8 2.8 5.6-6" />
    </>
  ),
  hold: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.8 8.5v7M14.2 8.5v7" />
    </>
  ),
  block: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M7.5 12h9" />
    </>
  ),
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  skip: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M8.5 12h7" strokeDasharray="2 2" />
    </>
  ),
  alert: (
    <>
      <path d="M12 3.5l9 16h-18z" />
      <path d="M12 10v4.2M12 17.2v.3" />
    </>
  ),
  error: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5v5.5M12 16.3v.3" />
    </>
  ),
  arrowRight: <path d="M4.5 12h15M13.5 6l6 6-6 6" />,
  arrowLeft: <path d="M19.5 12h-15M10.5 6l-6 6 6 6" />,
  copy: (
    <>
      <rect x="8.5" y="8.5" width="11" height="11" rx="2" />
      <path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5" />
    </>
  ),
  external: (
    <>
      <path d="M13.5 4.5h6v6M19.5 4.5l-8.5 8.5" />
      <path d="M18 14v4.5a1 1 0 0 1-1 1H5.5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1H10" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.2 2" />
    </>
  ),
  spinner: <path d="M12 3a9 9 0 1 1-8.2 5.3" />,
  chevronDown: <path d="M6 9.5l6 6 6-6" />,
  chevronUp: <path d="M6 14.5l6-6 6 6" />,
  close: <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />,
  shield: (
    <>
      <path d="M12 3.2l7.5 3v5.6c0 4.4-3.1 7.6-7.5 9-4.4-1.4-7.5-4.6-7.5-9V6.2z" />
      <path d="M8.8 12.2l2.2 2.2 4.3-4.6" />
    </>
  ),
  chain: (
    <>
      <path d="M10 13.5a4 4 0 0 0 5.7.2l2.8-2.8a4 4 0 0 0-5.7-5.7l-1.3 1.3" />
      <path d="M14 10.5a4 4 0 0 0-5.7-.2l-2.8 2.8a4 4 0 0 0 5.7 5.7l1.3-1.3" />
    </>
  ),
  flag: (
    <>
      <path d="M5.5 21V4" />
      <path d="M5.5 4.5h11l-2.2 4 2.2 4h-11" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5.5M12 7.7v.3" />
    </>
  ),
  play: <path d="M8 5.5v13l10.5-6.5z" />,
  reset: (
    <>
      <path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3" />
      <path d="M4.5 4.5v4h4" />
    </>
  ),
  escrow: (
    <>
      <rect x="4.5" y="10.5" width="15" height="10" rx="2" />
      <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3M12 14.5v2.5" />
    </>
  ),
  note: (
    <>
      <path d="M6 3.5h8.5l4 4V20a.5.5 0 0 1-.5.5H6a.5.5 0 0 1-.5-.5V4a.5.5 0 0 1 .5-.5z" />
      <path d="M14 3.5V8h4.5M8.5 12.5h7M8.5 16h5" />
    </>
  ),
  officer: (
    <>
      <circle cx="12" cy="8" r="3.8" />
      <path d="M4.5 20.5c1.2-3.8 4-5.6 7.5-5.6s6.3 1.8 7.5 5.6" />
    </>
  ),
  terminal: (
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="M7.5 9.5l3 2.5-3 2.5M12.5 15h4" />
    </>
  ),
  hash: <path d="M9.5 4l-2 16M16.5 4l-2 16M4.5 9h16M3.5 15h16" />,
  radio: (
    <>
      <circle cx="12" cy="12" r="2.2" />
      <path d="M7.8 16.2a6 6 0 0 1 0-8.4M16.2 7.8a6 6 0 0 1 0 8.4" />
    </>
  ),
  offline: (
    <>
      <path d="M4 4l16 16" />
      <path d="M7.8 16.2a6 6 0 0 1-.9-6.9M16.2 7.8a6 6 0 0 1 1 6.8" />
    </>
  ),
  code: <path d="M8.5 7.5L4 12l4.5 4.5M15.5 7.5L20 12l-4.5 4.5" />,
  eye: (
    <>
      <path d="M2.8 12s3.4-6.5 9.2-6.5 9.2 6.5 9.2 6.5-3.4 6.5-9.2 6.5S2.8 12 2.8 12z" />
      <circle cx="12" cy="12" r="2.8" />
    </>
  ),
  queue: <path d="M4.5 6.5h15M4.5 12h15M4.5 17.5h9" />,
  graph: (
    <>
      <circle cx="12" cy="12" r="2.6" />
      <circle cx="5" cy="5.5" r="1.8" />
      <circle cx="19" cy="6" r="1.8" />
      <circle cx="5.5" cy="18.5" r="1.8" />
      <circle cx="18.5" cy="18" r="1.8" />
      <path d="M6.4 6.8l3.6 3.4M17.6 7.3L14 10.4M7 17.3l3.2-3.4M17.1 16.8l-3.2-3" />
    </>
  ),
} as const;

export type IconName = keyof typeof PATHS;

interface IconProps extends Omit<SVGProps<SVGSVGElement>, "name"> {
  name: IconName;
  size?: number;
  /** Accessible label. Without one the icon is decorative (aria-hidden). */
  label?: string;
}

export function Icon({ name, size = 18, label, strokeWidth = 2, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
      {...rest}
    >
      {name === "play" ? <g fill="currentColor">{PATHS[name]}</g> : PATHS[name]}
    </svg>
  );
}
