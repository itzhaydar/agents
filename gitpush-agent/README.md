# GitPush Agent

A lightweight Windows desktop assistant: say the wake phrase, name a Git folder, describe your changes, review the preview, and confirm the push. Speech recognition and female-voice speech output run locally. No cloud AI account, API key, Node runtime, GPU, Electron or database is required.

The application is implemented and tested on Linux with real temporary Git repositories, local bare remotes, and a virtual desktop. Windows audio, installer execution, sign-in behavior, packaged executables and performance on a 4 GB PC must still be checked on Windows. Dependency resolution on Python 3.14 was reported successful by the user; it does not establish full Windows compatibility.

## Install or run

Requirements: Windows 10/11, 64-bit Python 3.11–3.14 with Tkinter (for source/build use), Git for Windows on PATH, a microphone and speakers/headphones. Python 3.14 uses pywin32 312; earlier supported Python versions use 308. The small English speech model is about 40 MB to download and needs additional disk space after extraction.

In PowerShell inside `gitpush-agent`:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

You can also run the packaged `dist\GitPushAgent\GitPushAgent.exe`. Keep the entire `dist\GitPushAgent` folder together. Files in `build` are intermediate build outputs.

### The five setup steps

The **Get started** page has a live progress table and a scrollable results panel. Status remains visible above every tab.

1. **Run device checks.** Checks Python, Git and model availability, inspects Windows microphone privacy guidance, and actually opens/closes a capture stream to test device access. No raw audio is stored. Missing requirements appear in the results; a format/device listing alone is not treated as microphone access.
2. **Prepare offline voice.** Automatically reuses a valid configured/default model or downloads the official small English model. Download progress uses actual received bytes and Content-Length when available, otherwise received MB. Extraction is reported separately. The model path is saved automatically. This model **is necessary** for offline wake/command recognition; it is not an optional AI service. Normal HTTPS verification, archive traversal protection and size limits remain enabled. No upstream checksum is pinned. You can alternatively select an already extracted model directory containing `am/final.mdl` in Voice & startup.
3. **Speak voice test.** Plays a sentence through Windows SAPI. The progress table reports when SAPI finishes playback, or displays an error. “Played” does not prove your speakers were audible; confirm that you heard it.
4. **Find my Git folders.** Opens **Workspaces** and discovers repositories automatically. Individual project registration is optional. Add a containing workspace if your folders are elsewhere.
5. **Start wake listening.** Saves the voice/model settings and opens the microphone. The progress table changes when capture is active and again when the wake phrase is detected. Say **“Hey GitPush”**, followed by your instruction. Use Voice & startup to choose the microphone, female voice, rate, alternative wake phrase or sign-in startup.

Device checks and downloads run off the UI thread. Their buttons disable while work is active. Discovery reports folders checked and repositories found, not an invented percentage. Each step reflects observed results rather than a timer.

### Microphone permissions

Click **Windows microphone settings** in Get started. In Windows Settings → Privacy (or Privacy & security) → Microphone, enable:

- Microphone access.
- **Allow desktop apps to access your microphone**.

Ordinary Win32 desktop apps may **not** display an individual microphone permission popup. The app cannot enable these permissions for you. A registry observation is guidance; the actual capture-open result tests whether access works. School/company policy can block access even when another setting looks enabled. Choose a different sounddevice device index in Voice & startup if the default is wrong. The active microphone indicator remains visible in the app.

Speech recognition and synthesis work offline after setup. Pushing to GitHub requires internet. Audio is neither saved nor transmitted externally.

## Use folders without registering projects

At startup, GitPush scans existing Documents, Desktop, Projects, source, repos and Developer folders in your home, plus OneDrive Documents/Desktop when available. **Workspaces → Add workspace folder** lets you add a different parent, such as `D:\Work`. All Git repository roots found there become available by their folder names. No per-project registration is needed.

For example:

- `D:\Work\portfolio` → “Push portfolio. Fixed the mobile layout.”
- `D:\Work\flight-app` → “Push flight app. Added flight controls.”
- `D:\Work\myPortfolio` → “Push my portfolio. Updated the CV.”

The search is read-only, bounded to 20,000 directories and six levels per root. It skips dependency/build caches, hidden directories, symlinks and junctions, and stops descending when it finds a repository. Linked-worktree `.git` files are recognized. Warnings and truncated/inaccessible paths are reported in Activity. Add a deeper/narrower workspace if something was not found. **Refresh folders** updates the index after adding/moving projects. **Use common folders** resets the custom search list.

