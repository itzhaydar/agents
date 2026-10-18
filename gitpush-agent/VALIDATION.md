# Validation record

Development host: Linux, Python 3.12.14, Git 2.52.0. Validation used temporary repositories and local bare remotes; no test commits were pushed to GitHub or other personal repositories.

- 58 automated tests passed with `DISPLAY=:97 GITPUSH_DATA_DIR=/tmp/gitpush-final-tests .venv/bin/python -m unittest discover -s tests -v` on the virtual X display. Without a display, the optional GUI test is skipped.
- Installed pinned application dependencies and ran `pip check`: no broken requirements.
- Imported the native Vosk recognizer successfully.
- GUI integration test on the virtual display: submitted an instruction, rendered the file/message preview, confirmed, performed a real commit/push to a local bare remote, checked remote SHA equality and success response. Audio and terminal-viewer interfaces were mocked in this automated GUI test.
- Separate Tkinter smoke check on an Xorg dummy display: built all four tabs, submitted a manual unknown-project instruction, displayed its response, closed cleanly.
- Diagnostics correctly report missing Linux PortAudio/microphone capability and Windows-only SAPI.
- Official model download attempted with verified HTTPS; this cloud's egress proxy returned HTTP 403 for `alphacephei.com`. An actual model and acoustic recognition could not be validated here. The application supports manual extracted-model selection and an HTTPS downloader; no verification was bypassed.

Remaining: Windows microphone/acoustic recognition, offline SAPI, default/alternative wake reliability, startup/activation/single-instance native handles, visible Windows terminal, packaged executable and 4 GB hardware performance. See the README acceptance checklist. Application code is implemented, but the complete Windows acceptance workflow has not been certified by these Linux checks.

## Female voice update

- Automatic preference now selects an installed female English SAPI voice; the UI allows an explicit installed-voice selection. New configurations default to rate -1; existing rates remain intact.
- Voice metadata, preferences, fallback behavior, persisted settings, and the speech worker's selection/plain-text SAPI invocation are tested with mocked Windows COM interfaces. These tests cannot assess audible naturalness.
- Current headless suite: 67 tests discovered, 66 passed, one optional GUI test skipped because no display is active.
- Audible quality and the installed voice list still require validation on Windows.

## Setup feedback update

- Replaced the clipped setup footer with a visible, scrollable results panel beside the five action buttons. Added immediate action feedback, busy indicators, download errors and a shared status notice across tabs. Voice settings scroll on short windows.
- 68 tests passed on the Linux virtual display, including the real-Git GUI test and a setup test at 1280×680 and 740×600. The setup test checks visible buttons/results, asynchronous device-check completion, download failure feedback, speech-error display and project/settings navigation.
- Windows audio and packaged executable checks remain user-side acceptance work. Rebuilding the executable is required to incorporate source updates.

## Automatic folders, observed setup progress and installer recipe

- 83 tests passed with `DISPLAY=:97 GITPUSH_DATA_DIR=/tmp/gitpush-discovery-tests .venv/bin/python -m unittest discover -s tests` on the Linux virtual desktop.
- The GUI integration test now discovers an unregistered Git folder, accepts an instruction by folder name, previews it, commits, pushes to a local bare remote and checks the remote hash.
- Added discovery tests for duplicate names, cache/submodule boundaries, linked-worktree markers, search limits, inaccessible paths, symlink avoidance, spoken names and saved-setting precedence. Added spoken-number disambiguation tests.
- Added model tests for actual byte counts, model reuse, incomplete responses, archive traversal prevention and TLS context use. Mock archive content is test-only, not a production speech model. Added a test verifying that diagnostics open an actual capture-stream interface.
- Reviewed the revised dark UI on a virtual display; existing setup-layout tests exercise small windows. Download percentages are derived from bytes, playback completion from SAPI, capture status from the microphone worker and scan status from discovered folders.
- Python 3.14 now selects pywin32 312; older supported Python versions retain 308. Dependency integrity check passed in the Linux Python 3.12 environment.
- Added `build-windows.ps1` and an Inno Setup per-user installer recipe. No Windows installer or executable was built/tested here. UAC elevation is deliberately unnecessary; Windows microphone privacy remains user-controlled.
- Acoustic recognition, Windows privacy/device behavior, SAPI audible quality, sign-in activation, installation/uninstallation and low-end hardware performance still require Windows acceptance testing. The previously observed official-model egress restriction remains; HTTPS verification has not been bypassed.
