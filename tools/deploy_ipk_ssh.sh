#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  tools/deploy_ipk_ssh.sh [options] <host|user@host> [package.ipk]

Examples:
  tools/deploy_ipk_ssh.sh 192.168.1.23
  tools/deploy_ipk_ssh.sh root@192.168.1.23 icopy-x-about-scroll-text-no-flash.ipk
  tools/deploy_ipk_ssh.sh -p 2222 -f icopy-x-about-scroll-text-no-flash.ipk 192.168.1.23
  tools/deploy_ipk_ssh.sh --dry-run 192.168.1.23

Options:
  -f, --file PATH       IPK to upload. Defaults to newest *.ipk in repo root.
  -d, --dest PATH       Remote destination directory. Default: /mnt/upan
  -u, --user USER       SSH user when host has no user@ prefix. Default: root
  -p, --port PORT       SSH port. Default: 22
  --keep-existing       Do not remove existing root-level *.ipk files first.
  --no-mux              Disable SSH connection sharing.
  --force               Upload even if /mnt/upan does not look mounted.
  -n, --dry-run         Print actions without uploading.
  -h, --help            Show this help.

Notes:
  By default, the script removes only root-level *.ipk and ._*.ipk files from
  the destination directory before upload, so the updater sees one package.
  It does not touch ipk_old/ or other subdirectories.
  The script only copies the IPK and runs sync. It does not install or reboot.
  The iCopy-X default SSH login is usually root / fa.
EOF
}

die() {
    echo "deploy_ipk_ssh: $*" >&2
    exit 1
}

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

target=""
ipk=""
dest="/mnt/upan"
user="root"
port="22"
dry_run=0
force=0
clean_existing=1
use_mux=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        -f|--file)
            [[ $# -ge 2 ]] || die "$1 requires a path"
            ipk="$2"
            shift 2
            ;;
        -d|--dest)
            [[ $# -ge 2 ]] || die "$1 requires a remote directory"
            dest="${2%/}"
            shift 2
            ;;
        -u|--user)
            [[ $# -ge 2 ]] || die "$1 requires a user"
            user="$2"
            shift 2
            ;;
        -p|--port)
            [[ $# -ge 2 ]] || die "$1 requires a port"
            port="$2"
            shift 2
            ;;
        --force)
            force=1
            shift
            ;;
        --keep-existing)
            clean_existing=0
            shift
            ;;
        --no-mux)
            use_mux=0
            shift
            ;;
        -n|--dry-run)
            dry_run=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            break
            ;;
        -*)
            die "unknown option: $1"
            ;;
        *)
            if [[ -z "$target" ]]; then
                target="$1"
            elif [[ -z "$ipk" ]]; then
                ipk="$1"
            else
                die "unexpected argument: $1"
            fi
            shift
            ;;
    esac
done

[[ -n "$target" ]] || {
    usage >&2
    exit 2
}

if [[ "$target" != *@* ]]; then
    target="${user}@${target}"
fi

if [[ "$dest" == *"'"* ]]; then
    die "remote destination path must not contain single quotes"
fi

