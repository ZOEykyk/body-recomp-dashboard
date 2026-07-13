# PR7.7 Weight Chart Dynamic Y-Axis Validation

## Summary

Validated the Streamlit dashboard with before/after screenshots on desktop and mobile widths.

The updated weight chart derives its y-axis range from valid daily weight and 7-day average values only. Null, blank, zero, and invalid values are excluded.

## Expected Domains

| Scenario | Expected after domain | Result |
| --- | --- | --- |
| `range_83_9_84_2` | 83kg to 85kg | Passed |
| `range_83_84` | 82kg to 85kg | Passed |
| `range_76_83` | 75kg to 85kg | Passed |
| `one_valid` | Single valid weight with +/-1.5kg padding, rounded to 82kg to 86kg | Passed |
| `mixed_missing_zero` | Zero and missing values excluded | Passed |
| `no_valid` | Existing empty-state behavior preserved | Passed |

## Rendered Screenshots

| Scenario | Desktop Before | Desktop After | Mobile Before | Mobile After |
| --- | --- | --- | --- | --- |
| 83.9-84.2kg | [before](before_range_83_9_84_2_desktop.png) | [after](after_range_83_9_84_2_desktop.png) | [before](before_range_83_9_84_2_mobile.png) | [after](after_range_83_9_84_2_mobile.png) |
| 83.1-84.0kg | [before](before_range_83_84_desktop.png) | [after](after_range_83_84_desktop.png) | [before](before_range_83_84_mobile.png) | [after](after_range_83_84_mobile.png) |
| 76.8-83.7kg | [before](before_range_76_83_desktop.png) | [after](after_range_76_83_desktop.png) | [before](before_range_76_83_mobile.png) | [after](after_range_76_83_mobile.png) |
| One valid weight | [before](before_one_valid_desktop.png) | [after](after_one_valid_desktop.png) | [before](before_one_valid_mobile.png) | [after](after_one_valid_mobile.png) |
| Mixed missing / zero | [before](before_mixed_missing_zero_desktop.png) | [after](after_mixed_missing_zero_desktop.png) | [before](before_mixed_missing_zero_mobile.png) | [after](after_mixed_missing_zero_mobile.png) |
| No valid weights | [before](before_no_valid_desktop.png) | [after](after_no_valid_desktop.png) | [before](before_no_valid_mobile.png) | [after](after_no_valid_mobile.png) |

## Notes

- Streamlit rendered without exceptions in all validation scenarios.
- `records.csv` was not modified.
- No CSV, JSON, Body Score, or historical data behavior was changed.
