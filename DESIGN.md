---
name: SMART SHELF AI
description: Operational retail platform for shelf monitoring, inventory, and assisted replenishment.
colors:
  ink: "#172435"
  page-background: "#f4f6f9"
  sidebar: "#111e2d"
  sidebar-text: "#d9e2ed"
  primary-action: "#142b40"
  mint-surface: "#d7f4e8"
  mint-ink: "#087c58"
  success: "#19865e"
  border: "#e1e7ee"
  surface: "#ffffff"
  muted-text: "#647386"
typography:
  body:
    fontFamily: "DM Sans, sans-serif"
    fontWeight: 400
  display:
    fontFamily: "Manrope, sans-serif"
    fontWeight: 800
rounded:
  sm: "6px"
  md: "9px"
  lg: "12px"
  xl: "15px"
---

## Overview

The current interface is a light operational dashboard with a dark navy navigation rail and restrained mint/green accents. It is designed for retail staff working through inventory, shelf evidence, and replenishment tasks. Preserve this visual language while improving hierarchy and consistency.

## Colors

- Primary text: `#172435`; page background: `#f4f6f9`; main surface: `#ffffff`.
- Navigation surface: `#111e2d`; navigation text: `#d9e2ed`.
- Primary action: `#142b40`.
- Mint surface and accent: `#d7f4e8` / `#087c58`.
- Borders: `#e1e7ee`; secondary text: `#647386`.
- Existing semantic status colors in `apps/web/src/styles.css` must remain semantically consistent. Do not collapse warning, danger, informational, and success states into one accent.

## Typography

- Body and operational content use DM Sans.
- Display headings use Manrope with strong weight.
- Preserve readable numeric data, labels, and dense table content. Avoid decorative display typography in controls or data.

## Layout

- Desktop uses a persistent dark sidebar and a flexible content region.
- Operational content uses clear page headers, filters/toolbars, metrics where meaningful, and task/evidence panels.
- Existing responsive breakpoints include 1050px, 900px, 700px, 600px, 560px, and 520px. Validate actual rendered layout at narrow widths; do not assume CSS breakpoints guarantee usability.
- Keep forms, tables, task rows, and review evidence readable without horizontal overflow.

## Elevation & Depth

- Prefer clear surfaces and subtle borders. Avoid stacking nested cards or adding decorative shadows without a functional hierarchy.
- Focus, hover, selected, disabled, loading, and error states must be visible and consistent.

## Shapes

- Existing corner radii range from 4px to 20px, with common panel/control radii around 8–12px. Consolidate only when it can be done without a disruptive redesign.
- Use rounded pills for compact statuses or controls, not as the default shape for every surface.

## Components

- Use the existing Lucide React icon system consistently.
- Buttons and form controls must retain clear labels and visible keyboard focus.
- Status labels must distinguish operational states such as unknown, pending review, failed analysis, and confirmed empty.
- Do not use color alone to communicate a status.

## Do's and Don'ts

- Do prioritize scanability, role-aware workflows, clear evidence provenance, and explicit human actions.
- Do preserve the API as the source of truth for authorization and operational decisions.
- Do label mock/synthetic demo content.
- Don't imply that a vision suggestion is a confirmed inventory fact.
- Don't introduce marketing hero layouts, decorative gradients, gratuitous animation, or card grids that reduce information density.
- Don't replace factual UI copy or change workflow semantics during visual polish.
