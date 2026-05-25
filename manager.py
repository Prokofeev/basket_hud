import ctypes
import datetime
import difflib
import hashlib
import http.server
import html
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Any, Dict, List, Tuple
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

import customtkinter as ctk
import psutil

from broadcast_control.diagnostics import HealthCheckService
from broadcast_control.models import GraphicState, PlayerState
from broadcast_control.services import PIDManager, ScraperProcessController
from broadcast_control.state import AppPaths, JsonStateStore


if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def resolve_data_paths(base_dir: str) -> Tuple[str, str, str]:
    candidates = [
        base_dir,
        os.path.dirname(base_dir),
    ]

    for root in candidates:
        config_candidate = os.path.join(root, "json", "config.json")
        result_candidate = os.path.join(root, "json", "result.json")
        if os.path.exists(config_candidate) or os.path.exists(result_candidate):
            return (
                config_candidate,
                result_candidate,
                os.path.join(root, "main.exe"),
            )

    # Fallback: keep behavior deterministic even if json files are missing yet.
    return (
        os.path.join(base_dir, "json", "config.json"),
        os.path.join(base_dir, "json", "result.json"),
        os.path.join(base_dir, "main.exe"),
    )


CONFIG_PATH, RESULT_PATH, MAIN_EXE = resolve_data_paths(BASE_DIR)
PLAYER_PATH = os.path.join(os.path.dirname(CONFIG_PATH), "player.json")
PLAYER_CACHE_DIR = os.path.join(os.path.dirname(CONFIG_PATH), "players")
PLAYER_DEBUG_PATH = os.path.join(os.path.dirname(CONFIG_PATH), "player_candidates.json")
NBA_PLAYERS_CACHE_PATH = os.path.join(os.path.dirname(CONFIG_PATH), "nba_players_cache.json")
CONTENT_ROOT = os.path.dirname(os.path.dirname(CONFIG_PATH))
APP_PATHS = AppPaths.resolve(BASE_DIR)
STATE_STORE = JsonStateStore(APP_PATHS.json_dir)
PID_MANAGER = PIDManager(APP_PATHS.pid_path, MAIN_EXE)
SCRAPER_CONTROLLER = ScraperProcessController(MAIN_EXE, os.path.dirname(MAIN_EXE), PID_MANAGER)

NBA_ABBRS = {
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}


def read_json(path: str) -> Dict[str, Any]:
    candidates = [path]
    root, ext = os.path.splitext(path)
    if ext.lower() == ".json":
        candidates.append(f"{root}.last_good.json")

    for candidate in candidates:
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
    return {}


def write_json(path: str, data: Dict[str, Any], atomic: bool = False) -> Tuple[bool, str]:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        STATE_STORE.write_raw(path, data, update_last_good=atomic)
        return True, ""
    except OSError as exc:
        return False, str(exc)


def default_player_data() -> Dict[str, Any]:
    return {
        "schema_version": 2,
        "visible": False,
        "mode": "hidden",
        "updated_at": "",
        "source": "manager",
        "team_side": "",
        "match_key": "",
        "name": "",
        "number": "",
        "position": "",
        "team": "",
        "photo": "",
        "photo_source": "",
        "photo_status": "",
        "stats": {
            "PPG": "",
            "RPG": "",
            "APG": "",
            "STL": "",
            "BLK": "",
            "FG": "",
            "3P": "",
            "FT": "",
            "MIN": "",
            "PLUS_MINUS": "",
            "TOV": "",
            "PF": "",
        },
    }


def normalize_name(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-zа-яё\s'-]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


CYR_TO_LAT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
})

NBA_NAME_HINTS = {
    "wembanyama": "1641705", "vembanyama": "1641705", "вембаньяма": "1641705",
    "gilgeous alexander": "1628983", "gildzhes aleksander": "1628983", "гилджес александер": "1628983",
    "fox": "1628368", "foks": "1628368", "фокс": "1628368",
    "vassell": "1630170", "vassel": "1630170", "васселл": "1630170",
    "castle": "1642264", "kasl": "1642264", "касл": "1642264",
    "holmgren": "1631096", "холмгрен": "1631096",
    "jalen williams": "1631114", "williams": "1631114", "уильямс": "1631114",
    "keldon johnson": "1629640", "johnson": "1629640", "джонсон": "1629640",
    "chris paul": "101108", "paul": "101108", "пол": "101108",
    "harrison barnes": "203084", "barnes": "203084", "барнс": "203084",
    "dort": "1629652", "дорту": "1629652",
    "hartenstein": "1628392", "хартенштейн": "1628392",
    "caruso": "1627936", "карузо": "1627936",
    "wallace": "1641717", "уоллес": "1641717",
    "champagnie": "1630577", "шампани": "1630577",
    "sochan": "1631110", "сохан": "1631110",
    "tre jones": "1630200", "jones": "1630200", "джонс": "1630200",
    "brunson": "1628973", "брансон": "1628973",
    "anunoby": "1628384", "ануноби": "1628384",
    "og anunoby": "1628384",
    "mikal bridges": "1628969", "bridges": "1628969", "бриджес": "1628969",
    "towns": "1626157", "таунс": "1626157",
    "josh hart": "1628404", "hart": "1628404", "харт": "1628404",
    "mitchell": "1628378", "митчелл": "1628378",
    "mobley": "1630596", "мобли": "1630596",
    "garland": "1629636", "гарланд": "1629636",
    "jarrett allen": "1628386", "allen": "1628386", "аллен": "1628386",
    "strus": "1629622", "струс": "1629622",
    "deuce mcbride": "1630540", "mcbride": "1630540", "макбрайд": "1630540",
}