If two folders share a name, the agent reads numbered options **with their paths**. Say **“option one”**, **“option two”**, or the unique project name. It never silently chooses between duplicates, guesses unrelated directories, or creates a repository. “This folder” alone is insufficient: the app cannot see which folder your editor is using. Name the folder in your command.

Optional saved projects remain available below discovery results for custom spoken aliases and exclusion patterns. Registration can also point to an exact root outside the search locations. Saved settings take precedence over discovered entries at the same path. Project lists/voice settings have scrollbars for small screens.

Every operation still validates the exact repository root, branch and upstream and asks for confirmation of the selected files/message. Discovery does not authorize a push on its own.

## Speak and push

1. Say **“Hey GitPush.”** Wait for **“I'm listening.”**
2. Say **“We updated portfolio and fixed the mobile CV layout. Push the changes.”**
3. Review the Activity preview: actual repository path, branch, upstream, selected files, exclusions and proposed message **“Fix mobile CV layout.”**
4. Say **“Confirm push”** or **“Cancel.”**

Other instructions:

- “Push Marshout. Added new flight controls.”
- “Commit and push portfolio. Fixed responsive navigation.”
- “Change message to Fix the mobile navigation.” — prepares a fresh confirmation.
- “What's the status?”
- “Stop listening.” — closes capture; resume with the visible button.
- “Close GitPush.” — exits when no Git/validation operation is running.

The parser is deterministic and offline, not a general conversation model. It handles named folders/aliases and common change verbs: fixed, added, updated, improved, removed, changed, refactored, documented and resolved. If the description is missing, the agent asks for it instead of inventing one.

Confirmation expires after 30 seconds of response time, excluding the app's own speech. Silence/uncertain wording never approves an operation. A changed repository requires a fresh preview. Recognition pauses during speech, and speech is serialized. Headphones reduce acoustic echo.

Wake listening uses restricted-vocabulary Vosk phrase recognition, **not a dedicated wake-word engine**. Some models omit “git”; the idle grammar uses the close pronunciation “get” when necessary. Configure an alternative such as “hey push” and test it in your room if false activations occur. Only command mode performs unrestricted recognition. One resident listener shares one model with the UI.

Activity also provides manual instructions, Confirm and Cancel as an accessible fallback.

## Female offline voice

Automatic selection prefers an installed female English SAPI voice, such as Microsoft Zira. Voice & startup lists the voices available to SAPI; save your choice before testing. New configurations use a slightly slower rate (-1); existing rates are preserved.

If no female voice exists, the app warns and uses the Windows default. If a saved voice disappears, it warns and tries the female preference. Install an offline **SAPI 5** voice and restart to refresh the list. Not all Narrator/OneCore or Windows “natural” voices are exposed to SAPI. Audible quality depends on the installed engine; no neural/cloud voice or measured naturalness is claimed.

## Git prerequisites and safeguards

Configure Git identity, authentication, remote and the branch's upstream outside the app. An existing commit and attached branch are required. Use your actual branch name, not an assumed main/master. For example, this is an explicit **manual setup** step, not an automatic app action:

```powershell
git config user.name "Your Name"
git config user.email "your-email@example.com"
git branch --set-upstream-to=origin/YOUR_BRANCH YOUR_BRANCH
```

Authenticate using Git Credential Manager or SSH in your usual Git client first. GitPush disables interactive credential prompts and uses timeouts.

- NUL-delimited inspection and literal pathspecs handle modified/added/deleted/renamed/staged/untracked/ignored paths, including unusual filenames.
- Suspicious file names/content, private-key/token patterns, symlinks, configured exclusions and files larger than 10 MiB are excluded. Suspicious/excluded files already staged block the operation for manual review.
- Preview builds an approved tree using a temporary index, preserving the real index. Content/refs/local-config fingerprints bind confirmation to the actual state.
- Staging is selective. The real staged tree must match the approved tree. Hook modifications to the commit tree stop the push and retain the commit.
- Selection is **whole-file**. For a partially staged selected file, confirmation approves its current full contents, not just prior staged hunks. Use Git manually for hunk-level work.
- A visible Windows Terminal (or native console fallback) displays actual command results. The worker runs Git once and independently captures exit codes. Output arrives after each command completes. Closing the viewer does not cancel Git.
- Push targets only HEAD at the configured upstream destination, with no force or extra tags. Success requires successful push exit status and matching advertised remote SHA from `git ls-remote`.
- A clean tree with unpushed commits uses the same confirmation for push-only work. No changes/no pending commits means no empty commit.
- Failed pushes retain successful local commits. Retry after fixing the reported cause. Failed staging/hooks can leave the index staged for inspection; no reset is performed.
- Conflicts, interrupted operations, submodules, mirror remotes, missing/unborn/detached branches, local upstreams, and differing/multiple fetch/push URLs are blocked for manual review.

