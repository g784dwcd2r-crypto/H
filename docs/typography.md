# Disclosure visual identity

The agreed September 2026 visual identity kit is the reference for the public site, research workspace and platform administration. It supersedes the earlier Sabon / Neue Haas Unica and plum / blush proposal.

## Colours

| Token | Value | Use |
| --- | --- | --- |
| Ivory | `#FAFAF9` | Primary canvas |
| Ink | `#0F0E0D` | Reading text and high-contrast sections |
| Royal blue | `#274BD8` | Primary actions, focus indicators and emphasis |
| Pale periwinkle | `#EEF2FF` | Selected cells, source context and selected navigation surfaces |
| White | `#FFFFFF` | Cards and inputs |
| Surface | `#F2F1F0` | Quiet secondary surfaces |
| Border | `#E5E5E3` | Fine separators and card borders |

The interface stays predominantly ivory/white. Blue is used for actions; periwinkle is a background, never low-contrast text. Text, underlines, icons and labels identify selected, warning and error states in addition to colour. Gain/loss and warning colours remain semantically distinct. Darker muted text and blue hover colours are functional derivatives; the primary kit colours remain exact.

## Typography and layout

| Role | Family | Desktop / mobile | Weight | Line height |
| --- | --- | --- | --- | --- |
| Homepage hero | EB Garamond | 72 / 44px | Regular 400 | 1.08 |
| Page titles / editorial sections | EB Garamond | 48 / 34px | Regular 400 | 1.12 |
| Card headings | Albert Sans | 24 / 22px | Medium 500 | 1.25 |
| Introductions | Albert Sans | 20 / 18px | Regular 400 | 1.5 |
| Body copy | Albert Sans | 16 / 16px | Regular 400 | 1.5 |
| Navigation / buttons | Albert Sans | 14 / 14px | Medium 500 | 1.2 |
| Tables / labels | Albert Sans | 14 / 14px | Regular 400 / Medium 500 | 1.4 |

Headings use natural tracking. The wordmark uses EB Garamond Regular. Main homepage content uses a 12-column desktop grid with 24px gutters and a five/seven-column hero, 48px outer margins and one column below 1180px. Mobile outer margins are 20px. Mobile typography begins at 640px. Introductions target 55ch; headline-to-description spacing is 24–32px. Major sections use 96px desktop / 64px mobile spacing, with tighter spacing inside research tools.

Controls have 8px corners; cards use 12px, larger panels 16px. Shadows stay minimal except where an overlay must be distinguished from the page underneath. Financial tables use tabular sans-serif numerals and contained horizontal scrolling. Raw XML and document diffs retain monospace; the original filing iframe retains source formatting. Existing finite animations and reduced-motion support are preserved.

## Font delivery

The actual supplied EB Garamond and Albert Sans fonts are bundled under `web/public/fonts` and loaded through `web/app/fonts.css`. There is no Adobe project, account, API key or external font service dependency. The old `ADOBE_FONTS_KIT_ID` setting is no longer used.

Normal EB Garamond Regular and Albert Sans Regular are preloaded. Albert Sans Medium loads when used; genuine italic faces are available on demand. `font-display: swap` keeps text visible if a font request is slow. Synthetic weights/styles are disabled; emphasis uses the supplied Medium face. The three normal faces total 185,044 bytes before HTTP overhead.

Files were converted from the supplied TTFs to WOFF2 using fontTools 4.65.0 and Brotli 1.2.0, retaining the full character maps and font names. The original SIL Open Font License and copyright notices are included for each family. `web/public/fonts/manifest.json` records each source archive entry, source/output SHA-256 digest, byte size and weight.

To reproduce a conversion with an extracted source TTF:

```python
from fontTools.ttLib import TTFont

font = TTFont("AlbertSans-Regular.ttf", recalcTimestamp=False)
font.flavor = "woff2"
font.save("albert-sans-regular.woff2")
```

The browser smoke test checks that all six font faces load successfully from this application, including real Regular and Medium weights. Review hero wrapping, live contrast, selected table cells, keyboard focus, menus and horizontal overflow at desktop/tablet/mobile widths when changing the identity.
