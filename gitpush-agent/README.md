# GitPush Agent

A lightweight Windows desktop assistant for committing and pushing registered Git projects using offline voice commands. Python, Tkinter, a small Vosk model, sounddevice, and Windows SAPI handle the desktop and speech. No cloud AI, API keys, Node runtime, Electron, database, or GPU is required.

**Implementation status:** the Python application and automated tests are implemented. Linux validation covers real Git operations with temporary local remotes and a Tkinter smoke test. Windows microphone recognition, SAPI, startup, native console behavior, packaged executables, and performance on a 4 GB PC still require the acceptance checks below. Do not treat this as Windows-certified software yet.

## Requirements

- Windows 10 or 11; Python 3.11–3.13 with Tkinter (Python 3.12 recommended).
- Git for Windows on PATH, configured identity, existing repository and upstream.
- Microphone, desktop microphone permission, speakers or preferably headphones.
- Approximately 40 MB download for the small English Vosk model, plus installed Python dependencies and extracted model storage.
- Designed for 4 GB RAM, without measured hardware performance claims.

Recognition, wake matching, parsing and speech synthesis run locally. Internet is used for dependency/model downloads and Git remote operations. No audio is saved or uploaded. The implementation supplies an explicit local model path to Vosk, avoiding Vosk's automatic online model discovery.

## Install and run

Open PowerShell in this `gitpush-agent` folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Python's Windows installer includes Tcl/Tk by default. If Git is missing, install it from <https://git-scm.com/download/win> and restart the application. Node.js is not used.

The **First-run setup** tab guides device checks, model installation, a spoken output test, project registration, and wake testing. Each action updates the visible **Setup results** panel; device checks and model downloads show a progress indicator. A status message remains visible above every tab. Voice settings have a scrollbar for smaller screens. Initial setup can use mouse/keyboard. Use **Activity** for normal operation.

1. Run device checks. If needed, open Windows Settings → Privacy & security (Privacy on Windows 10) → Microphone. Enable microphone access for desktop apps.
2. Download the official `vosk-model-small-en-us-0.15` English model using the setup button, or download and extract it from <https://alphacephei.com/vosk/models>. Select the extracted model directory containing `am/final.mdl` in **Voice & startup**. The download uses normal HTTPS certificate verification and checks archive paths and size limits; the upstream distribution does not supply a pinned checksum here.
3. Test offline Windows speech and confirm you can hear the response. Automatic voice selection prefers an installed female English SAPI voice (for example Microsoft Zira). The voice dropdown lists the SAPI voices available on your PC; choose one and save before testing. New configurations use a slightly slower speaking rate (-1) with the selected voice's native prosody for a more relaxed delivery. Existing speed settings are preserved. Choose volume, speed, and optionally a sounddevice microphone index. A blank index uses the default device.
4. Register a project as described below.
5. Save settings to start/restart the listener. Say **“Hey GitPush”**, then check that the window activates, displays your instruction, and speaks **“I'm listening.”**
6. Test a project instruction and say **“cancel”**. Verify the proposed files and message before performing your first real operation.
7. Optionally enable Windows sign-in startup.

For diagnostics without launching the desktop:

```powershell
.\.venv\Scripts\python.exe main.py --diagnose
```

## Register projects

In **Projects**, choose **New**, enter a unique display name, choose the absolute **Git repository root**, and optionally enter comma-separated spoken aliases and exclusion patterns. Click **Save / validate**. Select a registered row to edit it, or remove it with **Remove selected**.

For example, a project called `Portfolio` can have aliases `my portfolio, portfolio project`. Paths are chosen on your machine; no example paths are assumed to exist. If a selected folder is inside a larger repository, registration stops and reports the actual root. Choose that root explicitly if you want the agent to operate on the entire repository.

Exclusion examples: `build/*, exports/*, notes.txt`. Patterns match repository-relative paths using Python fnmatch. Configure exclusions during setup; routine push operations require no typing. The preview marks ignored, excluded, selected, and previously staged files separately. Large lists remain scrollable in Activity.

