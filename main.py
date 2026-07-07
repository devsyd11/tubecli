import os
import sys
import shutil
import time
import winreg
from pathlib import Path
from urllib.parse import urlparse, parse_qs

try:
    import yt_dlp
except ImportError:
    print("ERROR: yt-dlp is not installed. Run: pip install -r requirements.txt")
    input("Press Enter to exit...")
    sys.exit(1)

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import (
        Progress, SpinnerColumn, BarColumn, TextColumn,
        DownloadColumn, TransferSpeedColumn, TimeRemainingColumn,
    )
    from rich.prompt import Prompt, Confirm
    from rich.text import Text
    from rich.align import Align
    from rich import box
except ImportError:
    print("ERROR: rich is not installed. Run: pip install -r requirements.txt")
    input("Press Enter to exit...")
    sys.exit(1)

BANNER = (
    "████████╗██╗   ██╗██████╗ ███████╗ ██████╗██╗     ██╗\n"
    "   ██╔╝  ██║   ██║██╔══██╗██╔════╝██╔════╝██║     ██║\n"
    "   ██║   ██║   ██║██████╔╝█████╗  ██║     ██║     ██║\n"
    "   ██║   ██║   ██║██╔══██╗██╔══╝  ██║     ██║     ██║\n"
    "   ██║   ╚██████╔╝██████╔╝███████╗╚██████╗███████╗██║\n"
    "   ╚═╝    ╚═════╝ ╚═════╝ ╚══════╝ ╚═════╝╚══════╝╚═╝"
)

VERSION = "1.0.0"


def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def get_output_dir() -> Path:
    out = get_app_dir() / "downloads"
    out.mkdir(exist_ok=True)
    return out


def get_ffmpeg_local_dir() -> Path:
    return get_app_dir() / "ffmpeg"


def _add_local_ffmpeg_to_path(local_dir: Path) -> None:
    os.environ["PATH"] = str(local_dir) + os.pathsep + os.environ.get("PATH", "")


def add_to_user_path(directory: Path) -> bool:
    """
    Permanently write directory into the current user's PATH via the Windows registry.
    Uses HKCU — no admin rights needed. Idempotent: skips if already present.
    Broadcasts WM_SETTINGCHANGE so open terminals pick up the change immediately.
    """
    dir_str = str(directory)
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, "Environment",
            0, winreg.KEY_READ | winreg.KEY_WRITE,
        )
        try:
            current, _ = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current = ""

        entries = [e for e in current.split(os.pathsep) if e]
        if dir_str not in entries:
            entries.append(dir_str)
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ,
                              os.pathsep.join(entries))
        winreg.CloseKey(key)

        import ctypes
        ctypes.windll.user32.SendMessageTimeoutW(
            0xFFFF, 0x001A, 0, "Environment", 2, 5000, None
        )
        return True
    except Exception:
        return False


def ensure_ffmpeg(console: Console) -> bool:
    if shutil.which("ffmpeg"):
        return True

    local_dir = get_ffmpeg_local_dir()
    if (local_dir / "ffmpeg.exe").exists():
        _add_local_ffmpeg_to_path(local_dir)
        return True

    console.print("  [yellow]One-time setup: downloading FFmpeg (~60 MB)...[/]\n")
    try:
        import static_ffmpeg
        with console.status("  [cyan]Downloading FFmpeg, please wait...[/]", spinner="dots"):
            static_ffmpeg.add_paths(weak=False)

        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            raise RuntimeError("FFmpeg still not found after download.")

        src_dir = Path(ffmpeg_path).parent
        local_dir.mkdir(parents=True, exist_ok=True)
        for binary in ("ffmpeg.exe", "ffprobe.exe"):
            src = src_dir / binary
            if src.exists():
                shutil.copy2(src, local_dir / binary)

        add_to_user_path(local_dir)
        console.print("  [bold green]✔ FFmpeg downloaded and added to your PATH![/]\n")
        console.print("  [dim]FFmpeg is now available system-wide in any new terminal.[/]\n")
        return True

    except Exception as e:
        console.print(
            Panel(
                f"[bold red]Could not install FFmpeg automatically[/]\n\n[dim]{e}[/]\n\n"
                "Install manually: https://ffmpeg.org/download.html\n"
                "Then add the 'bin' folder to your Windows PATH and restart.",
                border_style="red", box=box.ROUNDED, padding=(0, 2),
            )
        )
        return False


def show_banner(console: Console) -> None:
    console.print()
    console.print(Align.center(Text(BANNER, style="bold red", justify="center")))
    console.print(
        Panel(
            Align.center(
                f"[bold cyan]TubeCLI[/]  [dim]YouTube → MP3  •  v{VERSION}[/]\n"
                f"[dim]Built with [bold red]♥[/] by Syd[/]"
            ),
            border_style="red",
            box=box.DOUBLE,
            padding=(0, 4),
        )
    )
    console.print()


