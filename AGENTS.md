# Codex Project Instructions

## BMI30 active version

Before editing any BMI30 GUI application code, resolve the active application file. Do not assume `host/BMI30.200.py` is the current target.

Resolution order:

1. If `BMI30_APP_PATH` is set in the environment, use that file.
2. Else, if `host/bmi30_active_version.env` exists, read `BMI30_APP_PATH` from it.
3. Else, use the default from `launch.sh`.
4. Else, use option 1 from `switch_version.sh`, marked as the main working version for edits.

Current intended working file:

`host/BMI30.200.py.2026-05-24-work`

Only edit another BMI30 version file when the user explicitly names it or when it is selected by the active-version resolution above.
