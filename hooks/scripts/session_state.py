#!/usr/bin/env python3
"""Where the hooks keep their per-session scratch state, and how they open it.

State lives beside the session transcript, at `<transcript_path>.ioncache-<name>`,
because the authorization judge has to find it and can only build a path by
copying one out of its own hook input. The judge is an agent hook with Read,
Grep and Glob and nothing else: it cannot run `id -u`, read $TMPDIR, or list
anything to guess with.

Two earlier locations failed exactly there, both found only by live testing:

- A per-user temp directory. The judge had no way to compute the path, so
  every authorized commit was denied as "file missing".
- The session scratchpad. `scratchpad_dir` is present in interactive sessions
  but absent in headless ones (`claude -p`, scheduled agents), from every hook
  event, so every commit in those sessions was denied. The judge also
  hallucinated a scratchpad path when the field was missing.

`transcript_path` was observed present on both UserPromptSubmit and PreToolUse,
headless and interactive, and its directory already exists when the first
prompt of a brand-new session fires. It sits in the user's home directory, not
the shared /tmp, owned by the user and not writable by anyone else.

Codex loads these same hooks with its own input shape, so there is still a
fallback: `/tmp/.ioncache-<uid>/`, on Linux and macOS alike. /tmp itself is
used without any checks, because it is the place meant for exactly this; only
our own subdirectory is checked, to be sure it really is ours. The judge
never reads the fallback, so nothing written there can authorize a commit; the
pending-question hooks, which are all command hooks, work in either location.

Everything in the fallback is temporary and is gone after a reboot. Nothing may
depend on it persisting: a missing prompts list reads as empty (the judge then
denies), and a missing pending-question flag reads as "no question pending".

Nothing in this module raises. A hook that throws exits 1, and Claude Code
treats exit 1 as a non-blocking error and proceeds, so a raise here would
silently switch a guard off. Callers get None instead and decide explicitly.
"""
import os
import pathlib
import stat

PROMPTS = "prompts"
PENDING_QUESTION = "pending-question"

# Appended to the transcript path. The result ends in neither `.jsonl` nor
# anything else Claude Code reads, so it cannot be mistaken for a session.
TRANSCRIPT_SUFFIX = ".ioncache-"

# Literal /tmp rather than tempfile.gettempdir(), which on macOS is a per-user
# /var/folders path. /tmp is the same well-known place on both systems.
TMP_DIR = pathlib.Path("/tmp") / f".ioncache-{os.getuid()}"

DIR_MODE = 0o700
FILE_MODE = 0o600

# O_NOFOLLOW so a symlink where the file should be is an error rather than a
# redirected write. O_TRUNC because every writer here replaces the whole file.
CREATE_FLAGS = os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW


def is_private_dir(path):
    """True if `path` is a real directory (not a symlink), owned by this user,
    that no group or other account can write into. Write access is what
    matters: files here are created 0600, so reading is already private, but a
    writable directory lets someone else plant a file before we do.
    """
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if not stat.S_ISDIR(info.st_mode):
        return False
    return info.st_uid == os.getuid() and not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)


def state_file(hook_input, name):
    """Path for one piece of per-session state, or None if nowhere safe exists.

    Resolves identically for every hook given the same input, which is the
    contract the authorization judge depends on: the capture hook writes where
    the judge will look, because both derive the path from `transcript_path`.
    """
    transcript = hook_input.get("transcript_path")
    if transcript:
        path = pathlib.Path(f"{transcript}{TRANSCRIPT_SUFFIX}{name}")
        # Checked, never created: that directory belongs to Claude Code, and it
        # already exists by the first prompt. If it does not, something is
        # unusual enough that falling back is the right call.
        if is_private_dir(path.parent):
            return path

    try:
        TMP_DIR.mkdir(mode=DIR_MODE, exist_ok=True)
    except OSError:
        return None  # /tmp itself unusable; callers treat None explicitly
    # /tmp itself is never vetted, it is the right place for temp files. Our
    # own subdirectory is: on a shared host another account could create
    # /tmp/.ioncache-<uid> first, as its own directory or a symlink to one, and
    # then plant or delete the pending-question flag inside it. If the entry is
    # not a real directory owned by this user, use nothing rather than theirs.
    if not is_private_dir(TMP_DIR):
        return None
    directory = TMP_DIR
    # A falsy id normalizes to one name for every caller. Writer and reader
    # once normalized differently, one writing `...-unknown` while the other
    # deleted `...-None`, so state silently outlived what cleared it.
    return directory / f"{name}-{hook_input.get('session_id') or 'unknown'}"


def write_private(path, text):
    """Writes `text` to `path`, owner-readable only. May raise; callers that
    write are expected to handle it, since a failed write has to be turned
    into an explicit decision rather than silently ignored.
    """
    fd = os.open(path, CREATE_FLAGS, FILE_MODE)
    try:
        # A file that already existed keeps its old mode, so set it explicitly
        # rather than trusting the create mode to have applied.
        os.fchmod(fd, FILE_MODE)
        os.write(fd, text.encode())
    finally:
        os.close(fd)
