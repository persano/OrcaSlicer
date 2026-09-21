#!/usr/bin/env python3
"""
apply_bbl_patches.py

Autonomous patching script to port Bambu Lab Cloud / P1S support onto any OrcaSlicer
ref (stable releases, main, or nightly builds).
"""

import os
import sys
import subprocess
import argparse
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_DIR = REPO_ROOT.parent / "bbl-patches" / "v2.4.2-port"
CLEAN_PATCH_DIR = REPO_ROOT.parent / "bbl-patches" / "clean"


def run_cmd(cmd, cwd=REPO_ROOT, check=True):
    print(f"[CMD] {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    res = subprocess.run(
        cmd,
        cwd=cwd,
        shell=isinstance(cmd, str),
        capture_output=True,
        text=True,
    )
    if check and res.returncode != 0:
        print(f"[ERROR] Command failed with code {res.returncode}:\n{res.stderr.strip()}", file=sys.stderr)
        raise subprocess.CalledProcessError(res.returncode, cmd, output=res.stdout, stderr=res.stderr)
    return res


def fix_gui_app_conflict(file_path: Path):
    if not file_path.exists():
        return
    content = file_path.read_text(encoding="utf-8", errors="replace")
    if "<<<<<<<" not in content:
        return

    pattern = re.compile(
        r"<<<<<<< HEAD.*?"
        r"(auto should_load_networking_plugin = app_config->get_bool\(\"installed_networking\"\);).*?"
        r"=======\s*"
        r"(auto should_load_networking_plugin = app_config->get_bool\(\"installed_networking\"\) && Slic3r::is_bambu_host_mode\(\);).*?"
        r">>>>>>>.*?\n",
        re.DOTALL
    )

    if pattern.search(content):
        resolved = pattern.sub(r"\2\n", content)
        # Also clean any leftover conflict marker lines around it
        resolved = re.sub(r"<<<<<<< HEAD\n", "", resolved)
        resolved = re.sub(r">>>>>>> [^\n]+\n", "", resolved)
        resolved = re.sub(r"=======\n", "", resolved)
        file_path.write_text(resolved, encoding="utf-8")
        print(f"[FIX] Auto-resolved conflict in {file_path.name}")


def fix_version_conflict(file_path: Path):
    if not file_path.exists():
        return
    content = file_path.read_text(encoding="utf-8", errors="replace")
    if "<<<<<<<" not in content:
        return
    # Force SLIC3R_VERSION to 02.07.01.57 for Bambu network agent ABI parity
    resolved = re.sub(
        r"<<<<<<< HEAD.*?set\(SLIC3R_VERSION \".*?\"\).*?=======\s*set\(SLIC3R_VERSION \"02\.07\.01\.57\"\).*?>>>>>>> [^\n]+\n",
        'set(SLIC3R_VERSION "02.07.01.57")\n',
        content,
        flags=re.DOTALL
    )
    file_path.write_text(resolved, encoding="utf-8")
    print(f"[FIX] Auto-resolved SLIC3R_VERSION conflict in {file_path.name}")


def fix_cmake_conflict(file_path: Path):
    if not file_path.exists():
        return
    content = file_path.read_text(encoding="utf-8", errors="replace")
    if "<<<<<<<" not in content:
        return
    # If MSVC force multiple was merged into conflict block
    if "FORCE:MULTIPLE" in content:
        resolved = content.replace("<<<<<<< HEAD\n", "").replace("=======\n", "")
        resolved = re.sub(r">>>>>>> [^\n]+\n", "", resolved)
        file_path.write_text(resolved, encoding="utf-8")
        print(f"[FIX] Auto-resolved MSVC linker options in {file_path.name}")


def apply_patches(patch_dir: Path):
    patches = sorted(patch_dir.glob("0*.patch"))
    if not patches:
        print(f"[WARN] No patches found in {patch_dir}", file=sys.stderr)
        return False

    print(f"[INFO] Found {len(patches)} patches to apply.")
    for p in patches:
        print(f"[INFO] Applying {p.name}...")
        res = run_cmd(["git", "am", "-3", str(p)], check=False)
        if res.returncode != 0:
            print(f"[WARN] Conflict while applying {p.name}. Attempting auto-resolution...")
            fix_gui_app_conflict(REPO_ROOT / "src" / "slic3r" / "GUI" / "GUI_App.cpp")
            fix_version_conflict(REPO_ROOT / "version.inc")
            fix_cmake_conflict(REPO_ROOT / "src" / "CMakeLists.txt")
            
            run_cmd(["git", "add", "-u"], check=False)
            cont_res = run_cmd(["git", "am", "--continue"], check=False)
            if cont_res.returncode != 0:
                print(f"[ERROR] Could not auto-resolve conflict for {p.name}. Aborting.", file=sys.stderr)
                run_cmd(["git", "am", "--abort"], check=False)
                return False

    print("[SUCCESS] All patches applied successfully.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Apply Bambu Lab cloud patches to OrcaSlicer")
    parser.add_argument("--ref", default=None, help="Target git ref (tag, branch, commit) to checkout first")
    parser.add_argument("--clean-only", action="store_true", help="Use raw clean patch series instead of v2.4.2 series")
    args = parser.parse_args()

    if args.ref:
        print(f"[INFO] Checking out target ref: {args.ref}")
        run_cmd(["git", "checkout", args.ref])

    target_dir = CLEAN_PATCH_DIR if args.clean_only else (PATCH_DIR if PATCH_DIR.exists() else CLEAN_PATCH_DIR)
    success = apply_patches(target_dir)

    if success:
        print("[INFO] Updating MinHook submodule...")
        run_cmd(["git", "submodule", "update", "--init", "--recursive", "deps/minhook"], check=False)
        print("[DONE] Codebase patched and ready for build.")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
