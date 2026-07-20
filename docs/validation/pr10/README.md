# PR10 UI Validation

The Streamlit dashboard was checked with an isolated fixture only. The fixture
was kept outside the working repository; `records.csv` in this branch was not
modified.

## Desktop (1280px)

- [Balanced complete day](complete_desktop.png): `complete_day`, high confidence,
  Nutrition Score, protein strength, and compact breakdown are visible.
- [Partial day](partial_desktop.png): `partial_day`, 60% progress-aware target,
  and cautious dinner-oriented wording are visible.
- [Low-confidence day](low_confidence_desktop.png): unresolved meal input is
  labeled `low` confidence with a data-quality action.

## Mobile

- [Partial day at 390px](partial_mobile_390.png): `scrollWidth == clientWidth == 390`.
- [Complete day at 430px](complete_mobile_430.png): `scrollWidth == clientWidth == 430`.

No Streamlit exceptions occurred in these checks. The Nutrition Intelligence
cards, strengths, priorities, and actions remain readable in the narrow views.

## macOS Desktop CSS Regression

- [Chrome desktop after fix](macos_chrome_desktop_fixed.png): Body Score and
  Today's Metrics cards retain dark foreground text on their white card
  backgrounds.
- [Safari desktop after fix](macos_safari_desktop_fixed.png): the same card
  contrast is rendered correctly in Safari.
- Chrome was checked with DevTools cache disabled. Card computed styles were
  `color: rgb(49, 49, 63)`, `opacity: 1`, `filter: none`,
  `backdrop-filter: none`, and `mix-blend-mode: normal`.
- The Nutrition Intelligence and shared component-card selectors are scoped to
  their dedicated wrapper classes. No PR10 selectors target generic elements or
  Streamlit selectors such as `div`, `p`, `span`, `.stMarkdown`, `.stMetric`,
  or `.stContainer`.

## Body Score Card Follow-up

- [Before at 1280px](body_score_before_macos_chrome_1280.png): the white Body
  Score cards inherited the macOS dark-theme foreground
  `color: rgb(250, 250, 250)` for their titles and values.
- [After at 1280px](body_score_after_macos_chrome_1280.png): title and value use
  `rgb(49, 49, 63)`; the subtitle uses `rgba(49, 51, 63, 0.68)`.
- [After at 390px](body_score_after_mobile_390.png) and
  [after at 430px](body_score_after_mobile_430.png): cards remain one column,
  retain their existing mobile layout, and have no horizontal overflow.
- [Safari desktop after](body_score_after_macos_safari.png): the installed
  macOS Safari renders the Body Score title, value, and subtitle with readable
  dark foregrounds. Safari's Apple Events JavaScript inspection setting was
  disabled, so its computed values could not be exported; visual rendering and
  the card DOM text were verified in the actual Safari app.
- Chrome computed styles at all three widths confirm explicit foreground and
  `-webkit-text-fill-color`, `opacity: 1`, `filter: none`,
  `mix-blend-mode: normal`, `background-clip: border-box`, and no background
  image. The Body Score selectors use literal colors and do not depend on theme
  CSS variables. A separate light-theme Streamlit run at 1280px produced the
  same white card background and dark foreground without horizontal overflow.
