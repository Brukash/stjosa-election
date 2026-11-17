# Self-hosted fonts

These files are served from the app instead of `next/font/google`, because the
Google Fonts download fails silently in some build environments and next/font
then substitutes Georgia — which quietly changes the whole design.

| File | Family | Weights | Source |
| --- | --- | --- | --- |
| `instrument-serif-400.woff2` | Instrument Serif | 400 normal | [Google Fonts](https://fonts.google.com/specimen/Instrument+Serif) |
| `instrument-serif-400-italic.woff2` | Instrument Serif | 400 italic | [Google Fonts](https://fonts.google.com/specimen/Instrument+Serif) |
| `schibsted-grotesk-400-700.woff2` | Schibsted Grotesk | 400–700 variable | [Google Fonts](https://fonts.google.com/specimen/Schibsted+Grotesk) |

Both families are licensed under the **SIL Open Font License 1.1**, which
permits self-hosting and redistribution with the licence included:
<https://openfontlicense.org>.

To refresh a file, download the latin `woff2` for the family from the Google
Fonts CSS API and replace it here; keep the filenames so `app/layout.tsx` does
not change.
