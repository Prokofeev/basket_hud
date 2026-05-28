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
import time
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

NBA_TEAM_ABBRS = {
    "atlanta hawks": "ATL",
    "boston celtics": "BOS",
    "brooklyn nets": "BKN",
    "charlotte hornets": "CHA",
    "chicago bulls": "CHI",
    "cleveland cavaliers": "CLE",
    "dallas mavericks": "DAL",
    "denver nuggets": "DEN",
    "detroit pistons": "DET",
    "golden state warriors": "GSW",
    "houston rockets": "HOU",
    "indiana pacers": "IND",
    "los angeles clippers": "LAC",
    "la clippers": "LAC",
    "los angeles lakers": "LAL",
    "la lakers": "LAL",
    "memphis grizzlies": "MEM",
    "miami heat": "MIA",
    "milwaukee bucks": "MIL",
    "minnesota timberwolves": "MIN",
    "new orleans pelicans": "NOP",
    "new york knicks": "NYK",
    "oklahoma city thunder": "OKC",
    "orlando magic": "ORL",
    "philadelphia 76ers": "PHI",
    "phoenix suns": "PHX",
    "portland trail blazers": "POR",
    "sacramento kings": "SAC",
    "san antonio spurs": "SAS",
    "toronto raptors": "TOR",
    "utah jazz": "UTA",
    "washington wizards": "WAS",
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


def overlay_screen_value(value: Any) -> str:
    return "player_stats" if str(value or "").strip() == "player_stats" else "team_stats"


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
    "tyrese maxey": "1630178", "maxey": "1630178", "макси": "1630178",
    "joel embiid": "203954", "embiid": "203954", "эмбиид": "203954",
    "jayson tatum": "1628369", "tatum": "1628369", "тейтум": "1628369",
    "jaylen brown": "1627759", "brown": "1627759", "браун": "1627759",
    "paul george": "202331", "george": "202331", "джордж": "202331",
    "derrick white": "1628401", "white": "1628401", "уайт": "1628401",
    "payton pritchard": "1630202", "pritchard": "1630202", "притчард": "1630202",
    "quentin grimes": "1629656", "grimes": "1629656", "граймс": "1629656",
    "sam hauser": "1630573", "hauser": "1630573", "хаузер": "1630573",
    "andre drummond": "203083", "drummond": "203083", "драммонд": "203083",
    "kelly oubre": "203468", "oubre": "203468", "убре": "203468",
    "edgecombe": "1642845",
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


def _extract_players_from_nba_page(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        players = payload.get("players")
        if isinstance(players, list) and any(isinstance(p, dict) and "PERSON_ID" in p for p in players):
            normalized: List[Dict[str, Any]] = []
            for player in players:
                if not isinstance(player, dict):
                    continue
                normalized.append({
                    "firstName": str(player.get("PLAYER_FIRST_NAME", "")).strip(),
                    "lastName": str(player.get("PLAYER_LAST_NAME", "")).strip(),
                    "personId": str(player.get("PERSON_ID", "")).strip(),
                })
            return normalized
        for value in payload.values():
            found = _extract_players_from_nba_page(value)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _extract_players_from_nba_page(item)
            if found:
                return found
    return []


def _fetch_nba_players_page() -> List[Dict[str, Any]]:
    req = urllib.request.Request(
        "https://www.nba.com/players",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except (urllib.error.URLError, OSError, ValueError):
        return []

    match = re.search(
        r"<script[^>]+id=[\"']__NEXT_DATA__[\"'][^>]*>(.*?)</script>",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return []
    try:
        payload = json.loads(html.unescape(match.group(1)))
    except (json.JSONDecodeError, ValueError):
        return []
    return _extract_players_from_nba_page(payload)


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
            players = _fetch_nba_players_page()
            if not players:
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
        self._url_parse_after: str | None = None
        self._refresh_match_after: str | None = None
        self._match_pipeline_active = False
        self._motion_tick = 0
        self._last_result_mtime = 0.0
        self._result_latency_ms = 0
        self._pending_match_url = ""
        self._pending_match_home = ""
        self._pending_match_away = ""
        self._pending_match_started = 0.0
        self._pending_result_mtime = 0.0
        self._hydration_watch_after: str | None = None
        self._pipeline_stages = [
            ("input", "Match detected"),
            ("config", "Config armed"),
            ("fetch", "Fetching game data"),
            ("teams", "Teams / score hydrated"),
            ("players", "Players queued"),
            ("overlay", "Overlay sync"),
        ]
        self._pipeline_status: Dict[str, str] = {key: "idle" for key, _label in self._pipeline_stages}
        self._activity_lines: List[str] = []

        self._build_ui()
        self._load_config_url()
        self._refresh_embed_links()
        self._load_player_form()
        self._reload_match_players()
        self._bind_hotkeys()
        self._refresh_match()
        self._refresh_scraper_state()
        self._refresh_control_room_state(schedule_next=False)
        self._animate_activity()

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

    def _build_legacy_ui(self) -> None:
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
            text="ПОЛУЧЕНИЕ ДАННЫХ",
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

        self.air_state_frame = ctk.CTkFrame(self.content)
        self.air_state_frame.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self.air_state_frame.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(
            self.air_state_frame,
            text="СОСТОЯНИЕ ЭФИРА",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 8), sticky="w")
        self.air_preview_label = ctk.CTkLabel(self.air_state_frame, text="PREVIEW: пусто", text_color="#ffd166")
        self.air_preview_label.grid(row=1, column=0, padx=12, pady=(0, 10), sticky="w")
        self.air_live_label = ctk.CTkLabel(self.air_state_frame, text="LIVE: пусто", text_color="#66e08a")
        self.air_live_label.grid(row=1, column=1, padx=12, pady=(0, 10), sticky="w")

        self.embed_frame = ctk.CTkScrollableFrame(self.tabs.tab("OBS / VMIX"), corner_radius=0)
        self.embed_frame.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")
        self.embed_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.embed_title = ctk.CTkLabel(
            self.embed_frame,
            text="ССЫЛКИ ДЛЯ OBS / VMIX",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.embed_title.grid(row=0, column=0, columnspan=3, padx=12, pady=(10, 8), sticky="w")

        self.embed_local_lbl = ctk.CTkLabel(self.embed_frame, text="Табло: localhost", text_color="#9ba3af")
        self.embed_local_lbl.grid(row=1, column=0, padx=12, pady=(0, 4), sticky="w")

        self.embed_local_value = ctk.CTkEntry(self.embed_frame)
        self.embed_local_value.grid(row=2, column=0, columnspan=2, padx=(12, 6), pady=(0, 8), sticky="ew")

        self.embed_local_copy_btn = ctk.CTkButton(
            self.embed_frame,
            text="Копировать localhost",
            width=100,
            command=lambda: self._copy_embed_url(lan=False),
        )
        self.embed_local_copy_btn.grid(row=2, column=2, padx=(6, 12), pady=(0, 8), sticky="e")

        self.embed_lan_lbl = ctk.CTkLabel(self.embed_frame, text="Табло: LAN", text_color="#9ba3af")
        self.embed_lan_lbl.grid(row=3, column=0, padx=12, pady=(0, 4), sticky="w")

        self.embed_lan_value = ctk.CTkEntry(self.embed_frame)
        self.embed_lan_value.grid(row=4, column=0, columnspan=2, padx=(12, 6), pady=(0, 8), sticky="ew")

        self.embed_lan_copy_btn = ctk.CTkButton(
            self.embed_frame,
            text="Копировать LAN",
            width=100,
            command=lambda: self._copy_embed_url(lan=True),
        )
        self.embed_lan_copy_btn.grid(row=4, column=2, padx=(6, 12), pady=(0, 8), sticky="e")

        self.embed_player_local_lbl = ctk.CTkLabel(
            self.embed_frame,
            text="Плашка игрока: localhost",
            text_color="#9ba3af",
        )
        self.embed_player_local_lbl.grid(row=5, column=0, padx=12, pady=(0, 4), sticky="w")

        self.embed_player_local_value = ctk.CTkEntry(self.embed_frame)
        self.embed_player_local_value.grid(row=6, column=0, columnspan=2, padx=(12, 6), pady=(0, 8), sticky="ew")

        self.embed_player_local_copy_btn = ctk.CTkButton(
            self.embed_frame,
            text="Копировать localhost",
            width=100,
            command=lambda: self._copy_embed_url(lan=False, player=True),
        )
        self.embed_player_local_copy_btn.grid(row=6, column=2, padx=(6, 12), pady=(0, 8), sticky="e")

        self.embed_player_lan_lbl = ctk.CTkLabel(
            self.embed_frame,
            text="Плашка игрока: LAN",
            text_color="#9ba3af",
        )
        self.embed_player_lan_lbl.grid(row=7, column=0, padx=12, pady=(0, 4), sticky="w")

        self.embed_player_lan_value = ctk.CTkEntry(self.embed_frame)
        self.embed_player_lan_value.grid(row=8, column=0, columnspan=2, padx=(12, 6), pady=(0, 8), sticky="ew")

        self.embed_player_lan_copy_btn = ctk.CTkButton(
            self.embed_frame,
            text="Копировать LAN",
            width=100,
            command=lambda: self._copy_embed_url(lan=True, player=True),
        )
        self.embed_player_lan_copy_btn.grid(row=8, column=2, padx=(6, 12), pady=(0, 8), sticky="e")

        self.embed_player_full_local_lbl = ctk.CTkLabel(
            self.embed_frame,
            text="Большая карточка: localhost",
            text_color="#9ba3af",
        )
        self.embed_player_full_local_lbl.grid(row=9, column=0, padx=12, pady=(0, 4), sticky="w")

        self.embed_player_full_local_value = ctk.CTkEntry(self.embed_frame)
        self.embed_player_full_local_value.grid(row=10, column=0, columnspan=2, padx=(12, 6), pady=(0, 8), sticky="ew")

        self.embed_player_full_local_copy_btn = ctk.CTkButton(
            self.embed_frame,
            text="Копировать localhost",
            width=100,
            command=lambda: self._copy_embed_url(lan=False, player_full=True),
        )
        self.embed_player_full_local_copy_btn.grid(row=10, column=2, padx=(6, 12), pady=(0, 8), sticky="e")

        self.embed_player_full_lan_lbl = ctk.CTkLabel(
            self.embed_frame,
            text="Большая карточка: LAN",
            text_color="#9ba3af",
        )
        self.embed_player_full_lan_lbl.grid(row=11, column=0, padx=12, pady=(0, 4), sticky="w")

        self.embed_player_full_lan_value = ctk.CTkEntry(self.embed_frame)
        self.embed_player_full_lan_value.grid(row=12, column=0, columnspan=2, padx=(12, 6), pady=(0, 8), sticky="ew")

        self.embed_player_full_lan_copy_btn = ctk.CTkButton(
            self.embed_frame,
            text="Копировать LAN",
            width=100,
            command=lambda: self._copy_embed_url(lan=True, player_full=True),
        )
        self.embed_player_full_lan_copy_btn.grid(row=12, column=2, padx=(6, 12), pady=(0, 8), sticky="e")

        self.embed_open_local_btn = ctk.CTkButton(
            self.embed_frame,
            text="Открыть табло",
            command=lambda: self._open_embed_url(lan=False, player=False),
            fg_color="#41464b",
            hover_color="#33373b",
        )
        self.embed_open_local_btn.grid(row=13, column=0, padx=(12, 6), pady=(0, 8), sticky="ew")

        self.embed_open_lan_btn = ctk.CTkButton(
            self.embed_frame,
            text="Открыть табло LAN",
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

        self.embed_status = ctk.CTkLabel(
            self.embed_frame,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#9ba3af",
        )
        self.embed_status.grid(row=15, column=0, columnspan=3, padx=12, pady=(0, 4), sticky="w")

        self.embed_lan_status = ctk.CTkLabel(
            self.embed_frame,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#9ba3af",
        )
        self.embed_lan_status.grid(row=16, column=0, columnspan=3, padx=12, pady=(0, 10), sticky="w")

        self.obs_tab_status = ctk.CTkLabel(
            self.embed_frame,
            text="Сервер не проверен",
            font=ctk.CTkFont(size=12),
            text_color="#9ba3af",
        )
        self.obs_tab_status.grid(row=17, column=0, columnspan=3, padx=12, pady=(0, 8), sticky="w")
        ctk.CTkButton(
            self.embed_frame,
            text="Проверить сервер",
            command=self._ensure_server_from_tab,
            fg_color="#41464b",
            hover_color="#33373b",
        ).grid(row=18, column=0, columnspan=3, padx=12, pady=(0, 12), sticky="ew")

        self.change_frame = ctk.CTkFrame(self.tabs.tab("МАТЧ"))
        self.change_frame.grid(row=0, column=0, padx=16, pady=16, sticky="nsew")
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

        self.player_frame = ctk.CTkScrollableFrame(self.tabs.tab("ИГРОКИ"), corner_radius=0)
        self.player_frame.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")
        self.player_frame.grid_columnconfigure((0, 1), weight=1)

        self.player_title = ctk.CTkLabel(
            self.player_frame,
            text="КАРТОЧКА ИГРОКА",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.player_title.grid(row=0, column=0, padx=12, pady=(10, 8), sticky="w")
        self.player_flow_state = ctk.CTkLabel(
            self.player_frame,
            text="PREVIEW: пусто\nLIVE: пусто",
            text_color="#9ba3af",
            justify="right",
        )
        self.player_flow_state.grid(row=0, column=1, padx=12, pady=(10, 8), sticky="e")

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
            text="Подготовить выбранного",
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
            text="Подготовить PREVIEW",
            command=self._preview_player_card,
        )
        self.player_show_btn.grid(row=0, column=0, padx=(0, 4), pady=0, sticky="ew")

        self.player_arm_btn = ctk.CTkButton(
            self.player_btns_frame,
            text="Разрешить вывод",
            command=self._arm_preview,
            fg_color="#856404",
            hover_color="#6b5203",
        )
        self.player_arm_btn.grid(row=0, column=1, padx=4, pady=0, sticky="ew")

        self.player_take_btn = ctk.CTkButton(
            self.player_btns_frame,
            text="Вывести в LIVE",
            command=self._take_preview_to_air,
            fg_color="#0f5132",
            hover_color="#0b3d26",
        )
        self.player_take_btn.grid(row=0, column=2, padx=4, pady=0, sticky="ew")

        self.player_hide_btn = ctk.CTkButton(
            self.player_btns_frame,
            text="Скрыть из эфира",
            command=self._hide_player_card,
            fg_color="#41464b",
            hover_color="#33373b",
        )
        self.player_hide_btn.grid(row=0, column=3, padx=(4, 0), pady=0, sticky="ew")

        self.player_reset_btn = ctk.CTkButton(
            self.player_frame,
            text="Сбросить карточку",
            command=self._reset_player_card,
            fg_color="#AA2E25",
            hover_color="#8C251D",
        )
        self.player_reset_btn.grid(row=8, column=0, padx=(12, 6), pady=(0, 8), sticky="ew")

        self.emergency_hide_btn = ctk.CTkButton(
            self.player_frame,
            text="Срочно скрыть всё",
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

    def _build_ui(self) -> None:
        self._ui = {
            "bg": "#080B10",
            "panel": "#0D1118",
            "panel_2": "#111722",
            "line": "#253044",
            "text": "#F4F7FB",
            "muted": "#8D98AA",
            "cyan": "#21D4FD",
            "blue": "#2F7BFF",
            "lime": "#77F36D",
            "amber": "#FFB84D",
            "red": "#FF3B45",
        }
        self.configure(fg_color=self._ui["bg"])
        self.geometry("1180x760")
        self.minsize(1060, 680)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=148, corner_radius=0, fg_color="#090D14", border_width=1, border_color="#151D2A")
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_rowconfigure(8, weight=1)
        ctk.CTkLabel(
            self.sidebar,
            text="BCR",
            font=ctk.CTkFont(family="Sora", size=24, weight="bold"),
            text_color=self._ui["text"],
        ).grid(row=0, column=0, padx=12, pady=(20, 4), sticky="ew")
        ctk.CTkLabel(
            self.sidebar,
            text="CONTROL ROOM",
            font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
            text_color=self._ui["cyan"],
        ).grid(row=1, column=0, padx=12, pady=(0, 18), sticky="ew")

        self.nav_buttons: Dict[str, ctk.CTkButton] = {}
        nav_items = [
            ("ЭФИР", "Эфир"),
            ("МАТЧ", "Матч"),
            ("ИГРОКИ", "Игроки"),
            ("OBS / VMIX", "OBS / vMix"),
            ("ДИАГНОСТИКА", "Система"),
        ]
        for idx, (tab_name, label) in enumerate(nav_items, start=2):
            btn = ctk.CTkButton(
                self.sidebar,
                text=label,
                height=48,
                corner_radius=12,
                fg_color="transparent",
                hover_color="#152033",
                text_color=self._ui["muted"],
                anchor="w",
                font=ctk.CTkFont(family="Inter", size=13, weight="bold"),
                command=lambda name=tab_name: self._select_control_tab(name),
            )
            btn.grid(row=idx, column=0, padx=12, pady=4, sticky="ew")
            self.nav_buttons[tab_name] = btn

        self.shell = ctk.CTkFrame(self, corner_radius=0, fg_color=self._ui["bg"])
        self.shell.grid(row=0, column=1, sticky="nsew")
        self.shell.grid_columnconfigure(0, weight=1)
        self.shell.grid_rowconfigure(2, weight=1)

        self.topbar = ctk.CTkFrame(self.shell, height=76, corner_radius=0, fg_color="#0B1018", border_width=1, border_color="#182234")
        self.topbar.grid(row=0, column=0, sticky="ew")
        self.topbar.grid_propagate(False)
        self.topbar.grid_columnconfigure(1, weight=1)
        self.live_badge = ctk.CTkLabel(
            self.topbar,
            text="● LIVE OPS",
            fg_color="#2A1017",
            text_color=self._ui["red"],
            corner_radius=999,
            padx=14,
            pady=6,
            font=ctk.CTkFont(family="Inter", size=12, weight="bold"),
        )
        self.live_badge.grid(row=0, column=0, padx=(24, 16), pady=18, sticky="w")
        self.top_game_label = ctk.CTkLabel(
            self.topbar,
            text="Broadcast Control Room / текущая игра не загружена",
            text_color=self._ui["text"],
            font=ctk.CTkFont(family="Sora", size=18, weight="bold"),
        )
        self.top_game_label.grid(row=0, column=1, padx=0, pady=12, sticky="w")
        self.server_state_label = ctk.CTkLabel(
            self.topbar,
            text="SYNC: LOCAL  /  SERVER: STANDBY",
            text_color=self._ui["muted"],
            font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
        )
        self.server_state_label.grid(row=0, column=2, padx=(16, 24), pady=18, sticky="e")

        self._build_status_strip()

        self.tabs = ctk.CTkTabview(self.shell, corner_radius=0, fg_color=self._ui["bg"])
        self.tabs.grid(row=2, column=0, padx=0, pady=0, sticky="nsew")
        for tab_name, _label in nav_items:
            self.tabs.add(tab_name)
            self.tabs.tab(tab_name).configure(fg_color=self._ui["bg"])
            self.tabs.tab(tab_name).grid_columnconfigure(0, weight=1)
            self.tabs.tab(tab_name).grid_rowconfigure(0, weight=1)
        if hasattr(self.tabs, "_segmented_button"):
            self.tabs._segmented_button.grid_forget()

        self._build_live_screen()
        self._build_obs_screen()
        self._build_match_screen()
        self._build_player_screen()
        self._build_secondary_tabs()
        self._select_control_tab("ЭФИР")

    def _control_card(self, parent: Any, fg: str | None = None, border: str | None = None, radius: int = 18) -> ctk.CTkFrame:
        return ctk.CTkFrame(
            parent,
            corner_radius=radius,
            fg_color=fg or self._ui["panel"],
            border_width=1,
            border_color=border or self._ui["line"],
        )

    def _section_title(self, parent: Any, text: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent,
            text=text,
            font=ctk.CTkFont(family="Inter", size=12, weight="bold"),
            text_color=self._ui["cyan"],
        )

    def _status_label(self, parent: Any, text: str, color: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(family="Inter", size=13, weight="bold"), text_color=color)

    def _pill_label(self, parent: Any, text: str, color: str, bg: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent,
            text=text,
            fg_color=bg,
            text_color=color,
            corner_radius=14,
            padx=14,
            pady=10,
            font=ctk.CTkFont(family="Inter", size=12, weight="bold"),
        )

    def _broadcast_button(self, parent: Any, text: str, command: Any, tone: str = "primary") -> ctk.CTkButton:
        palette = {
            "primary": (self._ui["blue"], "#1D63D8"),
            "success": ("#178C4B", "#21B364"),
            "danger": ("#B4232D", "#E33C47"),
            "neutral": ("#202B3C", "#2B3A52"),
            "amber": ("#8A5B16", "#B87820"),
        }
        fg, hover = palette.get(tone, palette["primary"])
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            height=50,
            corner_radius=14,
            fg_color=fg,
            hover_color=hover,
            border_width=1,
            border_color="#3A465C",
            text_color="#FFFFFF",
            font=ctk.CTkFont(family="Inter", size=12, weight="bold"),
        )

    def _control_entry(self, parent: Any, placeholder: str = "") -> ctk.CTkEntry:
        return ctk.CTkEntry(
            parent,
            placeholder_text=placeholder,
            height=44,
            corner_radius=12,
            fg_color="#0A0F17",
            border_color="#263754",
            text_color=self._ui["text"],
            placeholder_text_color=self._ui["muted"],
            font=ctk.CTkFont(family="Inter", size=13),
        )

    def _field_label(self, parent: Any, text: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent,
            text=text,
            text_color=self._ui["muted"],
            font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
        )

    def _build_status_strip(self) -> None:
        self.status_strip = ctk.CTkFrame(self.shell, height=42, corner_radius=0, fg_color="#080C13", border_width=1, border_color="#151F30")
        self.status_strip.grid(row=1, column=0, sticky="ew")
        self.status_strip.grid_propagate(False)
        self.status_strip.grid_columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="status")
        self.status_chips: Dict[str, ctk.CTkLabel] = {}
        for idx, (key, text) in enumerate([
            ("api", "API  -- ms"),
            ("sync", "SYNC  stale"),
            ("overlay", "OVERLAY  standby"),
            ("obs", "OBS  route ready"),
            ("vmix", "VMIX  route ready"),
        ]):
            chip = ctk.CTkLabel(
                self.status_strip,
                text=text,
                fg_color="#0F1622",
                text_color=self._ui["muted"],
                corner_radius=10,
                font=ctk.CTkFont(family="Inter", size=11, weight="bold"),
                padx=10,
                pady=6,
            )
            chip.grid(row=0, column=idx, padx=(16 if idx == 0 else 5, 16 if idx == 4 else 5), pady=7, sticky="ew")
            self.status_chips[key] = chip

    def _select_control_tab(self, tab_name: str) -> None:
        self.tabs.set(tab_name)
        for name, btn in self.nav_buttons.items():
            active = name == tab_name
            btn.configure(
                fg_color="#122643" if active else "transparent",
                text_color=self._ui["cyan"] if active else self._ui["muted"],
                border_width=1 if active else 0,
                border_color="#255FBD" if active else "#090D14",
            )

    def _build_live_screen(self) -> None:
        self.content = ctk.CTkScrollableFrame(
            self.tabs.tab("ЭФИР"),
            corner_radius=0,
            fg_color=self._ui["bg"],
            scrollbar_button_color="#1B2638",
            scrollbar_button_hover_color=self._ui["blue"],
        )
        self.content.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)

        self.match_frame = self._control_card(self.content, "#0B111A", "#20314A", radius=22)
        self.match_frame.grid(row=0, column=0, padx=24, pady=(24, 16), sticky="nsew")
        self.match_frame.grid_columnconfigure(0, weight=1)
        self.match_title = ctk.CTkLabel(
            self.match_frame,
            text="ON-AIR SCOREBOARD",
            font=ctk.CTkFont(family="Inter", size=12, weight="bold"),
            text_color=self._ui["cyan"],
        )
        self.match_title.grid(row=0, column=0, padx=26, pady=(22, 4), sticky="w")
        self.score_label = ctk.CTkLabel(
            self.match_frame,
            text="--- 0 - 0 ---",
            font=ctk.CTkFont(family="Space Grotesk", size=56, weight="bold"),
            text_color=self._ui["text"],
        )
        self.score_label.grid(row=1, column=0, padx=26, pady=(4, 6), sticky="ew")
        self.status_badge = ctk.CTkLabel(
            self.match_frame,
            text="● НЕ НАЧАТ",
            corner_radius=999,
            fg_color="#2E2511",
            text_color=self._ui["amber"],
            font=ctk.CTkFont(family="Inter", size=13, weight="bold"),
            padx=14,
            pady=6,
        )
        self.status_badge.grid(row=2, column=0, padx=26, pady=(0, 18), sticky="w")

        self.overlay_screen_frame = ctk.CTkFrame(self.match_frame, fg_color="transparent")
        self.overlay_screen_frame.grid(row=3, column=0, padx=22, pady=(0, 18), sticky="ew")
        self.overlay_screen_frame.grid_columnconfigure((0, 1), weight=1, uniform="overlay_screen")
        self.team_stats_screen_btn = self._broadcast_button(
            self.overlay_screen_frame,
            "КОМАНДНАЯ СТАТИСТИКА",
            lambda: self._set_overlay_screen("team_stats"),
            "neutral",
        )
        self.team_stats_screen_btn.grid(row=0, column=0, padx=(0, 6), pady=0, sticky="ew")
        self.player_stats_screen_btn = self._broadcast_button(
            self.overlay_screen_frame,
            "ЛИЧНАЯ СТАТИСТИКА",
            lambda: self._set_overlay_screen("player_stats"),
            "amber",
        )
        self.player_stats_screen_btn.grid(row=0, column=1, padx=(6, 0), pady=0, sticky="ew")
        self.overlay_screen_status = self._status_label(
            self.match_frame,
            "Нижний экран: командная статистика",
            self._ui["muted"],
        )
        self.overlay_screen_status.grid(row=4, column=0, padx=26, pady=(0, 18), sticky="w")

        self.quarter_table = ctk.CTkFrame(self.match_frame, fg_color="transparent")
        self.quarter_table.grid(row=5, column=0, padx=22, pady=(0, 24), sticky="ew")
        self.quarter_table.grid_columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="quarters")
        self.home_row_labels = []
        self.away_row_labels = []
        for col, h in enumerate(["TEAM", "Q1", "Q2", "Q3", "Q4"]):
            card = self._control_card(self.quarter_table, "#111A27", "#263754", radius=16)
            card.grid(row=0, column=col, padx=5, pady=0, sticky="nsew")
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=h, font=ctk.CTkFont(family="Inter", size=10, weight="bold"), text_color=self._ui["muted"]).grid(
                row=0, column=0, padx=8, pady=(12, 0), sticky="ew"
            )
            home_label = ctk.CTkLabel(card, text="-", font=ctk.CTkFont(family="Sora", size=22, weight="bold"), text_color=self._ui["text"])
            home_label.grid(row=1, column=0, padx=8, pady=(4, 0), sticky="ew")
            away_label = ctk.CTkLabel(card, text="-", font=ctk.CTkFont(family="Sora", size=18, weight="bold"), text_color="#AAB6C8")
            away_label.grid(row=2, column=0, padx=8, pady=(0, 12), sticky="ew")
            self.home_row_labels.append(home_label)
            self.away_row_labels.append(away_label)

        self.control_frame = self._control_card(self.content)
        self.control_frame.grid(row=1, column=0, padx=24, pady=8, sticky="nsew")
        self.control_frame.grid_columnconfigure((0, 1), weight=1)
        self.control_title = self._section_title(self.control_frame, "DATA INGEST / SCRAPER")
        self.control_title.grid(row=0, column=0, columnspan=2, padx=20, pady=(18, 8), sticky="w")
        self.scraper_state_label = self._status_label(self.control_frame, "● Остановлен", self._ui["red"])
        self.scraper_state_label.grid(row=1, column=0, columnspan=2, padx=20, pady=(0, 14), sticky="w")
        self.start_btn = self._broadcast_button(self.control_frame, "START FEED", self._start_scraper, "success")
        self.start_btn.grid(row=2, column=0, padx=(20, 8), pady=(0, 20), sticky="ew")
        self.stop_btn = self._broadcast_button(self.control_frame, "STOP FEED", self._stop_scraper, "danger")
        self.stop_btn.grid(row=2, column=1, padx=(8, 20), pady=(0, 20), sticky="ew")

        self.air_state_frame = self._control_card(self.content)
        self.air_state_frame.grid(row=2, column=0, padx=24, pady=(8, 24), sticky="nsew")
        self.air_state_frame.grid_columnconfigure((0, 1), weight=1)
        self._section_title(self.air_state_frame, "PROGRAM / PREVIEW BUS").grid(row=0, column=0, columnspan=2, padx=20, pady=(18, 12), sticky="w")
        self.air_preview_label = self._pill_label(self.air_state_frame, "PREVIEW: пусто", self._ui["amber"], "#241B0D")
        self.air_preview_label.grid(row=1, column=0, padx=(20, 8), pady=(0, 20), sticky="ew")
        self.air_live_label = self._pill_label(self.air_state_frame, "LIVE: пусто", self._ui["lime"], "#102414")
        self.air_live_label.grid(row=1, column=1, padx=(8, 20), pady=(0, 20), sticky="ew")

    def _build_obs_screen(self) -> None:
        self.embed_frame = ctk.CTkScrollableFrame(self.tabs.tab("OBS / VMIX"), corner_radius=0, fg_color=self._ui["bg"])
        self.embed_frame.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")
        self.embed_frame.grid_columnconfigure((0, 1), weight=1, uniform="obs")
        self.embed_title = ctk.CTkLabel(
            self.embed_frame,
            text="OBS / VMIX ROUTING",
            font=ctk.CTkFont(family="Sora", size=28, weight="bold"),
            text_color=self._ui["text"],
        )
        self.embed_title.grid(row=0, column=0, columnspan=2, padx=24, pady=(24, 4), sticky="w")
        self.obs_tab_status = self._pill_label(self.embed_frame, "Сервер не проверен", self._ui["muted"], "#111722")
        self.obs_tab_status.grid(row=1, column=0, columnspan=2, padx=24, pady=(0, 16), sticky="ew")

        cards = [
            ("SCOREBOARD", "LOCALHOST", "embed_local_lbl", "embed_local_value", "embed_local_copy_btn", lambda: self._copy_embed_url(lan=False), "neutral"),
            ("SCOREBOARD", "LAN", "embed_lan_lbl", "embed_lan_value", "embed_lan_copy_btn", lambda: self._copy_embed_url(lan=True), "primary"),
            ("PLAYER LOWER", "LOCALHOST", "embed_player_local_lbl", "embed_player_local_value", "embed_player_local_copy_btn", lambda: self._copy_embed_url(lan=False, player=True), "neutral"),
            ("PLAYER LOWER", "LAN", "embed_player_lan_lbl", "embed_player_lan_value", "embed_player_lan_copy_btn", lambda: self._copy_embed_url(lan=True, player=True), "primary"),
            ("PLAYER FULL", "LOCALHOST", "embed_player_full_local_lbl", "embed_player_full_local_value", "embed_player_full_local_copy_btn", lambda: self._copy_embed_url(lan=False, player_full=True), "neutral"),
            ("PLAYER FULL", "LAN", "embed_player_full_lan_lbl", "embed_player_full_lan_value", "embed_player_full_lan_copy_btn", lambda: self._copy_embed_url(lan=True, player_full=True), "primary"),
        ]
        for idx, (title, scope, label_attr, entry_attr, button_attr, command, tone) in enumerate(cards):
            row = 2 + idx // 2
            col = idx % 2
            card = self._control_card(self.embed_frame)
            card.grid(row=row, column=col, padx=(24 if col == 0 else 8, 8 if col == 0 else 24), pady=8, sticky="nsew")
            card.grid_columnconfigure(0, weight=1)
            label = ctk.CTkLabel(
                card,
                text=f"{title} / {scope}",
                font=ctk.CTkFont(family="Inter", size=12, weight="bold"),
                text_color=self._ui["cyan"] if scope == "LAN" else self._ui["muted"],
            )
            label.grid(row=0, column=0, padx=16, pady=(16, 6), sticky="w")
            entry = self._control_entry(card)
            entry.grid(row=1, column=0, padx=16, pady=(0, 10), sticky="ew")
            button = self._broadcast_button(card, "COPY ROUTE", command, tone)
            button.grid(row=2, column=0, padx=16, pady=(0, 16), sticky="ew")
            setattr(self, label_attr, label)
            setattr(self, entry_attr, entry)
            setattr(self, button_attr, button)

        open_card = self._control_card(self.embed_frame, "#0B111A", "#25405E")
        open_card.grid(row=5, column=0, columnspan=2, padx=24, pady=(8, 24), sticky="ew")
        open_card.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.embed_open_local_btn = self._broadcast_button(open_card, "OPEN SCORE", lambda: self._open_embed_url(lan=False, player=False), "neutral")
        self.embed_open_local_btn.grid(row=0, column=0, padx=(16, 6), pady=16, sticky="ew")
        self.embed_open_lan_btn = self._broadcast_button(open_card, "OPEN SCORE LAN", lambda: self._open_embed_url(lan=True, player=False), "neutral")
        self.embed_open_lan_btn.grid(row=0, column=1, padx=6, pady=16, sticky="ew")
        self.embed_open_player_btn = self._broadcast_button(open_card, "OPEN PLAYER", lambda: self._open_embed_url(lan=False, player=True), "neutral")
        self.embed_open_player_btn.grid(row=0, column=2, padx=6, pady=16, sticky="ew")
        self.embed_open_player_full_btn = self._broadcast_button(open_card, "OPEN FULL CARD", lambda: self._open_embed_url(lan=False, player_full=True), "neutral")
        self.embed_open_player_full_btn.grid(row=0, column=3, padx=(6, 16), pady=16, sticky="ew")
        self.embed_status = self._status_label(self.embed_frame, "", self._ui["muted"])
        self.embed_status.grid(row=6, column=0, columnspan=2, padx=24, pady=(0, 4), sticky="w")
        self.embed_lan_status = self._status_label(self.embed_frame, "", self._ui["muted"])
        self.embed_lan_status.grid(row=7, column=0, columnspan=2, padx=24, pady=(0, 12), sticky="w")
        self._broadcast_button(self.embed_frame, "CHECK LOCAL SERVER", self._ensure_server_from_tab, "primary").grid(
            row=8, column=0, columnspan=2, padx=24, pady=(0, 24), sticky="ew"
        )

    def _build_match_screen(self) -> None:
        self.change_frame = self._control_card(self.tabs.tab("МАТЧ"), "#0B111A", "#20314A", radius=22)
        self.change_frame.grid(row=0, column=0, padx=24, pady=24, sticky="new")
        self.change_frame.grid_columnconfigure(0, weight=1)
        self.change_frame.grid_columnconfigure(1, weight=0)
        self.change_title = ctk.CTkLabel(
            self.change_frame,
            text="MATCH SOURCE SWITCHER",
            font=ctk.CTkFont(family="Sora", size=28, weight="bold"),
            text_color=self._ui["text"],
        )
        self.change_title.grid(row=0, column=0, columnspan=2, padx=22, pady=(22, 8), sticky="w")
        ctk.CTkLabel(
            self.change_frame,
            text="Flashscore URL controls the live data feed. Apply restarts ingest and resets stale player assets.",
            text_color=self._ui["muted"],
            font=ctk.CTkFont(family="Inter", size=12),
        ).grid(row=1, column=0, columnspan=2, padx=22, pady=(0, 18), sticky="w")
        self.url_entry = self._control_entry(self.change_frame, "Вставьте URL матча Flashscore")
        self.url_entry.grid(row=2, column=0, padx=(22, 8), pady=(0, 12), sticky="ew")
        self.url_entry.bind("<Button-1>", self._focus_url_entry)
        self.url_entry.bind("<KeyRelease>", self._on_url_changed)
        self.paste_btn = self._broadcast_button(self.change_frame, "PASTE", self._paste_url_from_clipboard, "neutral")
        self.paste_btn.grid(row=2, column=1, padx=(8, 22), pady=(0, 12), sticky="e")
        self.apply_btn = self._broadcast_button(self.change_frame, "ARM NEW MATCH SOURCE", self._apply_match_url, "primary")
        self.apply_btn.grid(row=3, column=0, columnspan=2, padx=22, pady=(0, 12), sticky="ew")
        self.match_detected_label = self._pill_label(self.change_frame, "Waiting for match URL", self._ui["muted"], "#111722")
        self.match_detected_label.grid(row=4, column=0, columnspan=2, padx=22, pady=(0, 10), sticky="ew")

        self.pipeline_frame = ctk.CTkFrame(self.change_frame, fg_color="transparent")
        self.pipeline_frame.grid(row=5, column=0, columnspan=2, padx=22, pady=(0, 12), sticky="ew")
        self.pipeline_frame.grid_columnconfigure(tuple(range(len(self._pipeline_stages))), weight=1, uniform="pipeline")
        self.pipeline_labels: Dict[str, ctk.CTkLabel] = {}
        for idx, (key, label) in enumerate(self._pipeline_stages):
            item = ctk.CTkLabel(
                self.pipeline_frame,
                text=f"○ {label}",
                fg_color="#101825",
                text_color=self._ui["muted"],
                corner_radius=12,
                font=ctk.CTkFont(family="Inter", size=10, weight="bold"),
                padx=8,
                pady=8,
            )
            item.grid(row=0, column=idx, padx=(0 if idx == 0 else 5, 0 if idx == len(self._pipeline_stages) - 1 else 5), pady=0, sticky="ew")
            self.pipeline_labels[key] = item

        self.skeleton_card = self._control_card(self.change_frame, "#090F18", "#223552", radius=18)
        self.skeleton_card.grid(row=6, column=0, columnspan=2, padx=22, pady=(0, 12), sticky="ew")
        self.skeleton_card.grid_columnconfigure((0, 1, 2), weight=1)
        self.skeleton_title = self._section_title(self.skeleton_card, "LIVE PREVIEW HYDRATION")
        self.skeleton_title.grid(row=0, column=0, columnspan=3, padx=16, pady=(14, 8), sticky="w")
        self.preview_home_label = self._pill_label(self.skeleton_card, "HOME\nloading", self._ui["muted"], "#111A27")
        self.preview_home_label.grid(row=1, column=0, padx=(16, 6), pady=(0, 14), sticky="ew")
        self.preview_score_label = ctk.CTkLabel(
            self.skeleton_card,
            text="-- : --",
            fg_color="#101825",
            text_color=self._ui["cyan"],
            corner_radius=14,
            font=ctk.CTkFont(family="Space Grotesk", size=30, weight="bold"),
            padx=10,
            pady=18,
        )
        self.preview_score_label.grid(row=1, column=1, padx=6, pady=(0, 14), sticky="ew")
        self.preview_away_label = self._pill_label(self.skeleton_card, "AWAY\nloading", self._ui["muted"], "#111A27")
        self.preview_away_label.grid(row=1, column=2, padx=(6, 16), pady=(0, 14), sticky="ew")

        self.apply_status = self._status_label(self.change_frame, "", self._ui["muted"])
        self.apply_status.grid(row=7, column=0, columnspan=2, padx=22, pady=(0, 8), sticky="w")
        self.activity_feed = ctk.CTkTextbox(
            self.change_frame,
            height=116,
            corner_radius=14,
            fg_color="#080D14",
            border_width=1,
            border_color="#1D2A3E",
            text_color="#B9C7DA",
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        self.activity_feed.grid(row=8, column=0, columnspan=2, padx=22, pady=(0, 22), sticky="ew")
        self.activity_feed.configure(state="disabled")

    def _build_player_screen(self) -> None:
        self.player_frame = ctk.CTkScrollableFrame(self.tabs.tab("ИГРОКИ"), corner_radius=0, fg_color=self._ui["bg"])
        self.player_frame.grid(row=0, column=0, padx=0, pady=0, sticky="nsew")
        self.player_frame.grid_columnconfigure(0, weight=1)
        self.player_title = ctk.CTkLabel(
            self.player_frame,
            text="Карточка игрока",
            font=ctk.CTkFont(family="Sora", size=28, weight="bold"),
            text_color=self._ui["text"],
        )
        self.player_title.grid(row=0, column=0, padx=24, pady=(24, 4), sticky="w")
        ctk.CTkLabel(
            self.player_frame,
            text="Подготовьте игрока в PREVIEW, проверьте данные и только потом выводите в LIVE.",
            text_color=self._ui["muted"],
            font=ctk.CTkFont(family="Inter", size=13),
        ).grid(row=1, column=0, padx=24, pady=(0, 12), sticky="w")
        self.player_flow_state = self._pill_label(self.player_frame, "PREVIEW: пусто\nLIVE: пусто", self._ui["muted"], "#111722")
        self.player_flow_state.grid(row=0, column=0, padx=24, pady=(24, 4), sticky="e")

        talent_card = self._control_card(self.player_frame, "#0B111A", "#20314A", radius=22)
        talent_card.grid(row=2, column=0, padx=24, pady=(0, 16), sticky="nsew")
        talent_card.grid_columnconfigure(0, weight=0)
        talent_card.grid_columnconfigure(1, weight=1)

        preview_panel = ctk.CTkFrame(talent_card, fg_color="#0A1019", corner_radius=18, border_width=1, border_color="#223552")
        preview_panel.grid(row=0, column=0, rowspan=7, padx=20, pady=20, sticky="ns")
        preview_panel.grid_columnconfigure(0, weight=1)
        self.player_avatar_label = ctk.CTkLabel(
            preview_panel,
            text="Фото\nигрока",
            width=230,
            height=230,
            fg_color="#111A28",
            corner_radius=18,
            text_color=self._ui["cyan"],
            font=ctk.CTkFont(family="Sora", size=24, weight="bold"),
        )
        self.player_avatar_label.grid(row=0, column=0, padx=16, pady=(16, 12), sticky="ew")
        ctk.CTkLabel(
            preview_panel,
            text="Плашка ESPN / NBA intro",
            text_color=self._ui["muted"],
            font=ctk.CTkFont(family="Inter", size=12, weight="bold"),
        ).grid(row=1, column=0, padx=16, pady=(0, 8), sticky="w")
        ctk.CTkLabel(
            preview_panel,
            text="1. Выберите игрока\n2. Проверьте поля\n3. Подготовьте PREVIEW\n4. Разрешите и нажмите LIVE",
            justify="left",
            text_color="#B6C2D4",
            font=ctk.CTkFont(family="Inter", size=12),
        ).grid(row=2, column=0, padx=16, pady=(0, 16), sticky="w")

        form_panel = ctk.CTkFrame(talent_card, fg_color="transparent")
        form_panel.grid(row=0, column=1, padx=(0, 20), pady=20, sticky="nsew")
        form_panel.grid_columnconfigure((0, 1), weight=1)

        self.player_pick_var = tk.StringVar(value="Список игроков пуст")
        self.player_pick_values: List[str] = ["Список игроков пуст"]
        self.player_pick_map: Dict[str, Dict[str, Any]] = {}
        self._field_label(form_panel, "Игрок из текущего матча").grid(row=0, column=0, columnspan=2, padx=0, pady=(0, 6), sticky="w")
        self.player_pick_menu = ctk.CTkOptionMenu(
            form_panel,
            variable=self.player_pick_var,
            values=self.player_pick_values,
            command=self._on_player_selected,
            height=44,
            corner_radius=12,
            fg_color="#142033",
            button_color="#1F6FFF",
            button_hover_color="#21D4FD",
            text_color=self._ui["text"],
            font=ctk.CTkFont(family="Inter", size=13, weight="bold"),
        )
        self.player_pick_menu.grid(row=1, column=0, columnspan=2, padx=0, pady=(0, 12), sticky="ew")
        self.player_pick_buttons = ctk.CTkFrame(form_panel, fg_color="transparent")
        self.player_pick_buttons.grid(row=2, column=0, columnspan=2, padx=0, pady=(0, 16), sticky="ew")
        self.player_pick_buttons.grid_columnconfigure((0, 1), weight=1)
        self.player_reload_btn = self._broadcast_button(self.player_pick_buttons, "Обновить игроков", self._reload_match_players, "neutral")
        self.player_reload_btn.grid(row=0, column=0, padx=(0, 6), pady=0, sticky="ew")
        self.player_air_btn = self._broadcast_button(self.player_pick_buttons, "Загрузить в PREVIEW", self._preview_selected_player, "primary")
        self.player_air_btn.grid(row=0, column=1, padx=(6, 0), pady=0, sticky="ew")

        self._field_label(form_panel, "Имя").grid(row=3, column=0, padx=(0, 8), pady=(0, 6), sticky="w")
        self._field_label(form_panel, "Команда").grid(row=3, column=1, padx=(8, 0), pady=(0, 6), sticky="w")
        self.player_name_entry = self._control_entry(form_panel, "Например: Shai Gilgeous-Alexander")
        self.player_name_entry.grid(row=4, column=0, padx=(0, 8), pady=(0, 12), sticky="ew")
        self.player_team_entry = self._control_entry(form_panel, "Например: Oklahoma City Thunder")
        self.player_team_entry.grid(row=4, column=1, padx=(8, 0), pady=(0, 12), sticky="ew")

        self._field_label(form_panel, "Номер").grid(row=5, column=0, padx=(0, 8), pady=(0, 6), sticky="w")
        self._field_label(form_panel, "Позиция").grid(row=5, column=1, padx=(8, 0), pady=(0, 6), sticky="w")
        self.player_number_entry = self._control_entry(form_panel, "2")
        self.player_number_entry.grid(row=6, column=0, padx=(0, 8), pady=(0, 12), sticky="ew")
        self.player_position_entry = self._control_entry(form_panel, "G / F / C")
        self.player_position_entry.grid(row=6, column=1, padx=(8, 0), pady=(0, 12), sticky="ew")

        self._field_label(self.player_frame, "Фото игрока").grid(row=3, column=0, padx=24, pady=(0, 6), sticky="w")
        self.player_photo_entry = self._control_entry(self.player_frame, "URL или локальный путь к фото")
        self.player_photo_entry.grid(row=4, column=0, padx=24, pady=(0, 12), sticky="ew")
        self.player_stats_frame = self._control_card(self.player_frame)
        self.player_stats_frame.grid(row=5, column=0, padx=24, pady=(0, 16), sticky="ew")
        self.player_stats_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="stats")
        self.ppg_entry = self._control_entry(self.player_stats_frame, "PPG")
        self.rpg_entry = self._control_entry(self.player_stats_frame, "RPG")
        self.apg_entry = self._control_entry(self.player_stats_frame, "APG")
        self.stl_entry = self._control_entry(self.player_stats_frame, "STL")
        self.blk_entry = self._control_entry(self.player_stats_frame, "BLK")
        for idx, (label, entry) in enumerate([
            ("Очки", self.ppg_entry),
            ("Подборы", self.rpg_entry),
            ("Передачи", self.apg_entry),
            ("Перехваты", self.stl_entry),
            ("Блоки", self.blk_entry),
        ]):
            self._field_label(self.player_stats_frame, label).grid(row=0, column=idx, padx=(14 if idx == 0 else 5, 14 if idx == 4 else 5), pady=(14, 6), sticky="w")
            entry.grid(row=1, column=idx, padx=(14 if idx == 0 else 5, 14 if idx == 4 else 5), pady=(0, 14), sticky="ew")

        self.player_btns_frame = self._control_card(self.player_frame)
        self.player_btns_frame.grid(row=6, column=0, padx=24, pady=(0, 12), sticky="ew")
        self.player_btns_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.player_show_btn = self._broadcast_button(self.player_btns_frame, "Подготовить", self._preview_player_card, "primary")
        self.player_show_btn.grid(row=0, column=0, padx=(16, 5), pady=16, sticky="ew")
        self.player_arm_btn = self._broadcast_button(self.player_btns_frame, "Разрешить", self._arm_preview, "amber")
        self.player_arm_btn.grid(row=0, column=1, padx=5, pady=16, sticky="ew")
        self.player_take_btn = self._broadcast_button(self.player_btns_frame, "В LIVE", self._take_preview_to_air, "success")
        self.player_take_btn.grid(row=0, column=2, padx=5, pady=16, sticky="ew")
        self.player_hide_btn = self._broadcast_button(self.player_btns_frame, "Скрыть", self._hide_player_card, "neutral")
        self.player_hide_btn.grid(row=0, column=3, padx=(5, 16), pady=16, sticky="ew")
        danger_row = ctk.CTkFrame(self.player_frame, fg_color="transparent")
        danger_row.grid(row=7, column=0, padx=24, pady=(0, 12), sticky="ew")
        danger_row.grid_columnconfigure((0, 1), weight=1)
        self.player_reset_btn = self._broadcast_button(danger_row, "Сбросить карточку", self._reset_player_card, "danger")
        self.player_reset_btn.grid(row=0, column=0, padx=(0, 8), pady=0, sticky="ew")
        self.emergency_hide_btn = self._broadcast_button(danger_row, "Срочно скрыть всё", self._emergency_hide_all, "danger")
        self.emergency_hide_btn.grid(row=0, column=1, padx=(8, 0), pady=0, sticky="ew")
        self.player_find_photo_btn = self._broadcast_button(self.player_frame, "Найти фото NBA", self._auto_find_nba_photo, "neutral")
        self.player_find_photo_btn.grid(row=8, column=0, padx=24, pady=(0, 12), sticky="ew")
        self.player_status = self._status_label(self.player_frame, "", self._ui["muted"])
        self.player_status.grid(row=9, column=0, padx=24, pady=(0, 24), sticky="w")

    def _build_secondary_tabs(self) -> None:
        self._build_diagnostics_tab()

    def _simple_tab_panel(self, tab_name: str, title: str) -> ctk.CTkFrame:
        panel = self._control_card(self.tabs.tab(tab_name), "#0B111A", "#20314A", radius=22)
        panel.grid(row=0, column=0, padx=24, pady=24, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            panel,
            text=title.upper(),
            font=ctk.CTkFont(family="Sora", size=28, weight="bold"),
            text_color=self._ui.get("text", "#ffffff"),
        ).grid(
            row=0, column=0, padx=22, pady=(22, 12), sticky="w"
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
            text="Выбор игрока готовит PREVIEW и не меняет LIVE без подтверждения.",
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
        panel = self._simple_tab_panel("ДИАГНОСТИКА", "Diagnostics")
        self.diagnostics_text = ctk.CTkTextbox(
            panel,
            height=360,
            corner_radius=14,
            fg_color="#070B11",
            border_color="#263754",
            border_width=1,
            text_color=self._ui.get("text", "#ffffff"),
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.diagnostics_text.grid(row=1, column=0, padx=22, pady=(0, 14), sticky="nsew")
        panel.grid_rowconfigure(1, weight=1)
        self._broadcast_button(panel, "RUN SYSTEM CHECK", self._run_self_check, "primary").grid(
            row=2, column=0, padx=22, pady=(0, 22), sticky="ew"
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
            self.obs_tab_status.configure(text="Порт занят или сервер недоступен", text_color="#ff5a5a")
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
            live_name = live.player.name if live.phase != "emergency_hidden" else "скрыто срочно"
            preview_text = f"PREVIEW: {preview.phase} · {preview_name}"
            live_text = f"LIVE: {live.phase} · {live_name or 'пусто'}"
            compact_text = f"{preview_text}\n{live_text}"
            if hasattr(self, "air_preview_label"):
                self.air_preview_label.configure(text=preview_text)
            if hasattr(self, "air_live_label"):
                self.air_live_label.configure(text=live_text)
            if hasattr(self, "player_flow_state"):
                self.player_flow_state.configure(text=compact_text)
            if hasattr(self, "players_tab_preview"):
                self.players_tab_preview.configure(text=preview_text)
            if hasattr(self, "players_tab_live"):
                self.players_tab_live.configure(text=live_text)
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

    def _on_url_changed(self, _event: Any = None) -> None:
        if self._url_parse_after:
            self.after_cancel(self._url_parse_after)
        self._show_input_detected(self.url_entry.get().strip(), source="typing")
        self._url_parse_after = self.after(180, lambda: self._parse_match_url_preview(self.url_entry.get().strip()))

    def _extract_match_preview(self, url: str) -> Tuple[str, str, str]:
        text = (url or "").strip()
        if not text:
            return "", "", ""
        try:
            parsed = urllib.parse.urlparse(text)
        except ValueError:
            return "", "", ""
        segments = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
        if len(segments) >= 3 and segments[0].lower() == "match":
            sport = segments[1].replace("-", " ").upper()
            if len(segments) >= 4:
                home_slug = re.sub(r"-[A-Za-z0-9]{5,}$", "", segments[2])
                away_slug = re.sub(r"-[A-Za-z0-9]{5,}$", "", segments[3])
                home = " ".join(part.title() for part in home_slug.split("-") if part)
                away = " ".join(part.title() for part in away_slug.split("-") if part)
                if home and away:
                    return sport, home, away
            teams = re.sub(r"-[A-Za-z0-9]{5,}$", "", segments[2])
            if "-vs-" in teams:
                home_slug, away_slug = teams.split("-vs-", 1)
                home = " ".join(part.title() for part in home_slug.split("-") if part)
                away = " ".join(part.title() for part in away_slug.split("-") if part)
                if home and away:
                    return sport, home, away
        return "", "", ""

    def _show_input_detected(self, url: str, source: str = "input") -> None:
        has_url = bool(url)
        self.url_entry.configure(border_color=self._ui["cyan"] if has_url else "#263754")
        if not has_url:
            self._set_pipeline_stage("input", "idle")
            self.match_detected_label.configure(text="Waiting for match URL", text_color=self._ui["muted"], fg_color="#111722")
            return
        self._set_pipeline_stage("input", "active")
        self.match_detected_label.configure(text="Parsing match source...", text_color=self._ui["cyan"], fg_color="#102233")
        if source != "typing":
            self._add_activity("input", "URL received from clipboard")

    def _parse_match_url_preview(self, url: str) -> None:
        sport, home, away = self._extract_match_preview(url)
        if home and away:
            self.match_detected_label.configure(
                text=f"Match detected: {home} vs {away}",
                text_color=self._ui["lime"],
                fg_color="#102414",
            )
            self.preview_home_label.configure(text=f"{home}\ncache pending", text_color=self._ui["text"], fg_color="#111A27")
            self.preview_away_label.configure(text=f"{away}\ncache pending", text_color=self._ui["text"], fg_color="#111A27")
            self.preview_score_label.configure(text="-- : --")
            self._set_pipeline_stage("input", "done")
            self._add_activity("parse", f"{sport or 'MATCH'} detected: {home} vs {away}")
        elif url:
            self.match_detected_label.configure(text="URL detected, waiting for Flashscore match pattern", text_color=self._ui["amber"], fg_color="#251E0F")
            self._set_pipeline_stage("input", "active")

    def _abbr_from_name(self, name: str) -> str:
        normalized = latinize_name(name)
        if normalized in NBA_TEAM_ABBRS:
            return NBA_TEAM_ABBRS[normalized]
        words = [part for part in re.split(r"\s+", str(name or "").strip()) if part]
        if not words:
            return "---"
        if len(words) == 1:
            return words[0][:3].upper()
        return "".join(word[0] for word in words[:3]).upper()

    def _name_tokens(self, name: str) -> set[str]:
        text = normalize_name(name)
        return {part for part in re.split(r"\s+", text) if len(part) >= 3}

    def _result_matches_expected(self, data: Dict[str, Any], home_expected: str, away_expected: str) -> bool:
        if not home_expected or not away_expected:
            return False
        home = data.get("home", {}) if isinstance(data.get("home", {}), dict) else {}
        away = data.get("away", {}) if isinstance(data.get("away", {}), dict) else {}
        actual_home = f"{home.get('name', '')} {home.get('abbr', '')}"
        actual_away = f"{away.get('name', '')} {away.get('abbr', '')}"
        expected_home_abbr = self._abbr_from_name(home_expected)
        expected_away_abbr = self._abbr_from_name(away_expected)
        actual_home_abbr = str(home.get("abbr", "")).strip().upper()
        actual_away_abbr = str(away.get("abbr", "")).strip().upper()
        if expected_home_abbr in NBA_ABBRS and expected_away_abbr in NBA_ABBRS:
            direct_abbr = actual_home_abbr == expected_home_abbr and actual_away_abbr == expected_away_abbr
            swapped_abbr = actual_home_abbr == expected_away_abbr and actual_away_abbr == expected_home_abbr
            if direct_abbr or swapped_abbr:
                return True

        def matches(expected: str, actual: str) -> bool:
            expected_tokens = self._name_tokens(expected)
            actual_tokens = self._name_tokens(actual)
            if not expected_tokens or not actual_tokens:
                return False
            return bool(expected_tokens & actual_tokens)

        direct = matches(home_expected, actual_home) and matches(away_expected, actual_away)
        swapped = matches(home_expected, actual_away) and matches(away_expected, actual_home)
        return direct or swapped

    def _result_is_fresh_for_pending(self, data: Dict[str, Any], mtime: float) -> bool:
        if not self._pending_match_url:
            return False
        meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
        source_url = str(meta.get("source_url") or meta.get("match_key") or "").strip()
        if source_url and source_url == self._pending_match_url:
            return True
        updated_at = str(meta.get("updated_at") or "").strip()
        if updated_at:
            try:
                updated = datetime.datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=datetime.UTC)
                if updated.timestamp() >= self._pending_match_started:
                    return True
            except ValueError:
                pass
        if mtime and self._pending_result_mtime and mtime > self._pending_result_mtime + 0.25:
            return True
        return False

    def _begin_pending_match(self, url: str) -> None:
        _sport, home, away = self._extract_match_preview(url)
        self._pending_match_url = url
        self._pending_match_home = home
        self._pending_match_away = away
        self._pending_match_started = time.time()
        try:
            self._pending_result_mtime = os.path.getmtime(RESULT_PATH)
        except OSError:
            self._pending_result_mtime = 0.0
        if home and away:
            home_abbr = self._abbr_from_name(home)
            away_abbr = self._abbr_from_name(away)
            if hasattr(self, "top_game_label"):
                self.top_game_label.configure(text=f"{home} vs {away}  /  waiting for data")
            self.score_label.configure(text=f"{home_abbr}  -- — --  {away_abbr}")
            self.status_badge.configure(text="● SWITCHING", fg_color="#102233", text_color=self._ui["cyan"])
            self.live_badge.configure(text="● SWITCHING SOURCE", fg_color="#102233", text_color=self._ui["cyan"])
            self.preview_home_label.configure(text=f"{home}\nawaiting feed", text_color=self._ui["cyan"], fg_color="#102233")
            self.preview_away_label.configure(text=f"{away}\nawaiting feed", text_color=self._ui["cyan"], fg_color="#102233")
            self.preview_score_label.configure(text="-- : --", text_color=self._ui["cyan"])
            self.home_row_labels[0].configure(text=home_abbr)
            self.away_row_labels[0].configure(text=away_abbr)
            for idx in range(1, 5):
                self.home_row_labels[idx].configure(text="...")
                self.away_row_labels[idx].configure(text="...")
        self.match_detected_label.configure(text="Source armed. Waiting for first fresh payload...", text_color=self._ui["cyan"], fg_color="#102233")

    def _pending_match_active(self) -> bool:
        return bool(self._pending_match_url and self._pending_match_home and self._pending_match_away)

    def _clear_pending_match(self) -> None:
        self._pending_match_url = ""
        self._pending_match_home = ""
        self._pending_match_away = ""
        self._pending_match_started = 0.0
        self._pending_result_mtime = 0.0
        if self._hydration_watch_after:
            self.after_cancel(self._hydration_watch_after)
            self._hydration_watch_after = None

    def _add_activity(self, channel: str, message: str) -> None:
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self._activity_lines.insert(0, f"{stamp}  {channel.upper():<7} {message}")
        self._activity_lines = self._activity_lines[:8]
        if hasattr(self, "activity_feed"):
            self.activity_feed.configure(state="normal")
            self.activity_feed.delete("1.0", "end")
            self.activity_feed.insert("1.0", "\n".join(self._activity_lines))
            self.activity_feed.configure(state="disabled")

    def _set_pipeline_stage(self, key: str, status: str) -> None:
        self._pipeline_status[key] = status
        if not hasattr(self, "pipeline_labels"):
            return
        palette = {
            "idle": ("○", self._ui["muted"], "#101825"),
            "active": ("●", self._ui["cyan"], "#102233"),
            "done": ("✓", self._ui["lime"], "#102414"),
            "warn": ("!", self._ui["amber"], "#251E0F"),
            "error": ("!", self._ui["red"], "#2A1017"),
        }
        marker, color, bg = palette.get(status, palette["idle"])
        label_text = dict(self._pipeline_stages).get(key, key)
        self.pipeline_labels[key].configure(text=f"{marker} {label_text}", text_color=color, fg_color=bg)

    def _reset_pipeline(self) -> None:
        for key, _label in self._pipeline_stages:
            self._set_pipeline_stage(key, "idle")

    def _pulse_button(self, button: ctk.CTkButton, text: str, color: str) -> None:
        original_text = button.cget("text")
        original_color = button.cget("fg_color")
        button.configure(text=text, fg_color=color)
        self.after(900, lambda: button.configure(text=original_text, fg_color=original_color))

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
        if hasattr(self, "_select_control_tab"):
            self._select_control_tab("ИГРОКИ")
        else:
            self.tabs.set("ИГРОКИ")
        canvas = getattr(self.player_frame, "_parent_canvas", None)
        if canvas is not None:
            canvas.yview_moveto(0.0)
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
        self.apply_status.configure(text="Ссылка вставлена. Матч распознаётся...", text_color="#66e08a")
        self._show_input_detected(value, source="paste")
        self._parse_match_url_preview(value)

    def _load_config_url(self) -> None:
        data = read_json(CONFIG_PATH)
        urls = data.get("urls", [])
        url = urls[0] if isinstance(urls, list) and urls else ""
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, url)
        if url:
            self._parse_match_url_preview(url)
        self._refresh_embed_links()

    def _refresh_overlay_screen_controls(self, screen: str | None = None) -> None:
        if screen is None:
            result_data = read_json(RESULT_PATH)
            config_data = read_json(CONFIG_PATH)
            screen = overlay_screen_value(result_data.get("screen") or config_data.get("overlay_screen"))
        else:
            screen = overlay_screen_value(screen)

        if hasattr(self, "overlay_screen_status"):
            if screen == "player_stats":
                self.overlay_screen_status.configure(text="Нижний экран: личная статистика", text_color=self._ui["amber"])
            else:
                self.overlay_screen_status.configure(text="Нижний экран: командная статистика", text_color=self._ui["cyan"])

        if hasattr(self, "team_stats_screen_btn") and hasattr(self, "player_stats_screen_btn"):
            self.team_stats_screen_btn.configure(
                fg_color=self._ui["blue"] if screen == "team_stats" else "#202B3C",
                border_color="#21D4FD" if screen == "team_stats" else "#3A465C",
            )
            self.player_stats_screen_btn.configure(
                fg_color="#8A5B16" if screen == "player_stats" else "#202B3C",
                border_color="#FFB347" if screen == "player_stats" else "#3A465C",
            )

    def _set_overlay_screen(self, screen: str) -> None:
        target = overlay_screen_value(screen)

        config_data = read_json(CONFIG_PATH)
        config_data["overlay_screen"] = target
        ok, err = write_json(CONFIG_PATH, config_data, atomic=True)
        if not ok:
            if hasattr(self, "overlay_screen_status"):
                self.overlay_screen_status.configure(text=f"Не удалось сохранить экран: {err}", text_color=self._ui["red"])
            return

        result_data = read_json(RESULT_PATH)
        if result_data:
            result_data["screen"] = target
            ok, err = write_json(RESULT_PATH, result_data, atomic=True)
            if not ok and hasattr(self, "overlay_screen_status"):
                self.overlay_screen_status.configure(text=f"config.json сохранён, result.json не обновлён: {err}", text_color=self._ui["amber"])
                return

        self._refresh_overlay_screen_controls(target)
        label = "личная статистика" if target == "player_stats" else "командная статистика"
        self._add_activity("overlay", f"Нижний экран: {label}")

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
            self.status_badge.configure(text=text, fg_color="#2A1017", text_color=self._ui.get("red", "#ff5a5a"))
            if hasattr(self, "live_badge"):
                self.live_badge.configure(text="● LIVE ON AIR", fg_color="#2A1017", text_color=self._ui.get("red", "#ff5a5a"))
        elif st == "over":
            self.status_badge.configure(text="● ЗАВЕРШЁН", fg_color="#202B3C", text_color="#D7DEE9")
            if hasattr(self, "live_badge"):
                self.live_badge.configure(text="● FINAL", fg_color="#202B3C", text_color="#D7DEE9")
        else:
            self.status_badge.configure(text="● НЕ НАЧАТ", fg_color="#2E2511", text_color=self._ui.get("amber", "#ffd166"))
            if hasattr(self, "live_badge"):
                self.live_badge.configure(text="● STANDBY", fg_color="#2E2511", text_color=self._ui.get("amber", "#ffd166"))

    def _refresh_match(self) -> None:
        self._refresh_match_after = None
        started = time.perf_counter()
        data = read_json(RESULT_PATH)
        try:
            self._last_result_mtime = os.path.getmtime(RESULT_PATH)
        except OSError:
            self._last_result_mtime = 0.0

        home = data.get("home", {}) if isinstance(data.get("home", {}), dict) else {}
        away = data.get("away", {}) if isinstance(data.get("away", {}), dict) else {}
        self._refresh_overlay_screen_controls(data.get("screen"))

        home_abbr = self._safe_value(home.get("abbr"), "---")
        away_abbr = self._safe_value(away.get("abbr"), "---")
        home_total = self._safe_value(home.get("total"), "0")
        away_total = self._safe_value(away.get("total"), "0")
        home_name = self._safe_value(home.get("name"), home_abbr)
        away_name = self._safe_value(away.get("name"), away_abbr)

        if (
            self._pending_match_active()
            and not self._result_is_fresh_for_pending(data, self._last_result_mtime)
            and not self._result_matches_expected(data, self._pending_match_home, self._pending_match_away)
        ):
            age = int(time.time() - self._pending_match_started)
            self.apply_status.configure(
                text=f"Ожидаю данные нового матча: {self._pending_match_home} vs {self._pending_match_away}. Старый payload не выводится как готовый ({age}s).",
                text_color=self._ui["cyan"] if age < 25 else self._ui["amber"],
            )
            self._result_latency_ms = int((time.perf_counter() - started) * 1000)
            self._refresh_status_strip()
            self._refresh_match_after = self.after(1000, self._refresh_match)
            return

        if self._pending_match_active():
            if not self._result_matches_expected(data, self._pending_match_home, self._pending_match_away):
                self._add_activity("fresh", "Fresh payload accepted; team names differ by locale/abbreviation")
            self._hydrate_pending_match(data)

        self.score_label.configure(text=f"{home_abbr}  {home_total} — {away_total}  {away_abbr}")
        if hasattr(self, "preview_home_label"):
            self.preview_home_label.configure(text=f"{home_abbr}\n{home_name}", text_color=self._ui["text"], fg_color="#111A27")
            self.preview_away_label.configure(text=f"{away_abbr}\n{away_name}", text_color=self._ui["text"], fg_color="#111A27")
            self.preview_score_label.configure(text=f"{home_total} : {away_total}", text_color=self._ui["cyan"])
        if hasattr(self, "top_game_label"):
            self.top_game_label.configure(text=f"{home_name} vs {away_name}")

        status = self._safe_value(data.get("status"), "scheduled")
        quarter = self._safe_value(data.get("quarter"), "")
        self._update_status_badge(status, quarter)

        self.home_row_labels[0].configure(text=home_abbr)
        self.away_row_labels[0].configure(text=away_abbr)

        quarter_keys = ["q1", "q2", "q3", "q4"]
        for idx, key in enumerate(quarter_keys, start=1):
            self.home_row_labels[idx].configure(text=self._safe_value(home.get(key)))
            self.away_row_labels[idx].configure(text=self._safe_value(away.get(key)))

        self._result_latency_ms = int((time.perf_counter() - started) * 1000)
        self._refresh_status_strip()
        self._refresh_match_after = self.after(3000, self._refresh_match)

    def _refresh_scraper_state(self) -> None:
        running = SCRAPER_CONTROLLER.is_running()
        if running:
            self.scraper_state_label.configure(text="● Запущен", text_color="#66e08a")
            if hasattr(self, "server_state_label"):
                self.server_state_label.configure(text="SYNC: ACTIVE  /  SERVER: INGEST ONLINE", text_color=self._ui.get("lime", "#66e08a"))
        else:
            self.scraper_state_label.configure(text="● Остановлен", text_color="#ff5a5a")
            if hasattr(self, "server_state_label"):
                self.server_state_label.configure(text="SYNC: LOCAL  /  SERVER: STANDBY", text_color=self._ui.get("muted", "#9ba3af"))
        self._refresh_status_strip()
        self.after(2000, self._refresh_scraper_state)

    def _refresh_status_strip(self) -> None:
        if not hasattr(self, "status_chips"):
            return
        now = time.time()
        result_age = now - self._last_result_mtime if self._last_result_mtime else 999
        scraper_running = SCRAPER_CONTROLLER.is_running()
        overlay_running = self._overlay_httpd is not None
        api_color = self._ui["lime"] if self._result_latency_ms < 25 else self._ui["amber"]
        pending = self._pending_match_active()
        sync_color = self._ui["cyan"] if pending else (self._ui["lime"] if result_age < 12 else self._ui["amber"])
        self.status_chips["api"].configure(text=f"API  {self._result_latency_ms or '--'} ms", text_color=api_color, fg_color="#102414" if api_color == self._ui["lime"] else "#251E0F")
        sync_text = "hydrating new match" if pending else f"{'live' if scraper_running else 'standby'} / {result_age:.0f}s"
        self.status_chips["sync"].configure(
            text=f"SYNC  {sync_text}",
            text_color=sync_color,
            fg_color="#102233" if pending else ("#102414" if sync_color == self._ui["lime"] else "#251E0F"),
        )
        self.status_chips["overlay"].configure(
            text=f"OVERLAY  {'online' if overlay_running else 'ready'}",
            text_color=self._ui["lime"] if overlay_running else self._ui["muted"],
            fg_color="#102414" if overlay_running else "#0F1622",
        )
        self.status_chips["obs"].configure(text="OBS  browser route", text_color=self._ui["cyan"], fg_color="#102233")
        self.status_chips["vmix"].configure(text="VMIX  browser route", text_color=self._ui["cyan"], fg_color="#102233")

    def _animate_activity(self) -> None:
        self._motion_tick = (self._motion_tick + 1) % 4
        dots = "." * (self._motion_tick + 1)
        if self._match_pipeline_active:
            for key, status in self._pipeline_status.items():
                if status == "active" and hasattr(self, "pipeline_labels"):
                    label = dict(self._pipeline_stages).get(key, key)
                    self.pipeline_labels[key].configure(text=f"● {label}{dots}")
            if hasattr(self, "preview_score_label"):
                shimmer = ["-- : --", "▰- : -▰", "▰▰ : ▰▰", "-- : --"][self._motion_tick]
                current = self.preview_score_label.cget("text")
                if not re.search(r"\d", str(current)):
                    self.preview_score_label.configure(text=shimmer)
        self.after(260, self._animate_activity)

    def _start_scraper(self) -> None:
        if SCRAPER_CONTROLLER.is_running():
            self.apply_status.configure(text="Источник данных уже запущен", text_color="#9ba3af")
            return

        if not os.path.exists(MAIN_EXE):
            self.apply_status.configure(text="Не найден main.exe", text_color="#ff5a5a")
            return

        try:
            pid = SCRAPER_CONTROLLER.start()
            self.apply_status.configure(text=f"Источник данных запущен (PID {pid})", text_color="#66e08a")
        except OSError as exc:
            self.apply_status.configure(text=f"Ошибка запуска: {exc}", text_color="#ff5a5a")

    def _stop_scraper(self) -> None:
        if not SCRAPER_CONTROLLER.is_running():
            self.apply_status.configure(text="Источник данных уже остановлен", text_color="#9ba3af")
            return

        if not messagebox.askyesno("Остановить данные", "Остановить получение данных? В эфире останутся последние валидные данные."):
            return

        SCRAPER_CONTROLLER.stop()
        self.apply_status.configure(text="Источник данных остановлен", text_color="#66e08a")

    def _apply_match_url(self) -> None:
        new_url = self.url_entry.get().strip()
        if not new_url:
            self.apply_status.configure(text="Введите URL матча", text_color=self._ui["red"])
            self._set_pipeline_stage("input", "error")
            return

        if self._match_pipeline_active:
            self.apply_status.configure(text="Переключение уже выполняется. UI остаётся доступным.", text_color=self._ui["amber"])
            return

        self._match_pipeline_active = True
        self._reset_pipeline()
        self._show_input_detected(new_url, source="apply")
        self._parse_match_url_preview(new_url)
        self._begin_pending_match(new_url)
        self._set_pipeline_stage("config", "active")
        self._set_pipeline_stage("fetch", "active")
        self.apply_status.configure(text="Source armed. Waiting for new match payload; old game is held as stale.", text_color=self._ui["cyan"])
        self.apply_btn.configure(state="disabled", text="SYNCING MATCH SOURCE...")
        self._pulse_button(self.paste_btn, "RECEIVED", "#145B72")
        self._add_activity("apply", "Optimistic match switch started")

        worker = threading.Thread(target=self._apply_match_url_worker, args=(new_url,), name="match-source-switch", daemon=True)
        worker.start()

    def _apply_match_url_worker(self, new_url: str) -> None:
        started = time.perf_counter()
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
            self.after(0, lambda: self._finish_match_pipeline(False, f"Не удалось сохранить config.json: {err}", failed_stage="config"))
            return
        self.after(0, lambda: self._set_pipeline_stage("config", "done"))
        self.after(0, lambda: self._add_activity("config", "config.json saved atomically"))
        self.after(0, self._refresh_embed_links)

        clear_player_cache()
        write_json(
            PLAYER_DEBUG_PATH,
            {"schema_version": 1, "match_key": new_url, "updated_at": now_iso(), "candidates": []},
            atomic=False,
        )
        player_data = default_player_data()
        player_data["source"] = "manager"
        player_data["photo_status"] = "stale"
        player_data["match_key"] = new_url
        player_data["updated_at"] = now_iso()
        self._write_player_data(player_data)
        self.after(0, self._load_player_form)
        self.after(0, lambda: self._set_pipeline_stage("players", "active"))
        self.after(0, lambda: self._add_activity("players", "Player cache reset; waiting for hydrated candidates"))
        self.after(0, self._reload_match_players)

        if not os.path.exists(MAIN_EXE):
            self.after(0, lambda: self._finish_match_pipeline(False, "Ссылка сохранена, но main.exe не найден", failed_stage="fetch", warn=True))
            return

        try:
            pid = SCRAPER_CONTROLLER.restart()
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            self.after(0, lambda: self._set_pipeline_stage("fetch", "done"))
            self.after(0, lambda: self._set_pipeline_stage("teams", "active"))
            self.after(0, lambda: self._set_pipeline_stage("overlay", "active"))
            self.after(0, lambda: self._add_activity("ingest", f"main.exe restarted PID {pid} in {elapsed_ms}ms"))
            self.after(0, lambda: self._watch_match_hydration(pid))
        except OSError as exc:
            self.after(0, lambda: self._finish_match_pipeline(False, f"Ссылка сохранена, но источник данных не запустился: {exc}", failed_stage="fetch", warn=True))

    def _watch_match_hydration(self, pid: int) -> None:
        self._hydration_watch_after = None
        data = read_json(RESULT_PATH)
        try:
            mtime = os.path.getmtime(RESULT_PATH)
        except OSError:
            mtime = 0.0
        if self._pending_match_active() and (
            self._result_is_fresh_for_pending(data, mtime)
            or self._result_matches_expected(data, self._pending_match_home, self._pending_match_away)
        ):
            if not self._result_matches_expected(data, self._pending_match_home, self._pending_match_away):
                self._add_activity("fresh", "Fresh payload accepted; team names differ by locale/abbreviation")
            self._hydrate_pending_match(data)
            self._finish_match_pipeline(True, f"Broadcast Ready. Новый матч загружен (PID {pid})")
            return
        age = int(time.time() - self._pending_match_started)
        if age >= 35:
            stale_note = "result.json ещё не сменился" if mtime <= self._pending_result_mtime else "payload обновился, но команды не совпали"
            self._finish_match_pipeline(False, f"Источник перезапущен, но новый матч не подтвердился: {stale_note}. Проверьте URL или main.exe.", failed_stage="teams", warn=True)
            return
        self.apply_status.configure(
            text=f"Источник перезапущен (PID {pid}). Жду первый payload нового матча... {age}s",
            text_color=self._ui["cyan"],
        )
        self._add_activity("wait", f"old result held; waiting for {self._pending_match_home} vs {self._pending_match_away}")
        self._hydration_watch_after = self.after(1000, lambda: self._watch_match_hydration(pid))

    def _hydrate_pending_match(self, data: Dict[str, Any]) -> None:
        self._set_pipeline_stage("teams", "done")
        self._set_pipeline_stage("players", "active")
        self._set_pipeline_stage("overlay", "active")
        self._add_activity("hydrate", "Fresh result payload matches armed source")
        self._clear_pending_match()
        self._reload_match_players()

    def _finish_match_pipeline(self, ok: bool, message: str, failed_stage: str = "", warn: bool = False) -> None:
        self._match_pipeline_active = False
        self.apply_btn.configure(state="normal", text="ARM NEW MATCH SOURCE")
        if ok:
            self._set_pipeline_stage("players", "done")
            self._set_pipeline_stage("overlay", "done")
            self.apply_status.configure(text=message, text_color=self._ui["lime"])
            self.match_detected_label.configure(text="Broadcast Ready", text_color=self._ui["lime"], fg_color="#102414")
            self.url_entry.configure(border_color=self._ui["lime"])
            self._add_activity("ready", "Scoreboard, players and overlay buses are syncing")
            if self._refresh_match_after:
                self.after_cancel(self._refresh_match_after)
            self._refresh_match()
            self._refresh_control_room_state(schedule_next=False)
            return
        if failed_stage:
            self._set_pipeline_stage(failed_stage, "warn" if warn else "error")
        self.apply_status.configure(text=message, text_color=self._ui["amber"] if warn else self._ui["red"])
        self.match_detected_label.configure(text="Needs operator attention", text_color=self._ui["amber"] if warn else self._ui["red"], fg_color="#251E0F" if warn else "#2A1017")
        self._add_activity("warn" if warn else "error", message)

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
        self.player_pick_menu.configure(button_color="#21D4FD")
        self.after(320, lambda: self.player_pick_menu.configure(button_color="#1F6FFF"))
        self.player_avatar_label.configure(text="Hydrating\nstats", text_color=self._ui["cyan"], fg_color="#102233")
        self._fill_player_form_from_candidate(candidate)
        self._write_player_preview(candidate=candidate)
        self.after(260, lambda: self.player_avatar_label.configure(text=f"{candidate.get('name', '')}\nPREVIEW", text_color=self._ui["lime"], fg_color="#102414"))
        if self._suspend_player_autopublish:
            self.player_status.configure(text="Игрок загружен в PREVIEW", text_color="#9ba3af")
            return

        self.player_status.configure(
            text="PREVIEW обновлён. LIVE не изменился. Разрешите вывод и нажмите «Вывести в LIVE».",
            text_color="#ffd166",
        )

    def _reload_match_players(self) -> None:
        if hasattr(self, "player_reload_btn"):
            self._pulse_button(self.player_reload_btn, "LOADING...", "#145B72")
        if hasattr(self, "player_status"):
            self.player_status.configure(text="Список игроков обновляется без блокировки эфира...", text_color=self._ui["cyan"])
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
                text="Игроки появятся после первого цикла получения данных.",
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
        self._pulse_button(self.player_air_btn, "SENDING PREVIEW...", "#145B72")
        self._fill_player_form_from_candidate(candidate)
        self._write_player_preview(candidate=candidate)
        self.player_status.configure(
            text="Игрок подготовлен в PREVIEW. Для эфира: разрешите вывод и нажмите «Вывести в LIVE».",
            text_color="#ffd166",
        )

    def _preview_player_card(self) -> None:
        data = self._build_player_payload()
        if not data.get("name"):
            self.player_status.configure(text="Укажите имя игрока для PREVIEW", text_color="#ff5a5a")
            return
        self._pulse_button(self.player_show_btn, "PREVIEW SYNC...", "#145B72")
        self._write_player_preview(payload=data)
        self.player_status.configure(
            text="PREVIEW готов. LIVE не изменился. Теперь разрешите вывод.",
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
            payload["player_url"] = str(candidate.get("player_url", "")).strip()
            payload["stats"] = {
                "PPG": str(candidate.get("pts", "")),
                "RPG": str(candidate.get("reb", "")),
                "APG": str(candidate.get("ast", "")),
                "STL": str(candidate.get("stl", "")),
                "BLK": str(candidate.get("blk", "")),
                **candidate.get("extra_stats", {}),
            }

        if not payload.get("photo"):
            self._try_fill_nba_photo(payload)

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
        if hasattr(self, "player_avatar_label"):
            self.player_avatar_label.configure(text=f"{payload.get('name', '')}\nPREVIEW", text_color=self._ui["cyan"], fg_color="#102233")
        self._refresh_control_room_state(schedule_next=False)

    def _arm_preview(self) -> None:
        snapshot = STATE_STORE.read("preview_state", GraphicState, max_age_s=300)
        player_name = snapshot.value.player.name.strip()
        if not player_name:
            self.player_status.configure(text="Нет подготовленного PREVIEW", text_color="#ff5a5a")
            return
        state = snapshot.value.model_copy(update={"phase": "armed", "armed": True, "message": f"Разрешён вывод: {player_name}"})
        STATE_STORE.write("preview_state", state, update_last_good=False)
        self._take_armed = True
        self._pulse_button(self.player_arm_btn, "ARMED", "#8A5B16")
        self.player_status.configure(text=f"Вывод разрешён: {player_name}. Теперь нажмите «Вывести в LIVE».", text_color="#ffd166")
        self._refresh_control_room_state(schedule_next=False)

    def _take_preview_to_air(self) -> None:
        snapshot = STATE_STORE.read("preview_state", GraphicState, max_age_s=300)
        if not (self._take_armed or snapshot.value.armed):
            self.player_status.configure(text="Сначала разрешите вывод в LIVE", text_color="#ff5a5a")
            return
        player = snapshot.value.player.model_dump(by_alias=True)
        if not str(player.get("name", "")).strip():
            self.player_status.configure(text="PREVIEW пуст", text_color="#ff5a5a")
            return
        player["visible"] = True
        player["mode"] = "manual_lock"
        player["source"] = "manager-take"
        player["updated_at"] = now_iso()
        self._pulse_button(self.player_take_btn, "TAKING LIVE...", "#178C4B")

        if not player.get("photo"):
            self._try_fill_nba_photo(player)

        ok, err = self._write_player_data(player)
        if not ok:
            self.player_status.configure(text=f"Не удалось вывести в LIVE: {err}", text_color="#ff5a5a")
            return

        live_state = GraphicState(
            phase="on_air_synced",
            selected_layer="player_card",
            armed=False,
            player=PlayerState.model_validate(player),
            result=read_json(RESULT_PATH),
            message=f"LIVE: {player.get('name', '')}",
        )
        STATE_STORE.write("live_state", live_state)
        STATE_STORE.write("last_good_state", live_state)
        self._take_armed = False
        if hasattr(self, "player_avatar_label"):
            self.player_avatar_label.configure(text=f"{player.get('name', '')}\nLIVE", text_color=self._ui["lime"], fg_color="#102414")
        self.player_status.configure(text=f"В LIVE: {player.get('name', '')}", text_color="#66e08a")
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
        pid = ""
        lookup_names = [
            _player_name_from_url_slug(str(player.get("player_url", ""))),
            str(player.get("name", "")),
        ]
        for lookup_name in lookup_names:
            if not lookup_name:
                continue
            try:
                pid = find_nba_player_id(lookup_name)
            except Exception:
                pid = ""
            if pid:
                break
        if pid:
            local_path = os.path.join(PLAYER_CACHE_DIR, f"{pid}.png")
            local_rel = f"json/players/{pid}.png"
            if not download_player_photo(nba_photo_url(pid), local_path, referer="https://www.nba.com/"):
                return
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
            self.player_status.configure(text=f"Не удалось срочно скрыть графику: {err}", text_color="#ff5a5a")
            return
        state = GraphicState(
            phase="emergency_hidden",
            selected_layer="all",
            armed=False,
            emergency_hidden=True,
            player=PlayerState.model_validate(data),
            result=read_json(RESULT_PATH),
            message="Срочно скрыто",
        )
        STATE_STORE.write("live_state", state)
        STATE_STORE.write("last_good_state", state)
        self._take_armed = False
        self.player_status.configure(text="Вся графика срочно скрыта", text_color="#ff5a5a")
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
        data["player_url"] = str(candidate.get("player_url", "")).strip()
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
            photo_value = str(data.get("photo", "")).strip()
            if "cdn.nba.com/headshots/nba/" in photo_value or re.search(r"json/players/\d+\.png$", photo_value):
                data["photo_source"] = "auto:nba"
                data["photo_status"] = "auto_found"
            elif photo_value.startswith("json/players/"):
                data["photo_source"] = str(data.get("photo_source", "") or "auto:cached")
                data["photo_status"] = str(data.get("photo_status", "") or "auto_found")
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
        if not messagebox.askyesno("Скрыть карточку", "Скрыть карточку игрока из эфира?"):
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
                message="Карточка игрока скрыта",
            )
            STATE_STORE.write("live_state", state)
            self.player_status.configure(text="Карточка игрока скрыта", text_color="#9ba3af")
            self._refresh_control_room_state(schedule_next=False)
        else:
            self.player_status.configure(text=f"Ошибка сохранения: {err}", text_color="#ff5a5a")

    def _reset_player_card(self) -> None:
        if not messagebox.askyesno("Сбросить карточку", "Сбросить карточку игрока и очистить ручную фиксацию?"):
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
