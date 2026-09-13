# Disclosure typography

The interface uses ivory `#FAFAF9`, ink `#0F0E0D`, muted plum `#373340`, and blush `#D9CDCC`. Blush is a surface and border accent; body copy and interactive text use ink, plum, or the darker muted token. Semantic gain/loss and warning colours stay distinct.

| Role | Family | Desktop / mobile | Weight | Line height |
| --- | --- | --- | --- | --- |
| Homepage hero | Sabon LT Pro | 72 / 44px | 400 | 1.08 |
| Page titles / editorial sections | Sabon LT Pro | 48 / 34px | 400 | 1.12 |
| Card headings | Neue Haas Unica | 24 / 22px | 500 | 1.25 |
| Introductions | Neue Haas Unica | 20 / 18px | 400 | 1.5 |
| Body copy | Neue Haas Unica | 16 / 16px | 400 | 1.5 |
| Navigation / buttons | Neue Haas Unica | 14 / 14px | 500 | 1.2 |
| Tables / labels | Neue Haas Unica | 14 / 14px | 400 / 500 | 1.4 |

Mobile type starts at 640px. The homepage hero uses three explicit lines. Introductions target 55ch, with 24–32px after the heading. Major desktop homepage sections use 96px spacing. Card internals and research toolbars remain more compact. Text inputs stay at 16px for readability and to avoid focus zoom on mobile browsers. Figures use tabular numerals; source XML and diff code retain monospace. Existing reduced-motion support remains enabled.

## Font delivery

Exact font binaries are **not bundled**. The default build currently renders Georgia / Arial unless the named fonts are already installed. A CSS family name alone does not download a font.

Both families are offered by Adobe Fonts:

- [Sabon](https://fonts.adobe.com/fonts/sabon)
- [Neue Haas Unica](https://fonts.adobe.com/fonts/neue-haas-unica)

To activate them, create a licensed Adobe Fonts **web project** containing Sabon regular and Neue Haas Unica regular, medium, and semibold. Select `font-display: swap` in that project's settings, then configure `ADOBE_FONTS_KIT_ID` in the web server environment with the seven-character project ID. The root layout loads the corresponding official `https://use.typekit.net/<id>.css` stylesheet. The CSS stacks use Adobe's `sabon` and `neue-haas-unica` family names. Restart the web server after configuration. No external font request is made when the ID is absent or invalid.

See [Adobe's website setup instructions](https://helpx.adobe.com/fonts/web/introduction/add-fonts-website.html). Adobe-hosted web projects do not provide self-hosting rights; use a suitable Monotype webfont licence if self-hosting is preferred. Do not commit licensed font binaries to this public repository without distribution permission.

After activation, verify in browser network/font tools that the stylesheet and font files load, then recheck desktop/mobile wrapping with the real font metrics. The current visual acceptance is for the fallback rendering, not proof of the licensed fonts being active.