if [[ -z "$ipk" ]]; then
    shopt -s nullglob
    candidates=("$repo_root"/*.ipk)
    shopt -u nullglob

    newest=""
    newest_mtime=0
    for candidate in "${candidates[@]}"; do
        base="$(basename "$candidate")"
        [[ "$base" == ._* ]] && continue
        if mtime="$(stat -f %m "$candidate" 2>/dev/null)"; then
            :
        else
            mtime="$(stat -c %Y "$candidate" 2>/dev/null || echo 0)"
        fi
        if (( mtime > newest_mtime )); then
            newest_mtime="$mtime"
            newest="$candidate"
        fi
    done

    [[ -n "$newest" ]] || die "no *.ipk found in repo root; pass --file"
    ipk="$newest"
elif [[ "$ipk" != /* && ! -f "$ipk" && -f "$repo_root/$ipk" ]]; then
    ipk="$repo_root/$ipk"
fi

[[ -f "$ipk" ]] || die "IPK not found: $ipk"
[[ "$(basename "$ipk")" != ._* ]] || die "refusing to upload AppleDouble sidecar: $ipk"
[[ "$ipk" == *.ipk ]] || die "not an .ipk file: $ipk"

base="$(basename "$ipk")"
if [[ "$base" == *"'"* ]]; then
    die "IPK filename must not contain single quotes"
fi

ssh_args=(-p "$port" -o ServerAliveInterval=10 -o ServerAliveCountMax=3)
scp_args=(-P "$port" -o ServerAliveInterval=10 -o ServerAliveCountMax=3)

control_path=""
mux_dir=""
if [[ "$use_mux" -eq 1 ]]; then
    # OpenSSH Unix-domain ControlPath has a short platform limit.  macOS
    # TMPDIR lives under /var/folders/... and can exceed that limit before the
    # socket name is added, so keep the mux path deliberately short.
    mux_dir="/tmp/icopyx_mux_$$"
    control_path="$mux_dir/s"
    ssh_args+=(-o ControlMaster=auto -o ControlPersist=60 -o "ControlPath=$control_path")
    scp_args+=(-o ControlMaster=auto -o ControlPersist=60 -o "ControlPath=$control_path")
fi

remote_dest="'$dest'"
remote_file="'$dest/$base'"
remote_sidecar="'$dest/._$base'"

echo "[deploy] target: $target"
echo "[deploy] file:   $ipk"
echo "[deploy] dest:   $dest/$base"
if [[ "$use_mux" -eq 1 ]]; then
    echo "[deploy] ssh:    connection sharing enabled; one password prompt expected"
fi

if [[ "$dry_run" -eq 1 ]]; then
    if [[ "$use_mux" -eq 1 ]]; then
        echo "[dry-run] ssh ${ssh_args[*]} -N -f $target"
    fi
    echo "[dry-run] ssh ${ssh_args[*]} $target test -d $remote_dest"
    if [[ "$clean_existing" -eq 1 ]]; then
        echo "[dry-run] ssh ${ssh_args[*]} $target find $remote_dest -maxdepth 1 -type f '(' -name '*.ipk' -o -name '._*.ipk' ')' -print -delete"
    fi
    echo "[dry-run] scp ${scp_args[*]} $ipk $target:$dest/"
    echo "[dry-run] ssh ${ssh_args[*]} $target rm -f $remote_sidecar && sync && ls -lh $remote_file"
    exit 0
fi

if [[ "$use_mux" -eq 1 ]]; then
    mkdir -p "$mux_dir"
    chmod 700 "$mux_dir" 2>/dev/null || true
    cleanup_mux() {
        ssh -p "$port" -o "ControlPath=$control_path" -O exit "$target" >/dev/null 2>&1 || true
        rmdir "$mux_dir" >/dev/null 2>&1 || true
    }
    trap cleanup_mux EXIT
    ssh "${ssh_args[@]}" -N -f "$target"
fi

ssh "${ssh_args[@]}" "$target" "test -d $remote_dest"

if [[ "$dest" == "/mnt/upan" && "$force" -eq 0 ]]; then
    ssh "${ssh_args[@]}" "$target" \
        "mount | grep -q ' on /mnt/upan ' || { echo 'ERROR: /mnt/upan does not look mounted. Use --force to upload anyway.' >&2; exit 3; }"
fi

if [[ "$clean_existing" -eq 1 ]]; then
    echo "[deploy] removing existing IPKs from $dest"
    ssh "${ssh_args[@]}" "$target" \
        "find $remote_dest -maxdepth 1 -type f '(' -name '*.ipk' -o -name '._*.ipk' ')' -print -delete"
else
    ssh "${ssh_args[@]}" "$target" "rm -f $remote_sidecar"
fi
scp "${scp_args[@]}" "$ipk" "$target:$dest/"
ssh "${ssh_args[@]}" "$target" "sync && ls -lh $remote_file"

echo "[deploy] uploaded. On the device, open About -> firmware update to install it."