A repository must have an existing commit, an attached branch, a remote and an upstream. Set up identity/authentication/upstream separately in Git or your editor. Registration never initializes repositories, changes remotes, or invents an upstream. A typical **manual, explicit setup** for an already published branch is:

```powershell
git config user.name "Your Name"
git config user.email "your-email@example.com"
git branch --set-upstream-to=origin/YOUR_BRANCH YOUR_BRANCH
```

Use your actual branch; the app assumes neither `main` nor `master`. Fetch the appropriate branch manually first if it is absent locally. Git Credential Manager or SSH authentication must already work. Authenticate interactively outside the agent; its Git subprocesses disable interactive credential prompts and have timeouts.

Repositories with submodules, detached/unborn HEAD, merge conflicts, interrupted operations, mirror remotes, local-only upstreams, or different/multiple fetch and push URLs are deliberately blocked for manual review. The app does not pull, rebase, force-push, reset, or resolve conflicts.

## Voice commands

After **“Hey GitPush”**, speak an instruction, for example:

- “We updated the portfolio folder and fixed the mobile CV layout. Push the changes.”
- “Push Marshout. Added new flight controls.”
- “Push changes in portfolio. Added a contact section.”
- “Commit and push portfolio. Fixed responsive navigation.”
- “Push my portfolio project. Updated the CV.”

A deterministic parser finds registered names/aliases and recognizes common change verbs, including fixed, added, updated, improved, removed, changed, refactored, documented and resolved. It proposes a short message from your description. It does not invent a description or accept arbitrary conversational language.

If two registered names or aliases match, the agent reads the project choices. Speak the **unique display name** of your choice. If a description is missing, say something like **“Fixed responsive navigation.”**

Before execution, the agent reads the selected-file count, excluded-file count, project, and commit message. The exact branch, upstream, file list, exclusions and previous staging appear in Activity. You can say:

- **“Change message to Fix the mobile navigation.”** — creates a fresh preview and asks again.
- **“Confirm push.”** — executes the pending approved plan.
- **“Cancel.”** — discards the pending plan.
- **“What's the status?”** — reads the current application state.
- **“Stop listening.”** — closes microphone capture. Resume with the visible button.
- **“Close GitPush.”** — exits when no Git/validation worker is running.

Confirmation expires after 30 seconds of response time, excluding the agent's own speech. Silence never authorizes a push. Exact confirmation is required; “maybe confirm push later” does not approve anything. Speech is serialized, and recognition pauses while SAPI speaks. Use headphones to reduce room echo.

Wake listening uses Vosk's restricted vocabulary and exact whole-phrase matching, **not a dedicated wake-word engine**. Command mode uses unrestricted recognition only after activation. Some English models omit “git”; the idle grammar uses the close pronunciation “get” when required. Test false activations in your room. Configure an alternative supported phrase such as **“hey push”** if needed. There are no invented recognition-accuracy claims or calibrated confidence thresholds.

**Wake / Resume listening**, the instruction field, **Confirm push**, and **Cancel** provide an accessible manual fallback. Voice remains the primary workflow.

### Female voice and sound quality

The automatic voice preference applies to existing configurations as well as new installations. If a saved voice has been removed, the app warns and tries an available female voice. If no female SAPI voice is installed, it clearly warns and keeps the Windows default instead of claiming that a female voice is active.

Install an offline female Windows speech voice exposed to **SAPI 5**, restart GitPush to refresh its list, and choose it in **Voice & startup**. Not every Windows Narrator/OneCore or “natural” voice is exposed to SAPI; a voice appearing in Windows settings may not appear in this dropdown. Sound quality depends on the installed engine. This change does not add neural/cloud speech or promise studio-quality audio. Try the voice test and adjust the speaking speed to your preference.

## What Git execution does