The app does not initialize, change remotes, pull, rebase, force-push, resolve conflicts or discard files. Local tracking refs may be stale; Git rejects incompatible remote updates. If remote verification fails after a successful push, the result is conservatively reported as uncertain/failure with details. Existing historical commits are not scanned for secrets. Avoid editing/staging concurrently in other tools: external processes cannot be made transactionally atomic by this app.

## Portable app versus installer

Opening a portable `.exe` starts the app; it is **not an installation wizard**. Windows UAC (“allow this app to make changes”) requests elevation, not proof that an app was installed. This app does not need administrator privileges or UAC for normal use.

An optional Inno Setup installer recipe is included. It installs for the current user under `%LOCALAPPDATA%\Programs\GitPushAgent`, adds a Start-menu shortcut, offers a desktop shortcut and optional launch, and provides uninstall support. It intentionally uses no elevation. Windows SmartScreen may separately warn about an unsigned downloaded executable; the installer does not bypass that protection.

Build on Windows from this folder, with all app instances closed:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pyinstaller
powershell -NoProfile -File .\build-windows.ps1
```

The script tests first, then builds `dist\GitPushAgent\GitPushAgent.exe` using PyInstaller. The model remains in per-user data, not bundled in the executable. Git is a separate prerequisite.

If PowerShell policy blocks scripts, follow your administrator's approved process or build directly without a script:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --windowed --name GitPushAgent --collect-all vosk --collect-all sounddevice --hidden-import win32com.client --hidden-import pythoncom --hidden-import pywintypes main.py
```

To also create a setup wizard, install **Inno Setup 6** from <https://jrsoftware.org/isinfo.php>, then run:

```powershell
powershell -NoProfile -File .\build-windows.ps1 -Installer
```

Result: `dist\installer\GitPushAgent-Setup.exe`. The installer recipe and PowerShell build cannot be executed in the Linux development host and are not claimed tested on Windows. Uninstall preserves configuration/model/log data but removes the app-owned optional startup entry.

Enable **Start GitPush Agent when Windows starts** in Voice & startup to create the current-user Run entry. It starts a single minimized, observable instance in the interactive user session. Disable and save to remove startup. Duplicate launches activate the current instance via a session mutex/event. Closing the app exits its listener; live processes do not survive sign-out. Re-save startup after moving the installation.

## Updates and tests

Inside the cloned folder:

```powershell
git pull
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py
```

Source changes do not update an old `.exe`; rebuild using the script above. Check source behavior before packaging.

Tests use temporary repositories/local bare remotes only, never your GitHub projects. They cover discovery bounds/aliases/duplicates, spoken selection, safety validation, file selection/races, real commit/push success and failure, model archive/byte progress, microphone capture-opening logic, voice selection, timeouts/cancellation and GUI setup feedback. Audio/COM/download fixtures are mocked only in tests. GUI tests require a display; Unix hook fixtures are skipped on Windows. Native audio, sign-in, installer and 4 GB hardware performance remain Windows acceptance checks.

Linux development: create `.venv`, install requirements, run unittest. PortAudio is a separate Linux system prerequisite for sounddevice; Tkinter needs a display. Use `GITPUSH_DATA_DIR=/tmp/gitpush-dev .venv/bin/python main.py --diagnose` for isolated diagnostics. Linux is not the supported speech platform.

## Troubleshooting and data

- **No microphone:** open the Windows privacy shortcut; enable device/desktop-app access, select the correct device index, and rerun checks. Device-busy/missing-model errors are shown in Setup results and Activity.
- **Voice setup download fails:** allow `alphacephei.com` or select an extracted official model manually. Do not disable TLS checks.
- **Folder not found:** add its containing workspace and Refresh folders. Check Activity for inaccessible/depth/size-limit warnings. Use the folder's spoken name, not “this folder.”
- **Authentication/upstream/push rejection:** correct it in your Git client. Local commits are retained; request a push-only retry when ready.
- **Secret/excluded staged file:** inspect and unstage it manually before requesting a new preview.
- **Config cannot load:** back it up and correct/move aside the JSON; invalid user config is not overwritten.

Settings live at `%LOCALAPPDATA%\GitPushAgent\config.json`, alongside up to four ~1 MB rotating logs and ten terminal transcripts. `GITPUSH_DATA_DIR` overrides this for isolated tests. Logs include project/branch/message/commands/hash/results and redact common URL/token/password forms. Detection/redaction is heuristic and cannot guarantee every credential or arbitrary custom-hook output is caught. Keep credentials in Git's credential storage, not messages, filenames or configuration. No raw audio recordings are retained.
