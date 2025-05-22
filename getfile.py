import requests
from tqdm import tqdm
import os
import sys
import time
from urllib.parse import urlparse, unquote

def parse_proxy_line(line):
    """
    Parse a line from proxies.txt and return a requests-compatible proxy dict or None.
    Supports: http, https, socks5, shadowsocks (ss://...)
    """
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    if line.startswith('ss://'):
        # Shadowsocks is not natively supported by requests.
        # Requires external tools (e.g. running local socks5 via ss-local).
        # Here, we skip it but could add logic to run ss-local and return the local socks5 address.
        # For now, return None with a note.
        return {'type': 'shadowsocks', 'raw': line}
    # For all other formats
    if line.startswith('socks5://') or line.startswith('socks5h://'):
        return {'http': line, 'https': line}
    if line.startswith('http://') or line.startswith('https://'):
        return {'http': line, 'https': line}
    # Try socks5 as fallback
    if ':' in line:
        return {'http': 'socks5://' + line, 'https': 'socks5://' + line}
    return None

def load_proxies(proxy_file='proxies.txt'):
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

def test_proxy(url, proxy, timeout=5):
    """
    Test a proxy by attempting a HEAD request to the URL.
    Returns a tuple: (is_working, latency, proxy)
    For shadowsocks, always returns False (unless you add ss-local support).
    """
    if 'type' in proxy and proxy['type'] == 'shadowsocks':
        # SKIP: Implement ss-local startup here if you want, or skip as not supported
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

def choose_best_proxy(url, proxies, max_to_test=10):
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

def get_filename_from_url(url, response):
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

def prompt_use_proxy():
    """
    Ask the user if they want to use a proxy.
    """
    while True:
        choice = input("Use proxy? (y or n): ").strip().lower()
        if choice in ('y', 'yes'):
            return True
        elif choice in ('n', 'no'):
            return False
        else:
            print("Please enter 'y' or 'n'.")

def fast_wget(url, proxy_file='proxies.txt', chunk_size=8192):
    """
    Download a file from a URL with progress bar, proxy support, and fast streaming.
    """
    use_proxy = prompt_use_proxy()
    proxies = []
    chosen_proxy = None

    if use_proxy:
        proxies = load_proxies(proxy_file)
        if not proxies:
            print("No proxies found in proxies.txt.")
        else:
            print("Testing proxies, please wait...")
            chosen_proxy = choose_best_proxy(url, proxies, max_to_test=min(len(proxies), 10))
            if not chosen_proxy:
                print("No working proxies found, downloading directly.")
            elif 'type' in chosen_proxy and chosen_proxy['type'] == 'shadowsocks':
                print("Shadowsocks proxies require running a local socks5 proxy (not supported automatically).")
                print("Skipping shadowsocks proxy. Downloading directly.")
                chosen_proxy = None
            else:
                print(f"Using proxy: {chosen_proxy['http']}")

    proxy_dict = chosen_proxy if (chosen_proxy and 'type' not in chosen_proxy) else None

    try:
        with requests.get(url, stream=True, proxies=proxy_dict, timeout=10) as r:
            r.raise_for_status()
            filename = get_filename_from_url(url, r)
            total = int(r.headers.get('content-length', 0))
            with open(filename, 'wb') as f, tqdm(
                desc=filename,
                total=total,
                unit='iB',
                unit_scale=True,
                unit_divisor=1024,
            ) as bar:
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if chunk:
                        size = f.write(chunk)
                        bar.update(size)
        print(f"Downloaded to {filename}")
        return filename
    except Exception as e:
        print(f"Download failed: {e}")
        return None

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="A fast wget analog with progress bar and proxy support (auto-proxy selection).")
    parser.add_argument("url", help="URL to download")
    parser.add_argument("--proxy-file", help="Path to proxies.txt", default="proxies.txt")
    args = parser.parse_args()
    fast_wget(args.url, proxy_file=args.proxy_file)