1. Validate the exact root, branch, upstream and repository state.
2. Inspect tracked/staged/untracked changes and ignored paths with NUL-delimited Git output. Renames, deletions, spaces, Unicode and unusual path characters are handled as literal paths.
3. Exclude suspicious names, private-key/token patterns, symlinks, configured exclusions, and files larger than 10 MiB. A suspicious/excluded file already staged blocks execution; review and unstage it manually.
4. Build an expected commit tree in a **temporary index**, leaving the user's real index unchanged during preview. Fingerprint content, index changes, refs and local configuration.
5. Present the exact selection and ask for confirmation. Any subsequent detected repository change requires a new preview.
6. Open a native Windows console viewer. A background worker runs Git once and captures actual output and exit statuses. The viewer tails a sanitized transcript; it never repeats Git commands.
7. Stage only the approved literal paths. Compare the resulting tree with the approved tree, check the staged diff, and commit using an argument list with `shell=False`.
8. If a commit hook changes the approved tree, retain the local commit and stop before pushing.
9. Push **only HEAD to the current branch's configured upstream destination**, explicitly overriding ambiguous push defaults. Never force or push additional tags.
10. Require a successful push exit code and verify the destination branch's advertised commit via `git ls-remote` before announcing success.

Windows Terminal is used when available; a native console fallback works without Windows Terminal and requires no simulated keypresses. Output is displayed after each command completes; the GUI remains responsive during the command. The terminal remains open for inspection afterward. Closing it does not cancel Git. Close it with its window button, or Enter if convenient; the application never waits for that interaction.

Existing staged files are listed and included. **Selection is whole-file:** if a file is partially staged, confirming approves all current changes in that selected file, not just its previously staged hunks. Use Git manually for hunk selection. Staging or hook failures can leave the index staged for inspection; the app never resets it automatically.

If the tree is clean but commits are ahead, the same confirmation enables a push-only operation. No empty commit is created. If there is no selected work and no unpushed commit, the agent says **“No changes to push.”** A failed push leaves any successful local commit intact; a later push-only request can retry it. Existing historical commits are not scanned for secrets by this tool.

Remote tracking information may be stale because inspection does not fetch automatically. A later remote divergence is handled by Git's push rejection; the agent never tries to reconcile it. A successful push followed by failed remote verification is conservatively reported as failure/uncertain verification, with details for inspection.

## Windows startup and listener

Enable **Start GitPush Agent when Windows starts** and save. This writes only the current user's `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\GitPushAgent` value; no administrator rights or Windows service is needed. Disable the setting and save to remove it. You can also remove the entry through Windows startup settings/Registry Editor if the install was moved.

The entry runs `main.py --background` with the installed virtual environment's Python interpreter, or runs the packaged executable. Keep the installation at that location; re-save startup after moving it.

A single resident process contains the background listener and desktop UI, sharing **one Vosk model**. At sign-in the window starts minimized, with a visible taskbar presence and microphone status available in its window. It keeps listening while minimized. Wake activation restores the existing window. A per-session Windows mutex prevents duplicate listeners/windows; launching again signals the running instance to show itself. Closing the application exits the listener, and **Stop listening** releases capture without exiting. Live processes do not persist across sign-outs or machines.

## Data, logs and safety

Configuration is stored in `%LOCALAPPDATA%\GitPushAgent\config.json`. Rotating logs live alongside it (`agent.log`, up to four ~1 MB files). Up to ten terminal transcripts are retained. `GITPUSH_DATA_DIR` can override the data directory for testing or a portable installation. Never place credential values in configuration.

Logs record project, branch, message, operations, commit hash and result. Common URL credentials and token/password formats are redacted. Secret detection and output redaction are heuristic; they cannot guarantee detection of every secret or arbitrary custom-hook output. Do not put credentials into commit messages, filenames or command output. Review the selected files, existing local commits and trusted hooks. Keep Git authentication in Git's supported credential storage.

No force-push, initialization, file discard, automatic reset, or remote rewrite is performed. A timeout, failed hook or concurrent edit preserves files and completed commits for review. Avoid editing/staging with another Git tool during an approved operation: state and tree comparisons catch common races, but separate processes cannot be made transactionally atomic by this application.

## Tests

From this directory:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests create temporary repositories and **local bare remotes only**. They do not push to GitHub or operate on your registered repositories. Speech/microphone interfaces are mocked only in tests. Production uses Vosk, sounddevice, SAPI and real Git subprocesses.

