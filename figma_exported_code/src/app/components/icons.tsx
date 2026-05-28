import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement> & { size?: number };
const base = ({ size = 14, ...p }: P) => ({
  width: size,
  height: size,
  viewBox: "0 0 16 16",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.25,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  ...p,
});

export const IconLogo = (p: P) => (
  <svg {...base(p)}>
    <circle cx="4" cy="4" r="1.6" />
    <circle cx="12" cy="4" r="1.6" />
    <circle cx="8" cy="12" r="1.6" />
    <path d="M5.4 5.2L7 10.6M10.6 5.2L9 10.6M5.6 4h4.8" />
  </svg>
);
export const IconBranch = (p: P) => (
  <svg {...base(p)}>
    <circle cx="4" cy="3" r="1.2" /><circle cx="4" cy="13" r="1.2" /><circle cx="12" cy="6" r="1.2" />
    <path d="M4 4.2v7.6M4 8c0-2 1-3 3-3h3.8" />
  </svg>
);
export const IconCommit = (p: P) => (
  <svg {...base(p)}><circle cx="8" cy="8" r="2.4" /><path d="M2 8h3.2M10.8 8H14" /></svg>
);
export const IconRepo = (p: P) => (
  <svg {...base(p)}><path d="M3 2.5h8.5A1.5 1.5 0 0 1 13 4v9.5H4.5A1.5 1.5 0 0 1 3 12V2.5zM3 11.5h10" /></svg>
);
export const IconSearch = (p: P) => (
  <svg {...base(p)}><circle cx="7" cy="7" r="4" /><path d="M10 10l3 3" /></svg>
);
export const IconCommand = (p: P) => (
  <svg {...base(p)}>
    <path d="M5 3.5A1.5 1.5 0 1 1 6.5 5H5V3.5zM11 3.5A1.5 1.5 0 1 0 9.5 5H11V3.5zM5 12.5A1.5 1.5 0 1 0 6.5 11H5v1.5zM11 12.5A1.5 1.5 0 1 1 9.5 11H11v1.5zM5 5h6v6H5z" />
  </svg>
);
export const IconSun = (p: P) => (
  <svg {...base(p)}><circle cx="8" cy="8" r="2.6" /><path d="M8 1.5v1.6M8 12.9v1.6M1.5 8h1.6M12.9 8h1.6M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M3.4 12.6l1.1-1.1M11.5 4.5l1.1-1.1" /></svg>
);
export const IconMoon = (p: P) => (
  <svg {...base(p)}><path d="M13 9.5A5.5 5.5 0 0 1 6.5 3a5 5 0 1 0 6.5 6.5z" /></svg>
);
export const IconMonitor = (p: P) => (
  <svg {...base(p)}><rect x="2" y="3" width="12" height="8.5" rx="1" /><path d="M5.5 14h5M8 11.5V14" /></svg>
);
export const IconMenu = (p: P) => (
  <svg {...base(p)}><path d="M3 4.5h10M3 8h10M3 11.5h10" /></svg>
);
export const IconDot = (p: P) => (
  <svg {...base(p)}><circle cx="8" cy="8" r="3" fill="currentColor" stroke="none" /></svg>
);
export const IconChevronRight = (p: P) => (
  <svg {...base(p)}><path d="M6 3l4 5-4 5" /></svg>
);
export const IconChevronDown = (p: P) => (
  <svg {...base(p)}><path d="M3 6l5 4 5-4" /></svg>
);
export const IconCopy = (p: P) => (
  <svg {...base(p)}><rect x="5" y="5" width="8" height="8" rx="1" /><path d="M3 11V4a1 1 0 0 1 1-1h7" /></svg>
);
export const IconExport = (p: P) => (
  <svg {...base(p)}><path d="M8 10V2M5 5l3-3 3 3M3 10v3a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1v-3" /></svg>
);
export const IconBook = (p: P) => (
  <svg {...base(p)}><path d="M3 3h4a2 2 0 0 1 2 2v8a2 2 0 0 0-2-2H3V3zM13 3H9a2 2 0 0 0-2 2v8a2 2 0 0 1 2-2h4V3z" /></svg>
);
export const IconClose = (p: P) => (
  <svg {...base(p)}><path d="M4 4l8 8M12 4l-8 8" /></svg>
);
export const IconPlus = (p: P) => (
  <svg {...base(p)}><path d="M8 3v10M3 8h10" /></svg>
);
export const IconWarning = (p: P) => (
  <svg {...base(p)}><path d="M8 2.5l6 11H2l6-11zM8 7v3M8 11.6v.1" /></svg>
);
export const IconArrow = (p: P) => (
  <svg {...base(p)}><path d="M3 8h10M9 4l4 4-4 4" /></svg>
);
export const IconRefresh = (p: P) => (
  <svg {...base(p)}><path d="M13 8A5 5 0 1 1 8 3M13 3v5H8" /></svg>
);
export const IconSettings = (p: P) => (
  <svg {...base(p)}>
    <circle cx="8" cy="8" r="2.2" />
    <path d="M8 2v1.5M8 12.5V14M2 8h1.5M12.5 8H14M3.5 3.5l1.1 1.1M11.4 11.4l1.1 1.1M3.5 12.5l1.1-1.1M11.4 4.6l1.1-1.1" />
  </svg>
);
export const IconHelp = (p: P) => (
  <svg {...base(p)}>
    <circle cx="8" cy="8" r="5.5" />
    <path d="M6.2 6.2A1.8 1.8 0 0 1 8 5a1.8 1.8 0 0 1 .8 3.4c-.4.2-.8.7-.8 1.3" />
    <circle cx="8" cy="11.5" r=".5" fill="currentColor" stroke="none" />
  </svg>
);
export const IconChevronUp = (p: P) => (
  <svg {...base(p)}><path d="M3 10l5-4 5 4" /></svg>
);
