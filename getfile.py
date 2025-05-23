import requests
import os
import sys
import time
from typing import Optional, Dict, List, Any
from urllib.parse import urlparse, unquote

try:
    from rich.console import Console
    from rich.progress import Progress, BarColumn, TextColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False

def parse_proxy_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Parse a line from proxies.txt and return a requests-compatible proxy dict or None.
    Supports: http, https, socks5, shadowsocks (ss://...)
    """
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    if line.startswith('ss://'):
        # Shadowsocks not natively supported by requests.
        return {'type': 'shadowsocks', 'raw': line}
    if line.startswith('socks5://') or line.startswith('socks5h://'):
        return {'http': line, 'https': line}
    if line.startswith('http://') or line.startswith('https://'):
        return {'http': line, 'https': line}
    if ':' in line:
        return {'http': 'socks5://' + line, 'https': 'socks5://' + line}
    return None

def load_proxies(proxy_file: str = 'proxies.txt') -> List[Dict[str, Any]]:
    """
    Loads all proxies from file, returns a list of dicts.
    """
    proxies = []
    if not os.path.exists(proxy_file):
        return proxies
    with open(proxy_file, 'r') as f:
        for line in f:
            proxy = parse_proxy_line(line)
            if proxy:
                proxies.append(proxy)
    return proxies

def test_proxy(url: str, proxy: Dict[str, Any], timeout: int = 5):
    """
    Test a proxy by attempting a HEAD request to the URL.
    Returns a tuple: (is_working, latency, proxy)
    For shadowsocks, always returns False (unless you add ss-local support).
    """
    if 'type' in proxy and proxy['type'] == 'shadowsocks':
        return (False, float('inf'), proxy)
    try:
        start = time.perf_counter()
        r = requests.head(url, proxies=proxy, timeout=timeout, allow_redirects=True)
        latency = time.perf_counter() - start
        if 200 <= r.status_code < 400:
            return (True, latency, proxy)
        return (False, float('inf'), proxy)
    except Exception:
        return (False, float('inf'), proxy)

def choose_best_proxy(url: str, proxies: List[Dict[str, Any]], max_to_test: int = 10) -> Optional[Dict[str, Any]]:
    """
    Test all proxies in parallel and pick the fastest working one.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = []
    proxies_to_test = proxies[:max_to_test]
    with ThreadPoolExecutor(max_workers=min(10, len(proxies_to_test))) as executor:
        future_to_proxy = {executor.submit(test_proxy, url, p): p for p in proxies_to_test}
        for future in as_completed(future_to_proxy):
            ok, latency, p = future.result()
            if ok:
                results.append((latency, p))
    if not results:
        return None
    best = min(results, key=lambda x: x[0])[1]
    return best

def get_filename_from_url(url: str, response: requests.Response) -> str:
    """
    Try to get filename from Content-Disposition header, otherwise from URL.
    """
    cd = response.headers.get('content-disposition')
    if cd and 'filename=' in cd:
        filename = cd.split('filename=')[1]
        if filename[0] == '"' or filename[0] == "'":
            filename = filename[1:-1]
        filename = unquote(filename)
        return filename
    # Fallback: get from URL path
    path = urlparse(url).path
    filename = os.path.basename(path)
    if not filename:
        filename = "downloaded.file"
    return filename

def print_status(msg: str, style: str = "info"):
    if RICH_AVAILABLE:
        styles = {
            "info": "bold cyan",
            "success": "bold green",
            "error": "bold red",
            "warn": "bold yellow"
        }
        console.print(msg, style=styles.get(style, ""))
    else:
        print(msg)

def format_size(bytes_num: int) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_num < 1024.0:
            return f"{bytes_num:.1f}{unit}"
        bytes_num /= 1024.0
    return f"{bytes_num:.1f}PB"

def prompt_use_proxy() -> bool:
    if not sys.stdin.isatty():
        return False
    while True:
        choice = input("Use proxy? (y or n): ").strip().lower()
        if choice in ('y', 'yes'):
            return True
        elif choice in ('n', 'no'):
            return False
        else:
            print("Please enter 'y' or 'n'.")

def show_progress_bar(filename: str, total: int, get_chunk, *, bar_length: int = 20):
    downloaded = 0
    start_time = time.time()
    last_update = start_time
    last_downloaded = 0

    while True:
        chunk = get_chunk()
        if chunk is None:
            break
        chunk_len = len(chunk)
        downloaded += chunk_len

        now = time.time()
        elapsed = now - start_time
        percent = downloaded / total if total else 0
        filled_len = int(bar_length * percent)
        bar = '#' * filled_len + '-' * (bar_length - filled_len)
        percent_disp = int(percent * 100)
        downloaded_mb = downloaded / (1024 * 1024)
        total_mb = total / (1024 * 1024) if total else 0
        speed = (downloaded - last_downloaded) / (now - last_update + 1e-6) / (1024 * 1024)
        last_update = now
        last_downloaded = downloaded

        print(f"\rDownloading: [{bar}] {percent_disp:2d}%  {downloaded_mb:.1f}MB/{total_mb:.1f}MB  {speed:.1f}MB/s", end='', flush=True)
    print()  # Clear the line afterwards

def fast_wget(
    url: str,
    proxy_file: str = 'proxies.txt',
    chunk_size: int = 8192,
    use_proxy: Optional[bool] = None
) -> Optional[str]:
    """
    Download a file from a URL with a premium progress bar, proxy support, and fast streaming.
    """
    if use_proxy is None:
        use_proxy = prompt_use_proxy()
    proxies = []
    chosen_proxy = None

    if use_proxy:
        print_status("Connecting to fastest proxy...", "info")
        proxies = load_proxies(proxy_file)
        if not proxies:
            print_status("No proxies found in proxies.txt.", "warn")
        else:
            chosen_proxy = choose_best_proxy(url, proxies, max_to_test=min(len(proxies), 10))
            if not chosen_proxy:
                print_status("No working proxies found, downloading directly.", "warn")
            elif 'type' in chosen_proxy and chosen_proxy['type'] == 'shadowsocks':
                print_status("Shadowsocks proxies require running a local socks5 proxy (not supported automatically).", "warn")
                print_status("Skipping shadowsocks proxy. Downloading directly.", "warn")
                chosen_proxy = None
            else:
                addr = chosen_proxy.get('http', '(unknown)')
                print_status(f"Using proxy: {addr}", "success")

    proxy_dict = chosen_proxy if (chosen_proxy and 'type' not in chosen_proxy) else None

    try:
        with requests.get(url, stream=True, proxies=proxy_dict, timeout=10) as r:
            r.raise_for_status()
            filename = get_filename_from_url(url, r)
            total = int(r.headers.get('content-length', 0))
            with open(filename, 'wb') as f:
                if RICH_AVAILABLE:
                    with Progress(
                        TextColumn("[progress.description]{task.description}"),
                        BarColumn(),
                        DownloadColumn(),
                        TransferSpeedColumn(),
                        TimeRemainingColumn(),
                        console=console,
                    ) as progress:
                        task = progress.add_task(f"[cyan]{filename}", total=total)
                        for chunk in r.iter_content(chunk_size=chunk_size):
                            if chunk:
                                f.write(chunk)
                                progress.update(task, advance=len(chunk))
                else:
                    downloaded = 0
                    start_time = time.time()
                    bar_length = 15
                    def get_chunk_gen():
                        for chunk in r.iter_content(chunk_size=chunk_size):
                            yield chunk
                        yield None
                    chunk_iter = iter(get_chunk_gen())
                    def get_chunk():
                        return next(chunk_iter)
                    while True:
                        chunk = get_chunk()
                        if chunk is None:
                            break
                        chunk_len = len(chunk)
                        downloaded += chunk_len
                        elapsed = time.time() - start_time
                        percent = downloaded / total if total else 0
                        filled_len = int(bar_length * percent)
                        bar = '#' * filled_len + '-' * (bar_length - filled_len)
                        percent_disp = int(percent * 100)
                        downloaded_mb = downloaded / (1024 * 1024)
                        total_mb = total / (1024 * 1024) if total else 0
                        speed = downloaded / (elapsed + 1e-6) / (1024 * 1024)
                        print(
                            f"\rDownloading: [{bar}] {percent_disp:2d}%  {downloaded_mb:.1f}MB/{total_mb:.1f}MB  {speed:.1f}MB/s",
                            end='', flush=True
                        )
                        f.write(chunk)
                    print()  # Newline after progress bar
            file_size = os.path.getsize(filename)
            file_size_mb = file_size / (1024 * 1024)
            checkmark = "✔️" if RICH_AVAILABLE else "OK"
            print_status(f"Download complete: {filename} ({file_size_mb:.1f}MB) {checkmark}", "success")
            return filename
    except Exception as e:
        print_status(f"Download failed: {e}", "error")
        return None

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="A fast wget analog with premium progress bar and proxy support (auto-proxy selection).")
    parser.add_argument("url", help="URL to download")
    parser.add_argument("--proxy-file", help="Path to proxies.txt", default="proxies.txt")
    parser.add_argument("--no-proxy", action="store_true", help="Do not use proxy even if present")
    args = parser.parse_args()
    fast_wget(args.url, proxy_file=args.proxy_file, use_proxy=not args.no_proxy)