def latinize_name(value: str) -> str:
    text = str(value or "").lower().translate(CYR_TO_LAT)
    text = text.replace("dzhes", "geous").replace("dzh", "j").replace("ks", "x")
    text = re.sub(r"[^a-z\s'-]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def find_main_processes() -> List[psutil.Process]:
    result: List[psutil.Process] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name == "main.exe":
                result.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return result


def kill_process_tree(proc: psutil.Process) -> None:
    try:
        children = proc.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return

    for child in children:
        try:
            child.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    try:
        proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass


def get_match_key() -> str:
    config = read_json(CONFIG_PATH)
    urls = config.get("urls", [])
    if not isinstance(urls, list) or not urls:
        return ""
    return str(urls[0]).strip()


def is_nba_match(match_url: str, result_data: Dict[str, Any]) -> Tuple[bool, str]:
    url = (match_url or "").lower()
    url_has_nba = "nba" in url

    home = result_data.get("home", {}) if isinstance(result_data.get("home"), dict) else {}
    away = result_data.get("away", {}) if isinstance(result_data.get("away"), dict) else {}
    home_abbr = str(home.get("abbr", "")).strip().upper()
    away_abbr = str(away.get("abbr", "")).strip().upper()
    teams_are_nba = home_abbr in NBA_ABBRS and away_abbr in NBA_ABBRS

    if url_has_nba and teams_are_nba:
        return True, "nba_detected:url+teams"
    if teams_are_nba:
        return True, "nba_detected:teams"
    if url_has_nba:
        return True, "nba_detected:url"
    return False, "nba_not_detected"


def _read_cached_nba_players() -> List[Dict[str, Any]]:
    try:
        with open(NBA_PLAYERS_CACHE_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []

    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _write_cached_nba_players(players: List[Dict[str, Any]]) -> None:
    if not players:
        return
    try:
        os.makedirs(os.path.dirname(NBA_PLAYERS_CACHE_PATH), exist_ok=True)
        with open(NBA_PLAYERS_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(players, f, ensure_ascii=False)
    except OSError:
        return


def fetch_nba_players() -> List[Dict[str, Any]]:
    endpoint = "https://cdn.nba.com/static/json/liveData/players.json"
    req = urllib.request.Request(
        endpoint,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        },
    )
    players: Any = []
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        players = payload.get("league", {}).get("standard", [])
    except Exception:
        try:
            season_start = datetime.datetime.now(datetime.UTC).year
            if datetime.datetime.now(datetime.UTC).month < 7:
                season_start -= 1
            season = f"{season_start}-{str(season_start + 1)[-2:]}"
            stats_url = (
                "https://stats.nba.com/stats/commonallplayers"
                f"?LeagueID=00&Season={season}&IsOnlyCurrentSeason=1"
            )
            stats_req = urllib.request.Request(
                stats_url,
                headers={
                    "Host": "stats.nba.com",
                    "Accept": "application/json, text/plain, */*",
                    "Origin": "https://www.nba.com",
                    "Referer": "https://www.nba.com/",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "x-nba-stats-origin": "stats",
                    "x-nba-stats-token": "true",
                },
            )
            with urllib.request.urlopen(stats_req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
            result_sets = payload.get("resultSets", [])
            first_set = result_sets[0] if result_sets else {}
            headers = first_set.get("headers", [])
            rows = first_set.get("rowSet", [])
            idx = {name: i for i, name in enumerate(headers)}
            players = []
            for row in rows:
                full_name = str(row[idx.get("DISPLAY_FIRST_LAST", 2)]).strip()
                parts = full_name.split()
                players.append({
                    "firstName": parts[0] if parts else "",
                    "lastName": " ".join(parts[1:]) if len(parts) > 1 else "",
                    "personId": str(row[idx.get("PERSON_ID", 0)]).strip(),
                })
        except Exception:
            cached = _read_cached_nba_players()
            if cached:
                return cached
            return []

    if isinstance(players, list):
        normalized = [p for p in players if isinstance(p, dict)]
        if normalized:
            _write_cached_nba_players(normalized)
            return normalized

    cached = _read_cached_nba_players()
    if cached:
        return cached
    return []


def find_nba_player_id(player_name: str) -> str:
    target = normalize_name(player_name)
    target_latin = latinize_name(player_name)
    if not target and not target_latin:
        return ""

    hint_key = target.replace("-", " ")
    hint_latin = target_latin.replace("-", " ")
    for key, person_id in NBA_NAME_HINTS.items():
        if key in hint_key or key in hint_latin or hint_latin.split(" ")[0:1] == [key]:
            return person_id

    players = fetch_nba_players()
    exact_match = ""
    best_match = ""
    best_score = 0.0
    target_parts = [token for token in target_latin.split() if token]
    target_surname = target_parts[0] if target_parts else ""
    target_initial = ""
    if len(target_parts) > 1 and target_parts[1]:
        target_initial = target_parts[1][0]

    surname_candidates: List[str] = []
    for token in target_parts:
        if len(token) >= 3 and token not in surname_candidates:
            surname_candidates.append(token)
    if target_surname and target_surname not in surname_candidates:
        surname_candidates.insert(0, target_surname)

    for p in players:
        first_name = str(p.get("firstName", "")).strip()
        last_name = str(p.get("lastName", "")).strip()
        person_id = str(p.get("personId", "")).strip()
        full_name = normalize_name(f"{first_name} {last_name}")
        first_norm = normalize_name(first_name)
        last_norm = normalize_name(last_name)
        if not person_id or not full_name:
            continue

        if full_name == target or full_name == target_latin:
            exact_match = person_id
            break

        if target_surname and last_norm == target_surname:
            if not target_initial or (first_norm and first_norm.startswith(target_initial)):
                exact_match = person_id
                break

        if target and target in full_name and best_score < 0.9:
            best_match = person_id
            best_score = 0.9

        if target_latin and target_latin in full_name and best_score < 0.92:
            best_match = person_id
            best_score = 0.92

        if last_norm and surname_candidates:
            for surname in surname_candidates:
                surname_score = difflib.SequenceMatcher(None, surname, last_norm).ratio()
                if first_norm and target_initial and first_norm.startswith(target_initial):
                    surname_score += 0.08
                if surname_score > best_score:
                    best_match = person_id
                    best_score = surname_score

    return exact_match or (best_match if best_score >= 0.78 else "")


def nba_photo_url(person_id: str) -> str:
    safe_id = urllib.parse.quote((person_id or "").strip())
    return f"https://cdn.nba.com/headshots/nba/latest/1040x760/{safe_id}.png"


def _absolute_url(raw_url: str, base_url: str = "") -> str:
    url = str(raw_url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if base_url:
        return urllib.parse.urljoin(base_url, url)
    return ""


def _image_extension_from_url(url: str, default: str = ".jpg") -> str:
    try:
        path = urllib.parse.urlparse(url).path
    except Exception:
        return default
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext in {".png", ".jpg", ".jpeg", ".webp"}:
        return ext
    return default


def _fetch_flashscore_player_photo_url(player_url: str, referer: str = "") -> str:
    absolute_player_url = _absolute_url(player_url, referer)
    if not absolute_player_url:
        return ""
    req = urllib.request.Request(
        absolute_player_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": referer or absolute_player_url,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, OSError, ValueError):
        return ""

    patterns = [
        r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
        r'<meta\s+name=["\']twitter:image["\']\s+content=["\']([^"\']+)["\']',
        r'<img[^>]+class=["\'][^"\']*(?:participant|player)[^"\']*["\'][^>]+src=["\']([^"\']+)["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if not match:
            continue
        found = html.unescape(match.group(1)).strip()
        absolute = _absolute_url(found, absolute_player_url)
        if absolute:
            return absolute
    return ""


def _fetch_sportsdb_player_photo_url(player_name: str) -> str:
    latin = latinize_name(player_name)
    tokens = [t for t in latin.split() if t]
    if not tokens:
        return ""

    queries: List[str] = []
    full = " ".join(tokens)
    if full:
        queries.append(full)
    # Flashscore often gives "Surname I.", so surname-only lookup is useful.
    surname = tokens[0]
    if surname and surname not in queries:
        queries.append(surname)

    for query in queries:
        if len(query) < 3:
            continue
        endpoint = (
            "https://www.thesportsdb.com/api/v1/json/3/searchplayers.php?p="
            f"{urllib.parse.quote(query)}"
        )
        req = urllib.request.Request(
            endpoint,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError):
            continue

        players = payload.get("player", []) if isinstance(payload, dict) else []
        if not isinstance(players, list):
            continue

        best_url = ""
        best_score = 0.0
        for item in players:
            if not isinstance(item, dict):
                continue
            sport = str(item.get("strSport", "")).strip().lower()
            if sport and sport != "basketball":
                continue
            display_name = latinize_name(str(item.get("strPlayer", "")))
            score = 0.0
            if display_name:
                score = difflib.SequenceMatcher(None, display_name, full).ratio()
                if surname and surname in display_name:
                    score += 0.2

            image_url = (
                str(item.get("strThumb", "")).strip()
                or str(item.get("strCutout", "")).strip()
                or str(item.get("strRender", "")).strip()
                or str(item.get("strFanart1", "")).strip()
            )
            if not image_url:
                continue

            if score > best_score:
                best_score = score
                best_url = image_url

        if best_url:
            return best_url

    return ""


def _name_signature(value: str) -> Tuple[str, str]:
    parts = [p for p in normalize_name(value).replace(".", " ").split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""

    # Abbreviated format from Flashscore: "Surname I."
    if len(parts[1]) == 1:
        return parts[0], parts[1][0]

    # Full name format: "First Last"
    surname = parts[-1]
    initial = parts[0][0] if parts[0] else ""
    return surname, initial


def _player_name_from_url_slug(player_url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(player_url)
    except Exception:
        return ""
    segments = [urllib.parse.unquote(s) for s in parsed.path.split("/") if s]
    for idx, segment in enumerate(segments):
        if segment != "player":
            continue
        if idx + 1 >= len(segments):
            continue
        slug = segments[idx + 1].strip().lower()
        if not slug:
            continue
        slug = re.sub(r"[^a-z0-9-]", "", slug)
        if not slug:
            continue
        return slug.replace("-", " ").strip()
    return ""


def player_extra_stats(raw_nums: Any) -> Dict[str, str]:
    if not isinstance(raw_nums, list) or len(raw_nums) < 9:
        return {"FG": "", "3P": "", "FT": "", "MIN": "", "PLUS_MINUS": "", "TOV": "", "PF": ""}

    def raw(idx: int) -> str:
        if idx >= len(raw_nums):
            return ""
        return str(raw_nums[idx]).strip()

    def pair(made_idx: int, attempt_idx: int) -> str:
        made = raw(made_idx)
        attempt = raw(attempt_idx)
        if not made or not attempt:
            return ""
        try:
            made_num = float(made.replace(",", "."))
            attempt_num = float(attempt.replace(",", "."))
        except ValueError:
            return ""
        if made_num < 0 or attempt_num < made_num:
            return ""
        return f"{made} / {attempt}"

    return {
        "FG": pair(3, 4),
        "3P": pair(5, 6),
        "FT": pair(7, 8),
        "MIN": "",
        "PLUS_MINUS": raw(9),
        "TOV": raw(len(raw_nums) - 1) if len(raw_nums) >= 12 else "",
        "PF": raw(len(raw_nums) - 2) if len(raw_nums) >= 12 else "",
    }


def download_player_photo(photo_url: str, file_path: str, referer: str = "") -> bool:
    if not photo_url:
        return False
    parsed = urllib.parse.urlparse(photo_url)
    default_referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else "https://www.nba.com/"
    req = urllib.request.Request(
        photo_url,
        headers={
            "Referer": referer or default_referer,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        if len(data) < 1000:
            return False
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(data)
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def clear_player_cache() -> None:
    if not os.path.isdir(PLAYER_CACHE_DIR):
        return
    for entry in os.listdir(PLAYER_CACHE_DIR):
        path = os.path.join(PLAYER_CACHE_DIR, entry)
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass


def detect_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass

    try:
        candidates = socket.gethostbyname_ex(socket.gethostname())[2]
        for ip in candidates:
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass
    return ""


class ManagerApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Broadcast Control Room")
        self.geometry("920x720")
        self.minsize(820, 620)
        self.resizable(True, True)

        self._overlay_httpd: http.server.ThreadingHTTPServer | None = None
        self._overlay_server_thread: threading.Thread | None = None
        self._suspend_player_autopublish = False
        self._take_armed = False
        self._last_preview_payload: Dict[str, Any] = {}

        self._build_ui()
        self._load_config_url()
        self._refresh_embed_links()
        self._load_player_form()
        self._reload_match_players()
        self._bind_hotkeys()
        self._refresh_match()
        self._refresh_scraper_state()
        self._refresh_control_room_state(schedule_next=False)

    def destroy(self) -> None:
        self._stop_overlay_server()
        super().destroy()

    def _remove_maximize_button(self) -> None:
        if sys.platform != "win32":
            return

        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            if not hwnd:
                return

            GWL_STYLE = -16
            WS_MAXIMIZEBOX = 0x00010000
            WS_THICKFRAME = 0x00040000
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            SWP_FRAMECHANGED = 0x0020

            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            style &= ~WS_MAXIMIZEBOX
            style &= ~WS_THICKFRAME
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style)
            ctypes.windll.user32.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
            )
        except Exception:
            pass

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(self, corner_radius=0)
        self.tabs.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")
        for tab_name in ("ЭФИР", "МАТЧ", "ИГРОКИ", "OBS / VMIX", "ДИАГНОСТИКА"):
            self.tabs.add(tab_name)
            self.tabs.tab(tab_name).grid_columnconfigure(0, weight=1)
            self.tabs.tab(tab_name).grid_rowconfigure(0, weight=1)

        self.content = ctk.CTkScrollableFrame(self.tabs.tab("ЭФИР"), width=860, corner_radius=0)
        self.content.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)

        self.match_frame = ctk.CTkFrame(self.content)
        self.match_frame.grid(row=0, column=0, padx=12, pady=(12, 8), sticky="nsew")
        self.match_frame.grid_columnconfigure(0, weight=1)

        self.match_title = ctk.CTkLabel(
            self.match_frame,
            text="ТЕКУЩИЙ МАТЧ",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.match_title.grid(row=0, column=0, padx=12, pady=(10, 8), sticky="w")

        self.score_label = ctk.CTkLabel(
            self.match_frame,
            text="--- 0 — 0 ---",
            font=ctk.CTkFont(size=30, weight="bold"),
        )
        self.score_label.grid(row=1, column=0, padx=12, pady=(2, 8), sticky="ew")

        self.status_badge = ctk.CTkLabel(
            self.match_frame,
            text="● НЕ НАЧАТ",
            corner_radius=8,
            fg_color="#856404",
            text_color="#fff3cd",
            font=ctk.CTkFont(size=14, weight="bold"),
            padx=10,
            pady=4,
        )
        self.status_badge.grid(row=2, column=0, padx=12, pady=(0, 10), sticky="w")

        self.quarter_table = ctk.CTkFrame(self.match_frame)
        self.quarter_table.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="ew")
        self.quarter_table.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        headers = ["", "Q1", "Q2", "Q3", "Q4"]
        for i, h in enumerate(headers):
            ctk.CTkLabel(
                self.quarter_table,
                text=h,
                font=ctk.CTkFont(size=13, weight="bold"),
            ).grid(row=0, column=i, padx=4, pady=(8, 4), sticky="nsew")

        self.home_row_labels: List[ctk.CTkLabel] = []
        self.away_row_labels: List[ctk.CTkLabel] = []

        for col in range(5):
            home_label = ctk.CTkLabel(self.quarter_table, text="-")
            home_label.grid(row=1, column=col, padx=4, pady=4, sticky="nsew")
            self.home_row_labels.append(home_label)

            away_label = ctk.CTkLabel(self.quarter_table, text="-")
            away_label.grid(row=2, column=col, padx=4, pady=(4, 8), sticky="nsew")
            self.away_row_labels.append(away_label)

        self.control_frame = ctk.CTkFrame(self.content)
        self.control_frame.grid(row=1, column=0, padx=12, pady=8, sticky="nsew")
        self.control_frame.grid_columnconfigure((0, 1), weight=1)

        self.control_title = ctk.CTkLabel(
            self.control_frame,
            text="УПРАВЛЕНИЕ СКРАПЕРОМ",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.control_title.grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 8), sticky="w")

        self.scraper_state_label = ctk.CTkLabel(
            self.control_frame,
            text="● Остановлен",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#ff5a5a",
        )
        self.scraper_state_label.grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 10), sticky="w")

        self.start_btn = ctk.CTkButton(
            self.control_frame,
            text="▶ Запустить",
            command=self._start_scraper,
        )
        self.start_btn.grid(row=2, column=0, padx=(12, 6), pady=(0, 12), sticky="ew")

        self.stop_btn = ctk.CTkButton(
            self.control_frame,
            text="■ Остановить",
            command=self._stop_scraper,
            fg_color="#AA2E25",
            hover_color="#8C251D",
        )
        self.stop_btn.grid(row=2, column=1, padx=(6, 12), pady=(0, 12), sticky="ew")

        self.embed_frame = ctk.CTkFrame(self.content)
        self.embed_frame.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="nsew")
        self.embed_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.embed_title = ctk.CTkLabel(
            self.embed_frame,
            text="ССЫЛКИ ДЛЯ СТРИМА",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.embed_title.grid(row=0, column=0, columnspan=3, padx=12, pady=(10, 8), sticky="w")

        self.embed_local_lbl = ctk.CTkLabel(self.embed_frame, text="Статистика: Localhost", text_color="#9ba3af")
        self.embed_local_lbl.grid(row=1, column=0, padx=12, pady=(0, 4), sticky="w")

        self.embed_local_value = ctk.CTkEntry(self.embed_frame)
        self.embed_local_value.grid(row=2, column=0, columnspan=2, padx=(12, 6), pady=(0, 8), sticky="ew")

        self.embed_local_copy_btn = ctk.CTkButton(
            self.embed_frame,
            text="Копировать",
            width=100,
            command=lambda: self._copy_embed_url(lan=False),
        )
        self.embed_local_copy_btn.grid(row=2, column=2, padx=(6, 12), pady=(0, 8), sticky="e")

        self.embed_lan_lbl = ctk.CTkLabel(self.embed_frame, text="Статистика: LAN (для другой машины)", text_color="#9ba3af")
        self.embed_lan_lbl.grid(row=3, column=0, padx=12, pady=(0, 4), sticky="w")

        self.embed_lan_value = ctk.CTkEntry(self.embed_frame)
        self.embed_lan_value.grid(row=4, column=0, columnspan=2, padx=(12, 6), pady=(0, 8), sticky="ew")

        self.embed_lan_copy_btn = ctk.CTkButton(
            self.embed_frame,
            text="Копировать",
            width=100,
            command=lambda: self._copy_embed_url(lan=True),
        )
        self.embed_lan_copy_btn.grid(row=4, column=2, padx=(6, 12), pady=(0, 8), sticky="e")

        self.embed_player_local_lbl = ctk.CTkLabel(
            self.embed_frame,
            text="Карточка игрока: Localhost",
            text_color="#9ba3af",
        )
        self.embed_player_local_lbl.grid(row=5, column=0, padx=12, pady=(0, 4), sticky="w")

        self.embed_player_local_value = ctk.CTkEntry(self.embed_frame)
        self.embed_player_local_value.grid(row=6, column=0, columnspan=2, padx=(12, 6), pady=(0, 8), sticky="ew")

        self.embed_player_local_copy_btn = ctk.CTkButton(
            self.embed_frame,
            text="Копировать",
            width=100,
            command=lambda: self._copy_embed_url(lan=False, player=True),
        )
        self.embed_player_local_copy_btn.grid(row=6, column=2, padx=(6, 12), pady=(0, 8), sticky="e")

        self.embed_player_lan_lbl = ctk.CTkLabel(
            self.embed_frame,
            text="Карточка игрока: LAN (для другой машины)",
            text_color="#9ba3af",
        )
        self.embed_player_lan_lbl.grid(row=7, column=0, padx=12, pady=(0, 4), sticky="w")

        self.embed_player_lan_value = ctk.CTkEntry(self.embed_frame)
        self.embed_player_lan_value.grid(row=8, column=0, columnspan=2, padx=(12, 6), pady=(0, 8), sticky="ew")

        self.embed_player_lan_copy_btn = ctk.CTkButton(
            self.embed_frame,
            text="Копировать",
            width=100,
            command=lambda: self._copy_embed_url(lan=True, player=True),
        )
        self.embed_player_lan_copy_btn.grid(row=8, column=2, padx=(6, 12), pady=(0, 8), sticky="e")

        self.embed_player_full_local_lbl = ctk.CTkLabel(
            self.embed_frame,
            text="Большая карточка игрока: Localhost",
            text_color="#9ba3af",
        )
        self.embed_player_full_local_lbl.grid(row=9, column=0, padx=12, pady=(0, 4), sticky="w")

        self.embed_player_full_local_value = ctk.CTkEntry(self.embed_frame)
        self.embed_player_full_local_value.grid(row=10, column=0, columnspan=2, padx=(12, 6), pady=(0, 8), sticky="ew")

        self.embed_player_full_local_copy_btn = ctk.CTkButton(
            self.embed_frame,
            text="Копировать",
            width=100,
            command=lambda: self._copy_embed_url(lan=False, player_full=True),
        )
        self.embed_player_full_local_copy_btn.grid(row=10, column=2, padx=(6, 12), pady=(0, 8), sticky="e")

        self.embed_player_full_lan_lbl = ctk.CTkLabel(
            self.embed_frame,
            text="Большая карточка игрока: LAN (для другой машины)",
            text_color="#9ba3af",
        )
        self.embed_player_full_lan_lbl.grid(row=11, column=0, padx=12, pady=(0, 4), sticky="w")

        self.embed_player_full_lan_value = ctk.CTkEntry(self.embed_frame)
        self.embed_player_full_lan_value.grid(row=12, column=0, columnspan=2, padx=(12, 6), pady=(0, 8), sticky="ew")

        self.embed_player_full_lan_copy_btn = ctk.CTkButton(
            self.embed_frame,
            text="Копировать",
            width=100,
            command=lambda: self._copy_embed_url(lan=True, player_full=True),
        )
        self.embed_player_full_lan_copy_btn.grid(row=12, column=2, padx=(6, 12), pady=(0, 8), sticky="e")

        self.embed_open_local_btn = ctk.CTkButton(
            self.embed_frame,
            text="Открыть Local",
            command=lambda: self._open_embed_url(lan=False, player=False),
            fg_color="#41464b",
            hover_color="#33373b",
        )
        self.embed_open_local_btn.grid(row=13, column=0, padx=(12, 6), pady=(0, 8), sticky="ew")

        self.embed_open_lan_btn = ctk.CTkButton(
            self.embed_frame,
            text="Открыть LAN",
            command=lambda: self._open_embed_url(lan=True, player=False),
            fg_color="#41464b",
            hover_color="#33373b",
        )
        self.embed_open_lan_btn.grid(row=13, column=1, padx=6, pady=(0, 8), sticky="ew")

        self.embed_open_player_btn = ctk.CTkButton(
            self.embed_frame,
            text="Открыть плашку",
            command=lambda: self._open_embed_url(lan=False, player=True),
            fg_color="#41464b",
            hover_color="#33373b",
        )
        self.embed_open_player_btn.grid(row=13, column=2, padx=(6, 12), pady=(0, 8), sticky="ew")

        self.embed_open_player_full_btn = ctk.CTkButton(
            self.embed_frame,
            text="Открыть большую карточку",
            command=lambda: self._open_embed_url(lan=False, player_full=True),
            fg_color="#41464b",
            hover_color="#33373b",
        )
        self.embed_open_player_full_btn.grid(row=14, column=0, columnspan=3, padx=12, pady=(0, 8), sticky="ew")

        self.player_jump_btn = ctk.CTkButton(
            self.embed_frame,
            text="Перейти к карточке игрока ↓",
            command=self._scroll_to_player_card,
        )
        self.player_jump_btn.grid(row=15, column=0, columnspan=3, padx=12, pady=(0, 8), sticky="ew")

        self.embed_status = ctk.CTkLabel(
            self.embed_frame,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#9ba3af",
        )
        self.embed_status.grid(row=16, column=0, columnspan=3, padx=12, pady=(0, 4), sticky="w")

        self.embed_lan_status = ctk.CTkLabel(
            self.embed_frame,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#9ba3af",
        )
        self.embed_lan_status.grid(row=17, column=0, columnspan=3, padx=12, pady=(0, 10), sticky="w")

        self.change_frame = ctk.CTkFrame(self.content)
        self.change_frame.grid(row=3, column=0, padx=12, pady=(8, 12), sticky="nsew")
        self.change_frame.grid_columnconfigure(0, weight=1)
        self.change_frame.grid_columnconfigure(1, weight=0)

        self.change_title = ctk.CTkLabel(
            self.change_frame,
            text="СМЕНА МАТЧА",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.change_title.grid(row=0, column=0, padx=12, pady=(10, 8), sticky="w")

        self.url_entry = ctk.CTkEntry(
            self.change_frame,
            placeholder_text="Вставьте URL матча Flashscore",
        )
        self.url_entry.grid(row=1, column=0, padx=(12, 6), pady=(0, 8), sticky="ew")
        self.url_entry.bind("<Button-1>", self._focus_url_entry)

        self.paste_btn = ctk.CTkButton(
            self.change_frame,
            text="Вставить",
            width=92,
            command=self._paste_url_from_clipboard,
        )
        self.paste_btn.grid(row=1, column=1, padx=(6, 12), pady=(0, 8), sticky="e")

        self.apply_btn = ctk.CTkButton(
            self.change_frame,
            text="Применить",
            command=self._apply_match_url,
        )
        self.apply_btn.grid(row=2, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew")

        self.apply_status = ctk.CTkLabel(
            self.change_frame,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#9ba3af",
        )
        self.apply_status.grid(row=3, column=0, columnspan=2, padx=12, pady=(0, 10), sticky="w")

        self.player_frame = ctk.CTkFrame(self.content)
        self.player_frame.grid(row=4, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self.player_frame.grid_columnconfigure((0, 1), weight=1)

        self.player_title = ctk.CTkLabel(
            self.player_frame,
            text="КАРТОЧКА ИГРОКА",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.player_title.grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 8), sticky="w")

        self.player_pick_var = tk.StringVar(value="Список игроков пуст")
        self.player_pick_values: List[str] = ["Список игроков пуст"]
        self.player_pick_map: Dict[str, Dict[str, Any]] = {}

        self.player_pick_menu = ctk.CTkOptionMenu(
            self.player_frame,
            variable=self.player_pick_var,
            values=self.player_pick_values,
            command=self._on_player_selected,
        )
        self.player_pick_menu.grid(row=1, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew")

        self.player_pick_buttons = ctk.CTkFrame(self.player_frame, fg_color="transparent")
        self.player_pick_buttons.grid(row=2, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew")
        self.player_pick_buttons.grid_columnconfigure((0, 1), weight=1)

        self.player_reload_btn = ctk.CTkButton(
            self.player_pick_buttons,
            text="Обновить список игроков",
            command=self._reload_match_players,
        )
        self.player_reload_btn.grid(row=0, column=0, padx=(0, 6), pady=0, sticky="ew")

        self.player_air_btn = ctk.CTkButton(
            self.player_pick_buttons,
            text="Preview выбранного",
            command=self._preview_selected_player,
            fg_color="#41464b",
            hover_color="#33373b",
        )
        self.player_air_btn.grid(row=0, column=1, padx=(6, 0), pady=0, sticky="ew")

        self.player_name_entry = ctk.CTkEntry(self.player_frame, placeholder_text="Имя игрока")
        self.player_name_entry.grid(row=3, column=0, padx=(12, 6), pady=(0, 8), sticky="ew")

        self.player_team_entry = ctk.CTkEntry(self.player_frame, placeholder_text="Команда")
        self.player_team_entry.grid(row=3, column=1, padx=(6, 12), pady=(0, 8), sticky="ew")

        self.player_number_entry = ctk.CTkEntry(self.player_frame, placeholder_text="Номер")
        self.player_number_entry.grid(row=4, column=0, padx=(12, 6), pady=(0, 8), sticky="ew")

        self.player_position_entry = ctk.CTkEntry(self.player_frame, placeholder_text="Позиция")
        self.player_position_entry.grid(row=4, column=1, padx=(6, 12), pady=(0, 8), sticky="ew")

        self.player_photo_entry = ctk.CTkEntry(self.player_frame, placeholder_text="Фото URL или локальный путь")
        self.player_photo_entry.grid(row=5, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew")

        self.player_stats_frame = ctk.CTkFrame(self.player_frame, fg_color="transparent")
        self.player_stats_frame.grid(row=6, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew")
        self.player_stats_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        self.ppg_entry = ctk.CTkEntry(self.player_stats_frame, placeholder_text="PPG")
        self.ppg_entry.grid(row=0, column=0, padx=(0, 6), pady=0, sticky="ew")
        self.rpg_entry = ctk.CTkEntry(self.player_stats_frame, placeholder_text="RPG")
        self.rpg_entry.grid(row=0, column=1, padx=3, pady=0, sticky="ew")
        self.apg_entry = ctk.CTkEntry(self.player_stats_frame, placeholder_text="APG")
        self.apg_entry.grid(row=0, column=2, padx=3, pady=0, sticky="ew")
        self.stl_entry = ctk.CTkEntry(self.player_stats_frame, placeholder_text="STL")
        self.stl_entry.grid(row=0, column=3, padx=3, pady=0, sticky="ew")
        self.blk_entry = ctk.CTkEntry(self.player_stats_frame, placeholder_text="BLK")
        self.blk_entry.grid(row=0, column=4, padx=(6, 0), pady=0, sticky="ew")

        self.player_btns_frame = ctk.CTkFrame(self.player_frame, fg_color="transparent")
        self.player_btns_frame.grid(row=7, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew")
        self.player_btns_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.player_show_btn = ctk.CTkButton(
            self.player_btns_frame,
            text="Preview",
            command=self._preview_player_card,
        )
        self.player_show_btn.grid(row=0, column=0, padx=(0, 4), pady=0, sticky="ew")

        self.player_arm_btn = ctk.CTkButton(
            self.player_btns_frame,
            text="Arm Take",
            command=self._arm_preview,
            fg_color="#856404",
            hover_color="#6b5203",
        )
        self.player_arm_btn.grid(row=0, column=1, padx=4, pady=0, sticky="ew")

        self.player_take_btn = ctk.CTkButton(
            self.player_btns_frame,
            text="HOLD TO TAKE",
            command=self._take_preview_to_air,
            fg_color="#0f5132",
            hover_color="#0b3d26",
        )
        self.player_take_btn.grid(row=0, column=2, padx=4, pady=0, sticky="ew")

        self.player_hide_btn = ctk.CTkButton(
            self.player_btns_frame,
            text="Hide",
            command=self._hide_player_card,
            fg_color="#41464b",
            hover_color="#33373b",
        )
        self.player_hide_btn.grid(row=0, column=3, padx=(4, 0), pady=0, sticky="ew")

        self.player_reset_btn = ctk.CTkButton(
            self.player_frame,
            text="Сброс",
            command=self._reset_player_card,
            fg_color="#AA2E25",
            hover_color="#8C251D",
        )
        self.player_reset_btn.grid(row=8, column=0, padx=(12, 6), pady=(0, 8), sticky="ew")

        self.emergency_hide_btn = ctk.CTkButton(
            self.player_frame,
            text="EMERGENCY HIDE ALL",
            command=self._emergency_hide_all,
            fg_color="#B42318",
            hover_color="#8F1D14",
        )
        self.emergency_hide_btn.grid(row=8, column=1, padx=(6, 12), pady=(0, 8), sticky="ew")

        self.player_find_photo_btn = ctk.CTkButton(
            self.player_frame,
            text="Найти NBA фото",
            command=self._auto_find_nba_photo,
        )
        self.player_find_photo_btn.grid(row=9, column=0, columnspan=2, padx=12, pady=(0, 8), sticky="ew")

        self.player_status = ctk.CTkLabel(
            self.player_frame,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#9ba3af",
        )
        self.player_status.grid(row=10, column=0, columnspan=2, padx=12, pady=(0, 10), sticky="w")

        self._build_secondary_tabs()

    def _build_secondary_tabs(self) -> None:
        self._build_match_tab()
        self._build_players_tab()
        self._build_obs_tab()
        self._build_diagnostics_tab()

    def _simple_tab_panel(self, tab_name: str, title: str) -> ctk.CTkFrame:
        panel = ctk.CTkFrame(self.tabs.tab(tab_name))
        panel.grid(row=0, column=0, padx=16, pady=16, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(panel, text=title, font=ctk.CTkFont(size=20, weight="bold")).grid(
            row=0, column=0, padx=16, pady=(16, 10), sticky="w"
        )
        return panel

    def _build_match_tab(self) -> None:
        panel = self._simple_tab_panel("МАТЧ", "Матч и источник данных")
        ctk.CTkLabel(
            panel,
            text="Проверьте URL матча перед переключением эфира. Смена матча требует подтверждения.",
            text_color="#9ba3af",
        ).grid(row=1, column=0, padx=16, pady=(0, 12), sticky="w")
        self.match_tab_status = ctk.CTkLabel(panel, text="", text_color="#9ba3af")
        self.match_tab_status.grid(row=2, column=0, padx=16, pady=(0, 12), sticky="w")
        ctk.CTkButton(panel, text="Перейти к смене матча в ЭФИР", command=lambda: self.tabs.set("ЭФИР")).grid(
            row=3, column=0, padx=16, pady=(0, 8), sticky="ew"
        )

    def _build_players_tab(self) -> None:
        panel = self._simple_tab_panel("ИГРОКИ", "Игроки: Preview -> Take to Air")
        ctk.CTkLabel(
            panel,
            text="Выбор игрока теперь безопасен: он заполняет PREVIEW и не меняет эфир до Hold to Take.",
            text_color="#9ba3af",
        ).grid(row=1, column=0, padx=16, pady=(0, 12), sticky="w")
        self.players_tab_preview = ctk.CTkLabel(panel, text="PREVIEW: пусто", text_color="#ffd166")
        self.players_tab_preview.grid(row=2, column=0, padx=16, pady=(0, 8), sticky="w")
        self.players_tab_live = ctk.CTkLabel(panel, text="LIVE: пусто", text_color="#66e08a")
        self.players_tab_live.grid(row=3, column=0, padx=16, pady=(0, 12), sticky="w")
        ctk.CTkButton(panel, text="Открыть карточку игрока", command=self._scroll_to_player_card).grid(
            row=4, column=0, padx=16, pady=(0, 8), sticky="ew"
        )

    def _build_obs_tab(self) -> None:
        panel = self._simple_tab_panel("OBS / VMIX", "OBS / vMix ссылки")
        self.obs_tab_status = ctk.CTkLabel(panel, text="Сервер не проверен", text_color="#9ba3af")
        self.obs_tab_status.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="w")
        ctk.CTkButton(panel, text="Запустить / проверить локальный сервер", command=self._ensure_server_from_tab).grid(
            row=2, column=0, padx=16, pady=(0, 8), sticky="ew"
        )
        ctk.CTkButton(panel, text="Скопировать ссылку табло", command=lambda: self._copy_embed_url(lan=False)).grid(
            row=3, column=0, padx=16, pady=(0, 8), sticky="ew"
        )
        ctk.CTkButton(panel, text="Скопировать LAN ссылку табло", command=lambda: self._copy_embed_url(lan=True)).grid(
            row=4, column=0, padx=16, pady=(0, 8), sticky="ew"
        )

    def _build_diagnostics_tab(self) -> None:
        panel = self._simple_tab_panel("ДИАГНОСТИКА", "Диагностика")
        self.diagnostics_text = ctk.CTkTextbox(panel, height=360)
        self.diagnostics_text.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="nsew")
        panel.grid_rowconfigure(1, weight=1)
        ctk.CTkButton(panel, text="Run Self-Test", command=self._run_self_check).grid(
            row=2, column=0, padx=16, pady=(0, 8), sticky="ew"
        )

    def _ensure_server_from_tab(self) -> None:
        ok = self._ensure_overlay_server()
        lan_ip = detect_lan_ip()
        if ok:
            self.obs_tab_status.configure(
                text=f"Сервер готов: localhost:{self._stream_port()}  LAN: {lan_ip or 'не найден'}",
                text_color="#66e08a",
            )
        else:
            self.obs_tab_status.configure(text="Сервер недоступен или порт занят", text_color="#ff5a5a")
        self._refresh_embed_links()

    def _run_self_check(self) -> None:
        service = HealthCheckService(APP_PATHS, STATE_STORE, SCRAPER_CONTROLLER)
        checks = service.run(self._stream_port())
        lines = []
        for check in checks:
            marker = "OK" if check.ok else check.severity.upper()
            lines.append(f"{marker:5} {check.name}: {check.detail}")
        text = "\n".join(lines) or "Нет данных диагностики"
        self.diagnostics_text.configure(state="normal")
        self.diagnostics_text.delete("1.0", "end")
        self.diagnostics_text.insert("1.0", text)
        self.diagnostics_text.configure(state="disabled")

    def _refresh_control_room_state(self, schedule_next: bool = True) -> None:
        try:
            preview = STATE_STORE.read("preview_state", GraphicState, max_age_s=300).value
            live = STATE_STORE.read("live_state", GraphicState, max_age_s=300).value
            preview_name = preview.player.name or "пусто"
            live_name = live.player.name if live.phase != "emergency_hidden" else "EMERGENCY HIDDEN"
            if hasattr(self, "players_tab_preview"):
                self.players_tab_preview.configure(text=f"PREVIEW: {preview.phase} · {preview_name}")
            if hasattr(self, "players_tab_live"):
                self.players_tab_live.configure(text=f"LIVE: {live.phase} · {live_name or 'пусто'}")
            if hasattr(self, "match_tab_status"):
                result = read_json(RESULT_PATH)
                home = result.get("home", {}) if isinstance(result.get("home"), dict) else {}
                away = result.get("away", {}) if isinstance(result.get("away"), dict) else {}
                self.match_tab_status.configure(
                    text=f"{home.get('abbr', '---')} {home.get('total', '0')} — {away.get('total', '0')} {away.get('abbr', '---')}"
                )
        finally:
            if schedule_next:
                self.after(5000, self._refresh_control_room_state)

    def _bind_hotkeys(self) -> None:
        self.bind_all("<Control-v>", self._paste_url_event)
        self.bind_all("<Control-V>", self._paste_url_event)
        self.bind_all("<Shift-Insert>", self._paste_url_event)
        self.url_entry.bind("<Control-v>", self._paste_url_event)
        self.url_entry.bind("<Control-V>", self._paste_url_event)
        self.url_entry.bind("<Shift-Insert>", self._paste_url_event)

    def _focus_url_entry(self, _event: Any = None) -> None:
        self.url_entry.focus_set()

    def _stream_port(self) -> int:
        data = read_json(CONFIG_PATH)
        raw = data.get("stream_port", 8081)
        try:
            port = int(raw)
            if 1 <= port <= 65535:
                return port
        except (TypeError, ValueError):
            pass
        return 8081

    def _build_embed_url(self, host: str, page: str = "overlay.html") -> str:
        host = (host or "localhost").strip()
        port = self._stream_port()
        target_page = (page or "overlay.html").strip().lstrip("/")
        return f"http://{host}:{port}/{target_page}"

    def _is_overlay_reachable(self, host: str = "localhost") -> bool:
        url = self._build_embed_url(host)
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return int(getattr(resp, "status", 0)) == 200
        except (urllib.error.URLError, ValueError, OSError):
            return False

    def _start_overlay_server(self) -> bool:
        if self._overlay_httpd is not None:
            return True

        root = CONTENT_ROOT if os.path.isdir(CONTENT_ROOT) else BASE_DIR
        port = self._stream_port()

        class OverlayHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, directory=root, **kwargs)

            def end_headers(self) -> None:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-cache, no-store")
                super().end_headers()

            def log_message(self, _format: str, *_args: Any) -> None:
                return

        try:
            server = http.server.ThreadingHTTPServer(("0.0.0.0", port), OverlayHandler)
        except OSError:
            return False

        self._overlay_httpd = server
        self._overlay_server_thread = threading.Thread(
            target=server.serve_forever,
            name="overlay-http-server",
            daemon=True,
        )
        self._overlay_server_thread.start()
        return True

    def _stop_overlay_server(self) -> None:
        if self._overlay_httpd is None:
            return
        try:
            self._overlay_httpd.shutdown()
            self._overlay_httpd.server_close()
        except OSError:
            pass
        self._overlay_httpd = None
        self._overlay_server_thread = None

    def _ensure_overlay_server(self) -> bool:
        if self._is_overlay_reachable("localhost"):
            return True
        if not self._start_overlay_server():
            return self._is_overlay_reachable("localhost")
        return self._is_overlay_reachable("localhost")

    def _refresh_embed_links(self) -> None:
        local_url = self._build_embed_url("localhost", "overlay.html")
        player_local_url = self._build_embed_url("localhost", "player.html")
        player_full_local_url = self._build_embed_url("localhost", "player-full.html")
        lan_ip = detect_lan_ip()
        lan_url = self._build_embed_url(lan_ip, "overlay.html") if lan_ip else ""
        player_lan_url = self._build_embed_url(lan_ip, "player.html") if lan_ip else ""
        player_full_lan_url = self._build_embed_url(lan_ip, "player-full.html") if lan_ip else ""

        self.embed_local_value.configure(state="normal")
        self.embed_local_value.delete(0, "end")
        self.embed_local_value.insert(0, local_url)
        self.embed_local_value.configure(state="readonly")

        self.embed_lan_value.configure(state="normal")
        self.embed_lan_value.delete(0, "end")
        if lan_url:
            self.embed_lan_value.insert(0, lan_url)
            self.embed_lan_status.configure(text=f"LAN: {lan_ip}", text_color="#66e08a")
        else:
            self.embed_lan_value.insert(0, "LAN IP не найден")
            self.embed_lan_status.configure(text="LAN IP не найден", text_color="#ffd166")
        self.embed_lan_value.configure(state="readonly")

        self.embed_player_local_value.configure(state="normal")
        self.embed_player_local_value.delete(0, "end")
        self.embed_player_local_value.insert(0, player_local_url)
        self.embed_player_local_value.configure(state="readonly")

        self.embed_player_lan_value.configure(state="normal")
        self.embed_player_lan_value.delete(0, "end")
        if player_lan_url:
            self.embed_player_lan_value.insert(0, player_lan_url)
        else:
            self.embed_player_lan_value.insert(0, "LAN IP не найден")
        self.embed_player_lan_value.configure(state="readonly")

        self.embed_player_full_local_value.configure(state="normal")
        self.embed_player_full_local_value.delete(0, "end")
        self.embed_player_full_local_value.insert(0, player_full_local_url)
        self.embed_player_full_local_value.configure(state="readonly")

        self.embed_player_full_lan_value.configure(state="normal")
        self.embed_player_full_lan_value.delete(0, "end")
        if player_full_lan_url:
            self.embed_player_full_lan_value.insert(0, player_full_lan_url)
        else:
            self.embed_player_full_lan_value.insert(0, "LAN IP не найден")
        self.embed_player_full_lan_value.configure(state="readonly")

    def _copy_embed_url(self, lan: bool = False, player: bool = False, player_full: bool = False) -> None:
        if not self._ensure_overlay_server():
            self.embed_status.configure(text="Не удалось запустить локальный сервер", text_color="#ff5a5a")
            return
        if player_full:
            url = (
                self.embed_player_full_lan_value.get().strip()
                if lan else self.embed_player_full_local_value.get().strip()
            )
        elif player:
            url = self.embed_player_lan_value.get().strip() if lan else self.embed_player_local_value.get().strip()
        else:
            url = self.embed_lan_value.get().strip() if lan else self.embed_local_value.get().strip()
        if not url or "не найден" in url.lower():
            self.embed_status.configure(text="Ссылка недоступна", text_color="#ffd166")
            return
        self.clipboard_clear()
        self.clipboard_append(url)
        self.update()
        if player_full:
            scope = "большой карточки"
        elif player:
            scope = "плашки игрока"
        else:
            scope = "статистики"
        label = "LAN" if lan else "localhost"
        self.embed_status.configure(text=f"Ссылка {scope} ({label}) скопирована", text_color="#66e08a")

    def _open_embed_url(self, lan: bool = False, player: bool = False, player_full: bool = False) -> None:
        if player_full:
            url = (
                self.embed_player_full_lan_value.get().strip()
                if lan else self.embed_player_full_local_value.get().strip()
            )
        elif player:
            url = self.embed_player_lan_value.get().strip() if lan else self.embed_player_local_value.get().strip()
        else:
            url = self.embed_lan_value.get().strip() if lan else self.embed_local_value.get().strip()
        if not url or "не найден" in url.lower():
            self.embed_status.configure(text="Ссылка недоступна", text_color="#ffd166")
            return

        if not self._ensure_overlay_server():
            self.embed_status.configure(text="Не удалось запустить локальный сервер", text_color="#ff5a5a")
            return

        webbrowser.open(url)
        self.embed_status.configure(text="Открыто в браузере", text_color="#9ba3af")

    def _scroll_to_player_card(self) -> None:
        canvas = getattr(self.content, "_parent_canvas", None)
        if canvas is not None:
            canvas.yview_moveto(1.0)
        self.player_name_entry.focus_set()

    def _paste_url_event(self, _event: Any = None) -> str:
        self._paste_url_from_clipboard()
        return "break"

    def _paste_url_from_clipboard(self) -> None:
        try:
            value = self.clipboard_get().strip()
        except tk.TclError:
            self.apply_status.configure(text="Буфер обмена пуст", text_color="#ffd166")
            return

        if not value:
            self.apply_status.configure(text="Буфер обмена пуст", text_color="#ffd166")
            return

        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, value)
        self.url_entry.focus_set()
        self.apply_status.configure(text="Ссылка вставлена", text_color="#66e08a")

    def _load_config_url(self) -> None:
        data = read_json(CONFIG_PATH)
        urls = data.get("urls", [])
        url = urls[0] if isinstance(urls, list) and urls else ""
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, url)
        self._refresh_embed_links()

    def _safe_value(self, value: Any, default: str = "-") -> str:
        if value is None:
            return default
        text = str(value).strip()
        return text if text else default

    def _update_status_badge(self, status: str, quarter: str) -> None:
        st = (status or "").lower()
        q = self._safe_value(quarter, "")

        if st == "live":
            text = f"● LIVE {q}".strip()
            self.status_badge.configure(text=text, fg_color="#0f5132", text_color="#d1e7dd")
        elif st == "over":
            self.status_badge.configure(text="● ЗАВЕРШЁН", fg_color="#41464b", text_color="#e2e3e5")
        else:
            self.status_badge.configure(text="● НЕ НАЧАТ", fg_color="#856404", text_color="#fff3cd")

    def _refresh_match(self) -> None:
        data = read_json(RESULT_PATH)

        home = data.get("home", {}) if isinstance(data.get("home", {}), dict) else {}
        away = data.get("away", {}) if isinstance(data.get("away", {}), dict) else {}

        home_abbr = self._safe_value(home.get("abbr"), "---")
        away_abbr = self._safe_value(away.get("abbr"), "---")
        home_total = self._safe_value(home.get("total"), "0")
        away_total = self._safe_value(away.get("total"), "0")

        self.score_label.configure(text=f"{home_abbr}  {home_total} — {away_total}  {away_abbr}")

        status = self._safe_value(data.get("status"), "scheduled")
        quarter = self._safe_value(data.get("quarter"), "")
        self._update_status_badge(status, quarter)

        self.home_row_labels[0].configure(text=home_abbr)
        self.away_row_labels[0].configure(text=away_abbr)

        quarter_keys = ["q1", "q2", "q3", "q4"]
        for idx, key in enumerate(quarter_keys, start=1):
            self.home_row_labels[idx].configure(text=self._safe_value(home.get(key)))
            self.away_row_labels[idx].configure(text=self._safe_value(away.get(key)))

        self.after(3000, self._refresh_match)

    def _refresh_scraper_state(self) -> None:
        running = SCRAPER_CONTROLLER.is_running()
        if running:
            self.scraper_state_label.configure(text="● Запущен", text_color="#66e08a")
        else:
            self.scraper_state_label.configure(text="● Остановлен", text_color="#ff5a5a")
        self.after(2000, self._refresh_scraper_state)

    def _start_scraper(self) -> None:
        if SCRAPER_CONTROLLER.is_running():
            self.apply_status.configure(text="Скрапер уже запущен", text_color="#9ba3af")
            return

        if not os.path.exists(MAIN_EXE):
            self.apply_status.configure(text="Не найден main.exe", text_color="#ff5a5a")
            return

        try:
            pid = SCRAPER_CONTROLLER.start()
            self.apply_status.configure(text=f"Скрапер запущен (PID {pid})", text_color="#66e08a")
        except OSError as exc:
            self.apply_status.configure(text=f"Ошибка запуска: {exc}", text_color="#ff5a5a")

    def _stop_scraper(self) -> None:
        if not SCRAPER_CONTROLLER.is_running():
            self.apply_status.configure(text="Скрапер уже остановлен", text_color="#9ba3af")
            return

        if not messagebox.askyesno("Stop scraper", "Остановить скрапер? Данные в эфире останутся последними валидными."):
            return

        SCRAPER_CONTROLLER.stop()
        self.apply_status.configure(text="Скрапер остановлен", text_color="#66e08a")

    def _apply_match_url(self) -> None:
        new_url = self.url_entry.get().strip()
        if not new_url:
            self.apply_status.configure(text="Введите URL матча", text_color="#ff5a5a")
            return

        if not messagebox.askyesno(
            "Switch match",
            "Переключить матч, сбросить устаревшее фото игрока и перезапустить скрапер?",
        ):
            return

        data = read_json(CONFIG_PATH)
        urls = data.get("urls")
        if not isinstance(urls, list):
            urls = []

        if urls:
            urls[0] = new_url
        else:
            urls.append(new_url)

        data["urls"] = urls

        ok, err = write_json(CONFIG_PATH, data, atomic=True)
        if not ok:
            self.apply_status.configure(text=f"Не удалось сохранить config.json: {err}", text_color="#ff5a5a")
            return
        self._refresh_embed_links()

        clear_player_cache()
        player_data = default_player_data()
        player_data["source"] = "manager"
        player_data["photo_status"] = "stale"
        player_data["match_key"] = new_url
        player_data["updated_at"] = now_iso()
        self._write_player_data(player_data)
        self._load_player_form()
        self._reload_match_players()

        if not os.path.exists(MAIN_EXE):
            self.apply_status.configure(text="URL сохранен, но main.exe не найден", text_color="#ffd166")
            return

        try:
            pid = SCRAPER_CONTROLLER.restart()
            self.apply_status.configure(text=f"URL применен, скрапер перезапущен (PID {pid})", text_color="#66e08a")
        except OSError as exc:
            self.apply_status.configure(text=f"URL сохранен, ошибка запуска: {exc}", text_color="#ffd166")

    def _read_player_data(self) -> Dict[str, Any]:
        loaded = read_json(PLAYER_PATH)
        data = default_player_data()
        if not loaded:
            return data

        for key in [
            "schema_version", "visible", "mode", "updated_at", "source", "team_side",
            "match_key", "name", "number", "position", "team", "photo", "photo_source", "photo_status",
        ]:
            if key in loaded:
                data[key] = loaded[key]

        stats = loaded.get("stats", {}) if isinstance(loaded.get("stats"), dict) else {}
        for stat_key in ["PPG", "RPG", "APG", "STL", "BLK", "FG", "3P", "FT", "MIN", "PLUS_MINUS", "TOV", "PF"]:
            if stat_key in stats:
                data["stats"][stat_key] = stats[stat_key]
        return data

    def _write_player_data(self, data: Dict[str, Any]) -> Tuple[bool, str]:
        return write_json(PLAYER_PATH, data, atomic=True)

    def _load_player_form(self) -> None:
        data = self._read_player_data()

        def _set(entry: ctk.CTkEntry, value: Any) -> None:
            entry.delete(0, "end")
            entry.insert(0, str(value or ""))

        _set(self.player_name_entry, data.get("name", ""))
        _set(self.player_team_entry, data.get("team", ""))
        _set(self.player_number_entry, data.get("number", ""))
        _set(self.player_position_entry, data.get("position", ""))
        _set(self.player_photo_entry, data.get("photo", ""))

        stats = data.get("stats", {}) if isinstance(data.get("stats"), dict) else {}
        _set(self.ppg_entry, stats.get("PPG", ""))
        _set(self.rpg_entry, stats.get("RPG", ""))
        _set(self.apg_entry, stats.get("APG", ""))
        _set(self.stl_entry, stats.get("STL", ""))
        _set(self.blk_entry, stats.get("BLK", ""))

    def _team_for_side(self, side: str) -> str:
        result = read_json(RESULT_PATH)
        if side == "home":
            home = result.get("home", {}) if isinstance(result.get("home"), dict) else {}
            return str(home.get("name", "")).strip()
        if side == "away":
            away = result.get("away", {}) if isinstance(result.get("away"), dict) else {}
            return str(away.get("name", "")).strip()
        return ""

    def _fill_player_form_from_candidate(self, candidate: Dict[str, Any]) -> None:
        name = str(candidate.get("name", "")).strip()
        side = str(candidate.get("side", "")).strip().lower()
        team = self._team_for_side(side)

        self.player_name_entry.delete(0, "end")
        self.player_name_entry.insert(0, name)

        self.player_team_entry.delete(0, "end")
        self.player_team_entry.insert(0, team)

        self.player_photo_entry.delete(0, "end")

        self.ppg_entry.delete(0, "end")
        self.ppg_entry.insert(0, str(candidate.get("pts", "")))
        self.rpg_entry.delete(0, "end")
        self.rpg_entry.insert(0, str(candidate.get("reb", "")))
        self.apg_entry.delete(0, "end")
        self.apg_entry.insert(0, str(candidate.get("ast", "")))
        self.stl_entry.delete(0, "end")
        self.stl_entry.insert(0, str(candidate.get("stl", "")))
        self.blk_entry.delete(0, "end")
        self.blk_entry.insert(0, str(candidate.get("blk", "")))

    def _on_player_selected(self, selected: str) -> None:
        candidate = self.player_pick_map.get(selected)
        if not candidate:
            return
        self._fill_player_form_from_candidate(candidate)
        self._write_player_preview(candidate=candidate)
        if self._suspend_player_autopublish:
            self.player_status.configure(text="Игрок загружен в PREVIEW", text_color="#9ba3af")
            return

        self.player_status.configure(
            text="PREVIEW обновлен. Эфир не изменен. Нажмите Arm Take -> HOLD TO TAKE.",
            text_color="#ffd166",
        )

    def _reload_match_players(self) -> None:
        data = read_json(PLAYER_DEBUG_PATH)
        candidates = data.get("candidates", []) if isinstance(data.get("candidates"), list) else []

        # Prefer candidates that passed strict checks, but keep a fallback list so
        # the operator can still pick a player when source markup changes.
        allowed_candidates = [
            c for c in candidates
            if isinstance(c, dict) and bool(c.get("allowed", False))
        ]
        source_candidates = allowed_candidates or [c for c in candidates if isinstance(c, dict)]

        values: List[str] = []
        mapping: Dict[str, Dict[str, Any]] = {}
        seen: set[str] = set()

        known_side_count = sum(
            str(item.get("side", "")).strip().lower() in ("home", "away")
            for item in source_candidates
        )
        use_only_known_side = known_side_count >= 8

        for item in source_candidates:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            side = str(item.get("side", "")).strip().lower()
            if not name:
                continue
            if side not in ("home", "away") and use_only_known_side:
                continue

            team = self._team_for_side(side)
            key = f"{side}:{name.lower()}"
            if key in seen:
                continue
            seen.add(key)

            pts = item.get("pts", "")
            reb = item.get("reb", "")
            ast = item.get("ast", "")
            side_label = side.upper() if side in ("home", "away") else "UNK"
            label = f"{side_label} | {name} | PTS {pts} REB {reb} AST {ast}"
            values.append(label)
            mapping[label] = {
                "name": name,
                "side": side,
                "team": team,
                "pts": pts,
                "reb": reb,
                "ast": ast,
                "stl": item.get("stl", ""),
                "blk": item.get("blk", ""),
                "player_url": item.get("player_url", ""),
                "photo_url": item.get("photo_url", ""),
                "extra_stats": player_extra_stats(item.get("raw_nums", [])),
            }

        if not values:
            values = ["Список игроков пуст"]
            mapping = {}

        self.player_pick_values = values
        self.player_pick_map = mapping
        self.player_pick_menu.configure(values=values)

        self._suspend_player_autopublish = True
        try:
            self.player_pick_var.set(values[0])
            first = mapping.get(values[0])
            if first:
                self._fill_player_form_from_candidate(first)
        finally:
            self._suspend_player_autopublish = False

        if mapping.get(values[0]):
            self.player_status.configure(text=f"Загружено игроков: {len(mapping)}", text_color="#66e08a")
        else:
            self.player_status.configure(
                text="Нет списка игроков. Дождитесь цикла скрапера и нажмите Обновить.",
                text_color="#ffd166",
            )

    def _selected_candidate(self) -> Dict[str, Any] | None:
        selected = self.player_pick_var.get().strip()
        return self.player_pick_map.get(selected)

    def _preview_selected_player(self) -> None:
        candidate = self._selected_candidate()
        if not candidate:
            self.player_status.configure(text="Выберите игрока из списка", text_color="#ff5a5a")
            return
        self._fill_player_form_from_candidate(candidate)
        self._write_player_preview(candidate=candidate)
        self.player_status.configure(
            text="Игрок подготовлен в PREVIEW. Для эфира: Arm Take -> HOLD TO TAKE.",
            text_color="#ffd166",
        )

    def _preview_player_card(self) -> None:
        data = self._build_player_payload()
        if not data.get("name"):
            self.player_status.configure(text="Укажите имя игрока для PREVIEW", text_color="#ff5a5a")
            return
        self._write_player_preview(payload=data)
        self.player_status.configure(
            text="PREVIEW готов. Эфир не изменен. Нажмите Arm Take.",
            text_color="#ffd166",
        )

    def _write_player_preview(
        self,
        payload: Dict[str, Any] | None = None,
        candidate: Dict[str, Any] | None = None,
    ) -> None:
        if payload is None:
            payload = self._build_player_payload()
        if candidate:
            payload["name"] = str(candidate.get("name", "")).strip()
            payload["team_side"] = str(candidate.get("side", "")).strip().lower()
            payload["team"] = str(candidate.get("team", "")).strip() or self._team_for_side(payload["team_side"])
            payload["stats"] = {
                "PPG": str(candidate.get("pts", "")),
                "RPG": str(candidate.get("reb", "")),
                "APG": str(candidate.get("ast", "")),
                "STL": str(candidate.get("stl", "")),
                "BLK": str(candidate.get("blk", "")),
                **candidate.get("extra_stats", {}),
            }

        payload["visible"] = True
        payload["mode"] = "preview"
        payload["source"] = "manager-preview"
        payload["match_key"] = get_match_key()
        payload["updated_at"] = now_iso()

        state = GraphicState(
            phase="preview_ready",
            selected_layer="player_card",
            armed=False,
            player=PlayerState.model_validate(payload),
            result=read_json(RESULT_PATH),
            message=f"PREVIEW: {payload.get('name', '')}",
        )
        STATE_STORE.write("preview_state", state, update_last_good=False)
        self._take_armed = False
        self._last_preview_payload = payload
        self._refresh_control_room_state(schedule_next=False)

    def _arm_preview(self) -> None:
        snapshot = STATE_STORE.read("preview_state", GraphicState, max_age_s=300)
        player_name = snapshot.value.player.name.strip()
        if not player_name:
            self.player_status.configure(text="Нет подготовленного PREVIEW", text_color="#ff5a5a")
            return
        state = snapshot.value.model_copy(update={"phase": "armed", "armed": True, "message": f"ARMED: {player_name}"})
        STATE_STORE.write("preview_state", state, update_last_good=False)
        self._take_armed = True
        self.player_status.configure(text=f"ARMED: {player_name}. Теперь HOLD TO TAKE.", text_color="#ffd166")
        self._refresh_control_room_state(schedule_next=False)

    def _take_preview_to_air(self) -> None:
        snapshot = STATE_STORE.read("preview_state", GraphicState, max_age_s=300)
        if not (self._take_armed or snapshot.value.armed):
            self.player_status.configure(text="Сначала нажмите Arm Take", text_color="#ff5a5a")
            return
        player = snapshot.value.player.model_dump(by_alias=True)
        if not str(player.get("name", "")).strip():
            self.player_status.configure(text="PREVIEW пуст", text_color="#ff5a5a")
            return
        player["visible"] = True
        player["mode"] = "manual_lock"
        player["source"] = "manager-take"
        player["updated_at"] = now_iso()

        if not player.get("photo"):
            self._try_fill_nba_photo(player)

        ok, err = self._write_player_data(player)
        if not ok:
            self.player_status.configure(text=f"Ошибка TAKE: {err}", text_color="#ff5a5a")
            return

        live_state = GraphicState(
            phase="on_air_synced",
            selected_layer="player_card",
            armed=False,
            player=PlayerState.model_validate(player),
            result=read_json(RESULT_PATH),
            message=f"ON AIR: {player.get('name', '')}",
        )
        STATE_STORE.write("live_state", live_state)
        STATE_STORE.write("last_good_state", live_state)
        self._take_armed = False
        self.player_status.configure(text=f"ON AIR: {player.get('name', '')}", text_color="#66e08a")
        self._refresh_control_room_state(schedule_next=False)

    def _try_fill_nba_photo(self, player: Dict[str, Any]) -> None:
        def try_fill_from_sportsdb() -> bool:
            remote_photo = _fetch_sportsdb_player_photo_url(str(player.get("name", "")))
            if not remote_photo:
                return False

            seed = f"sportsdb:{player.get('name', '')}:{remote_photo}"
            digest = hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()[:12]
            ext = _image_extension_from_url(remote_photo, default=".jpg")
            local_name = f"sdb_{digest}{ext}"
            local_path = os.path.join(PLAYER_CACHE_DIR, local_name)
            local_rel = f"json/players/{local_name}"
            if not download_player_photo(remote_photo, local_path, referer="https://www.thesportsdb.com/"):
                return False

            player["photo"] = local_rel
            player["photo_source"] = "auto:sportsdb"
            player["photo_status"] = "auto_found"
            self.player_photo_entry.delete(0, "end")
            self.player_photo_entry.insert(0, local_rel)
            return True

        match_url = get_match_key()
        result_data = read_json(RESULT_PATH)
        nba_ok, _reason = is_nba_match(match_url, result_data)
        if not nba_ok:
            candidate = find_candidate_for_player_name()
            try_fill_from_candidate(candidate)
            return
        try:
            pid = find_nba_player_id(player.get("name", ""))
        except Exception:
            pid = ""
        if pid:
            local_path = os.path.join(PLAYER_CACHE_DIR, f"{pid}.png")
            local_rel = f"json/players/{pid}.png"
            if download_player_photo(nba_photo_url(pid), local_path, referer="https://www.nba.com/"):
                player["photo"] = local_rel
                player["photo_source"] = "auto:nba"
                player["photo_status"] = "auto_found"
                self.player_photo_entry.delete(0, "end")
                self.player_photo_entry.insert(0, local_rel)
                return

        if try_fill_from_sportsdb():
            return

    def _emergency_hide_all(self) -> None:
        data = self._read_player_data()
        data["visible"] = False
        data["mode"] = "manual_hidden_lock"
        data["source"] = "manager-emergency-hide"
        data["updated_at"] = now_iso()
        ok, err = self._write_player_data(data)
        if not ok:
            self.player_status.configure(text=f"Ошибка EMERGENCY HIDE: {err}", text_color="#ff5a5a")
            return
        state = GraphicState(
            phase="emergency_hidden",
            selected_layer="all",
            armed=False,
            emergency_hidden=True,
            player=PlayerState.model_validate(data),
            result=read_json(RESULT_PATH),
            message="EMERGENCY HIDDEN",
        )
        STATE_STORE.write("live_state", state)
        STATE_STORE.write("last_good_state", state)
        self._take_armed = False
        self.player_status.configure(text="EMERGENCY HIDE ALL выполнен", text_color="#ff5a5a")
        self._refresh_control_room_state()

    def _put_selected_player_on_air(self) -> None:
        selected = self.player_pick_var.get().strip()
        candidate = self.player_pick_map.get(selected)
        if not candidate:
            self.player_status.configure(text="Выберите игрока из списка", text_color="#ff5a5a")
            return

        self._fill_player_form_from_candidate(candidate)
        data = self._build_player_payload()
        data["name"] = str(candidate.get("name", "")).strip()
        data["team_side"] = str(candidate.get("side", "")).strip().lower()
        data["team"] = str(candidate.get("team", "")).strip() or self._team_for_side(data["team_side"])
        data["stats"] = {
            "PPG": str(candidate.get("pts", "")),
            "RPG": str(candidate.get("reb", "")),
            "APG": str(candidate.get("ast", "")),
            "STL": str(candidate.get("stl", "")),
            "BLK": str(candidate.get("blk", "")),
            **candidate.get("extra_stats", {}),
        }
        data["visible"] = True
        data["mode"] = "manual_lock"
        data["source"] = "manager-select"
        data["match_key"] = get_match_key()
        data["updated_at"] = now_iso()

        if not data.get("photo"):
            self._try_fill_nba_photo(data)

        ok, err = self._write_player_data(data)
        if ok:
            self.player_status.configure(text=f"В эфир выведен: {data['name']}", text_color="#66e08a")
        else:
            self.player_status.configure(text=f"Ошибка сохранения: {err}", text_color="#ff5a5a")

    def _build_player_payload(self) -> Dict[str, Any]:
        data = self._read_player_data()
        data["schema_version"] = 2
        data["name"] = self.player_name_entry.get().strip()
        data["team"] = self.player_team_entry.get().strip()
        data["number"] = self.player_number_entry.get().strip()
        data["position"] = self.player_position_entry.get().strip()
        data["photo"] = self.player_photo_entry.get().strip()
        data["source"] = "manager"
        data["updated_at"] = now_iso()
        data["match_key"] = get_match_key()

        stats = data.get("stats", {}) if isinstance(data.get("stats"), dict) else {}
        stats.update({
            "PPG": self.ppg_entry.get().strip(),
            "RPG": self.rpg_entry.get().strip(),
            "APG": self.apg_entry.get().strip(),
            "STL": self.stl_entry.get().strip(),
            "BLK": self.blk_entry.get().strip(),
        })
        data["stats"] = stats

        if data.get("photo"):
            if str(data.get("photo", "")).startswith("json/players/"):
                data["photo_source"] = "auto:nba"
                data["photo_status"] = "auto_found"
            else:
                data["photo_source"] = "manual"
                data["photo_status"] = "manual"
        else:
            data["photo_source"] = ""
            data["photo_status"] = ""

        return data

    def _show_player_card(self) -> None:
        data = self._build_player_payload()
        if not data.get("name"):
            self.player_status.configure(text="Укажите имя игрока", text_color="#ff5a5a")
            return

        if not data.get("photo"):
            self._try_fill_nba_photo(data)

        data["visible"] = True
        data["mode"] = "manual_lock"
        data["source"] = "manager"
        ok, err = self._write_player_data(data)
        if ok:
            self.player_status.configure(text="Карточка игрока показана", text_color="#66e08a")
        else:
            self.player_status.configure(text=f"Ошибка сохранения: {err}", text_color="#ff5a5a")

    def _hide_player_card(self) -> None:
        if not messagebox.askyesno("Hide player graphic", "Скрыть карточку игрока в эфире?"):
            return
        data = self._build_player_payload()
        data["visible"] = False
        data["mode"] = "manual_hidden_lock"
        data["source"] = "manager"
        ok, err = self._write_player_data(data)
        if ok:
            state = GraphicState(
                phase="on_air_synced",
                selected_layer="player_card",
                armed=False,
                player=PlayerState.model_validate(data),
                result=read_json(RESULT_PATH),
                message="Player card hidden",
            )
            STATE_STORE.write("live_state", state)
            self.player_status.configure(text="Карточка игрока скрыта", text_color="#9ba3af")
            self._refresh_control_room_state(schedule_next=False)
        else:
            self.player_status.configure(text=f"Ошибка сохранения: {err}", text_color="#ff5a5a")

    def _reset_player_card(self) -> None:
        if not messagebox.askyesno("Reset player card", "Сбросить карточку игрока и очистить ручную фиксацию?"):
            return
        data = default_player_data()
        data["updated_at"] = now_iso()
        data["match_key"] = get_match_key()
        ok, err = self._write_player_data(data)
        if ok:
            self._load_player_form()
            self.player_status.configure(text="Карточка игрока сброшена", text_color="#9ba3af")
        else:
            self.player_status.configure(text=f"Ошибка сброса: {err}", text_color="#ff5a5a")

    def _auto_find_nba_photo(self) -> None:
        data = self._build_player_payload()
        if not data.get("name"):
            self.player_status.configure(text="Для автопоиска укажите имя игрока", text_color="#ff5a5a")
            return

        match_url = get_match_key()
        result_data = read_json(RESULT_PATH)
        is_nba, reason = is_nba_match(match_url, result_data)
        if not is_nba:
            data["photo_status"] = "auto_missing"
            data["photo_source"] = ""
            ok, err = self._write_player_data(data)
            if ok:
                self.player_status.configure(text=f"Автопоиск отключен: {reason}", text_color="#ffd166")
            else:
                self.player_status.configure(text=f"Ошибка сохранения: {err}", text_color="#ff5a5a")
            return

        self.player_status.configure(text="Ищу фото игрока NBA...", text_color="#9ba3af")
        self.update_idletasks()

        try:
            person_id = find_nba_player_id(data.get("name", ""))
        except Exception as exc:
            self.player_status.configure(text=f"Ошибка поиска NBA: {exc}", text_color="#ff5a5a")
            return

        if not person_id:
            self._try_fill_nba_photo(data)
            if data.get("photo"):
                ok, err = self._write_player_data(data)
                if ok:
                    self.player_status.configure(text="Фото найдено через fallback и сохранено", text_color="#66e08a")
                else:
                    self.player_status.configure(text=f"Ошибка сохранения: {err}", text_color="#ff5a5a")
                return
            data["photo_status"] = "auto_missing"
            data["photo_source"] = ""
            ok, err = self._write_player_data(data)
            if ok:
                self.player_status.configure(text="Игрок NBA не найден", text_color="#ffd166")
            else:
                self.player_status.configure(text=f"Ошибка сохранения: {err}", text_color="#ff5a5a")
            return

        photo_url = nba_photo_url(person_id)
        local_path = os.path.join(PLAYER_CACHE_DIR, f"{person_id}.png")
        local_rel = f"json/players/{person_id}.png"
        if not download_player_photo(photo_url, local_path, referer="https://www.nba.com/"):
            self._try_fill_nba_photo(data)
            if data.get("photo"):
                ok, err = self._write_player_data(data)
                if ok:
                    self.player_status.configure(text="Фото найдено через fallback и сохранено", text_color="#66e08a")
                else:
                    self.player_status.configure(text=f"Ошибка сохранения: {err}", text_color="#ff5a5a")
                return
            data["photo_status"] = "auto_missing"
            ok, err = self._write_player_data(data)
            if ok:
                self.player_status.configure(text="Фото найдено, но загрузить не удалось", text_color="#ffd166")
            else:
                self.player_status.configure(text=f"Ошибка сохранения: {err}", text_color="#ff5a5a")
            return

        data["photo"] = local_rel
        data["photo_source"] = "auto:nba"
        data["photo_status"] = "auto_found"
        data["updated_at"] = now_iso()

        ok, err = self._write_player_data(data)
        if not ok:
            self.player_status.configure(text=f"Ошибка сохранения: {err}", text_color="#ff5a5a")
            return

        self.player_photo_entry.delete(0, "end")
        self.player_photo_entry.insert(0, local_rel)
        self.player_status.configure(text="NBA фото найдено и сохранено", text_color="#66e08a")


def main() -> None:
    app = ManagerApp()
    app.mainloop()


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        checks = HealthCheckService(APP_PATHS, STATE_STORE, SCRAPER_CONTROLLER).run()
        payload = {
            "ok": all(check.ok or check.severity == "warn" for check in checks),
            "checks": [check.__dict__ for check in checks],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        raise SystemExit(0 if payload["ok"] else 1)
    main()