def is_playlist_url(url: str) -> bool:
    """Return True if the URL contains a playlist ID (not a radio/autoplay mix)."""
    try:
        params = parse_qs(urlparse(url).query)
        list_id = params.get("list", [""])[0]
        # RD = radio/autoplay mix — those are fine to download as single videos
        return bool(list_id) and not list_id.startswith("RD")
    except Exception:
        return False


def validate_url(url: str) -> bool:
    u = url.strip().lower()
    return ("youtube.com" in u or "youtu.be" in u) and u.startswith("http")


def make_dl_hook(progress: Progress, dl_task, convert_task):
    def hook(d: dict):
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done  = d.get("downloaded_bytes", 0)
            speed = d.get("_speed_str", "").strip() or "..."
            eta   = d.get("_eta_str",   "").strip() or "..."
            progress.update(
                dl_task,
                completed=done,
                total=total if total > 0 else max(done * 2, 1),
                description=f"[cyan]Downloading[/]  [dim]{speed}  ETA {eta}[/]",
                visible=True,
            )
        elif status == "finished":
            progress.update(dl_task, visible=False)
            progress.update(convert_task, visible=True)
        elif status == "error":
            progress.update(dl_task, visible=False)
            progress.update(convert_task, visible=False)
    return hook


def download_single(url: str, output_dir: Path, console: Console) -> tuple[bool, str]:
    title_box: list[str] = ["Unknown"]

    with Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=28, style="cyan", complete_style="green"),
        DownloadColumn(), TransferSpeedColumn(), TimeRemainingColumn(),
        console=console, transient=True,
    ) as progress:
        dl_task      = progress.add_task("[cyan]Starting...[/]", total=None, visible=True)
        convert_task = progress.add_task(
            "[yellow]Converting to MP3...[/]", total=None, start=False, visible=False
        )

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
            "postprocessors": [{"key": "FFmpegExtractAudio",
                                "preferredcodec": "mp3", "preferredquality": "192"}],
            "progress_hooks": [make_dl_hook(progress, dl_task, convert_task)],
            "quiet": True, "no_warnings": True,
            "nooverwrites": True, "noplaylist": True,
            "retries": 3, "fragment_retries": 3,
            "socket_timeout": 30, "windowsfilenames": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get("title", "Unknown")
                title_box[0] = title
                short = title[:45] + ("…" if len(title) > 45 else "")
                progress.update(dl_task, description=f"[cyan]Downloading[/]  [dim]{short}[/]")
                ydl.download([url])
            return True, title_box[0]
        except yt_dlp.utils.ExtractorError as e:
            return False, f"Could not read video info.\n[dim]{e}[/dim]"
        except yt_dlp.utils.DownloadError as e:
            return False, f"Download failed.\n[dim]{e}[/dim]"
        except Exception as e:
            return False, f"Unexpected error: {e}"


def main():
    console = Console()
    show_banner(console)

    if not ensure_ffmpeg(console):
        input("\nPress Enter to exit...")
        sys.exit(1)

    output_dir = get_output_dir()
    console.print(f"  [dim]Saving to:[/] [bold]{output_dir}[/]\n")

    while True:
        url = Prompt.ask("  [bold cyan]YouTube URL[/] [dim](or Q to quit)[/]").strip()

        if url.lower() in ("q", "quit", "exit", ""):
            break

        if not validate_url(url):
            console.print(
                Panel(
                    "[red]That doesn't look like a YouTube URL.[/]\n"
                    "[dim]Example: https://www.youtube.com/watch?v=...[/]",
                    border_style="red", box=box.ROUNDED, padding=(0, 2),
                )
            )
            console.print()
            continue

        if is_playlist_url(url):
            console.print(
                Panel(
                    "[yellow]That looks like a playlist URL.[/]\n\n"
                    "Playlist downloading is not supported yet.\n"
                    "[dim]Tip: copy the link to a single video instead.\n"
                    "Example: https://www.youtube.com/watch?v=R36xGZMoz5Q[/]",
                    border_style="yellow", box=box.ROUNDED, padding=(0, 2),
                    title="[bold yellow] Playlist Detected [/]",
                )
            )
            console.print()
            continue

        console.print()
        success, message = download_single(url, output_dir, console)
        console.print()

        if success:
            console.print(
                Panel(
                    f"[bold green]✔ Downloaded successfully![/]\n\n"
                    f"  [bold white]{message}.mp3[/]\n"
                    f"  [dim]Saved to: {output_dir}[/]",
                    border_style="green", box=box.ROUNDED, padding=(0, 2),
                    title="[bold green] Done [/]",
                )
            )
        else:
            console.print(
                Panel(
                    f"[bold red]✘ Something went wrong[/]\n\n{message}",
                    border_style="red", box=box.ROUNDED, padding=(0, 2),
                    title="[bold red] Error [/]",
                )
            )

        console.print()

    console.print(
        Panel(
            Align.center(Text("Thanks for using TubeCLI !", style="bold cyan")),
            border_style="cyan", box=box.ROUNDED, padding=(0, 4),
        )
    )
    time.sleep(2)


if __name__ == "__main__":
    main()