The optional Tkinter integration test requires a display and exercises manual instruction → preview → confirmation → real local-remote push; without a display it is skipped. The suite covers parsing, aliases/ambiguity, wake matching and vocabulary fallback, transcription events, bounded audio queues, config round trips, exact/timed confirmation, cancellation, duplicate prevention, invalid repositories, file exclusions, staged/ignored content, rename/delete paths, content races, commit-hook failure/modification, rejected pushes, push-only work, and verified successful pushes. Unix shell-hook fixtures are skipped on Windows; exercise Windows hooks separately when relevant.

Linux development commands:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
GITPUSH_DATA_DIR=/tmp/gitpush-dev .venv/bin/python main.py --diagnose
```

Linux audio requires the system PortAudio library (`libportaudio2` on Debian/Ubuntu), a microphone, and an X display for Tkinter. Linux is a development/test host, not the supported speech platform.

## Package a Windows executable

Build **on Windows**, from the same virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onedir --windowed --name GitPushAgent --collect-all vosk --collect-all sounddevice --hidden-import win32com.client --hidden-import pythoncom --hidden-import pywintypes main.py
.\dist\GitPushAgent\GitPushAgent.exe
```

`onedir` avoids unpacking a large runtime/model on every startup. Models remain in the per-user data directory selected by setup, so they are not bundled into the executable. On another PC, use the first-run download or select a copied extracted model. Git for Windows is a separate prerequisite. The application opens a console explicitly for its transcript viewer even in a windowed package.

No Windows executable was built or tested in the Linux development environment. Check PyInstaller dependency collection, SAPI and microphone access on the destination Windows installation before distributing a build.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Git not found | Install Git for Windows, restart the app, run device checks. |
| Missing upstream/remote/identity | Configure and verify them manually in the intended repository. |
| Authentication fails or times out | Authenticate using Git Credential Manager/SSH outside the agent. Confirm remote access in your usual Git client. |
| Push rejected | Inspect local/remote history and reconcile manually. Local commits remain intact. |
| No speech recognition | Check microphone permissions/device index, extracted model directory and dependency installation. |
| Wake words absent from model | Set an alternative phrase in Voice & startup, save, and test again. |
| Recognition hears the speakers | Use headphones, lower voice volume, and test the room's acoustics. |
| Model download fails | Allow `alphacephei.com` through your network policy, or download/extract the official model manually and select it. Do not disable TLS verification. |
| Secret or excluded file already staged | Review/unstage that file manually, then request a new preview. |
| Repository changed after confirmation | Review current files and issue the instruction again. |
| Commit succeeded but push failed | Fix connectivity/authentication/rejection, then request a push-only retry. |
| Speech output unavailable | Check installed offline Windows voices and pywin32 in the same Python environment. Use manual controls meanwhile. |
| Multiple launch attempts | The running instance is activated; use its taskbar entry if Windows foreground restrictions keep it behind another app. |
| Invalid config file | Back it up and correct the JSON or move it aside to run setup again; the app does not overwrite invalid user configuration. |

## Windows acceptance checklist

Before relying on this for daily work, use a disposable project and remote:

- Complete setup; test default/alternate wake phrases, transcripts, SAPI volume/rate and speaker echo.
- Sign out/in with startup enabled; verify exactly one minimized listener, a visible microphone indicator, wake restoration and duplicate-launch behavior. Disable startup and verify it stays disabled.
- Register a repository; speak the portfolio example; verify the proposed message and every file category. Cancel and time out once before testing confirmation.
- Confirm a change; inspect the native terminal, actual commit and remote branch, and success speech.
- Test network loss/authentication rejection, missing upstream, conflicting state, hook failure, staged exclusions, push-only retry, stop/resume and close.
- Repeat from a PyInstaller build if using it.
- Measure idle/active CPU and memory in Task Manager while VS Code and usual applications run on the actual 4 GB PC. These measurements and end-to-end speech reliability remain unverified.
