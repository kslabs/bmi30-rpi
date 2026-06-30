# Codex Project Instructions

## BMI30 default edit target

By default, BMI30 work means the websplit system, not the legacy standalone GUI file.

Before editing any BMI30 runtime, GUI, portal, or engine code, resolve the active websplit files first:

1. If `BMI30_CORE_PATH`, `BMI30_GUI_PATH`, `BMI30_PORTAL_PATH`, or `BMI30_ENGINE_SOURCE` are set in the environment, use those files.
2. Else, if `host/bmi30_split_active_version.env` exists, read `BMI30_CORE_PATH`, `BMI30_GUI_PATH`, and `BMI30_PORTAL_PATH` from it.
3. For the engine loaded by the split core, use `BMI30_ENGINE_SOURCE` if set; otherwise use the `DEFAULT_ENGINE_FILE` declared by the active core file.

Current intended websplit files:

- Core service: `host/BMI30.001.py.2026-06-26-1015`
- Web GUI: `host/BMI30.GUI.001.py`
- Portal: `hotspot_info_server.py`
- Default engine: `host/BMI30.200.py.2026-06-25-websplit-reset-fix`

Live portal deployment reminder:

- Edit the portal source in `hotspot_info_server.py`.
- The running portal service uses the installed copy `/usr/local/bin/bmi30-hotspot-info-server.py`.
- After portal source changes, install the updated source to `/usr/local/bin/bmi30-hotspot-info-server.py` and restart `bmi30-hotspot-info.service`; otherwise the browser can still show the old portal UI.

Do not edit legacy BMI30 monolith/version files via `BMI30_APP_PATH`, `host/bmi30_active_version.env`, `launch.sh`, or `switch_version.sh` unless the user explicitly asks for the legacy system or that file is the engine selected by the active websplit core.

## BMI30 active version

This section is only for legacy standalone BMI30 GUI work when explicitly requested.

Before editing any BMI30 GUI application code, resolve the active application file. Do not assume `host/BMI30.200.py` is the current target.

Resolution order:

1. If `BMI30_APP_PATH` is set in the environment, use that file.
2. Else, if `host/bmi30_active_version.env` exists, read `BMI30_APP_PATH` from it.
3. Else, use the default from `launch.sh`.
4. Else, use option 1 from `switch_version.sh`, marked as the main working version for edits.

Current intended working file:

`host/BMI30.200.py.2026-05-24-work`

Only edit another BMI30 version file when the user explicitly names it or when it is selected by the active-version resolution above.
