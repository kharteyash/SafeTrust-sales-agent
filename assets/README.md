# Brand assets

Drop the SafeTrust Mortgage logo here and the carousels use it automatically —
no code changes needed.

## Logo

Save the logo as **`logo.png`** (or `logo.jpg` / `logo.svg`) in this folder.

- `generate_carousels.py` base64-embeds it into every slide at build time.
- White margins are trimmed and the white background is knocked out automatically,
  so a plain screenshot/export works fine — a transparent PNG is ideal but not required.
- On **light** slides the full-color logo is shown; on the **dark / gradient** slides
  the logo is automatically knocked out to solid white so it stays readable.

### Optional: a dedicated reversed logo

If you have an official white/reversed version of the logo, save it as
**`logo-white.png`** (or `.svg`). When present it is used on the dark/gradient
slides instead of the auto white-knockout.

If no logo file is present, the carousels fall back to a simple "S" + wordmark lockup.
