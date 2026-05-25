#!/usr/bin/env python3
"""
Basketball stats scraper for Flashscore -> vMix overlay
Reads:  json/config.json
Writes: json/result.json   every update_frequency seconds
    json/player.json   synchronized with result.json cycle
"""

import json
import time
import os
import sys
import logging
import re
import datetime
import tempfile
import difflib
import hashlib
import urllib.error
import urllib.parse
import urllib.request

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.webdriver import WebDriver as ChromeWebDriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ── Paths ──────────────────────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, 'json', 'config.json')
RESULT_PATH = os.path.join(BASE_DIR, 'json', 'result.json')
PLAYER_PATH = os.path.join(BASE_DIR, 'json', 'player.json')
PLAYER_CACHE_DIR = os.path.join(BASE_DIR, 'json', 'players')
PLAYER_DEBUG_PATH = os.path.join(BASE_DIR, 'json', 'player_candidates.json')
NBA_PLAYERS_CACHE_PATH = os.path.join(BASE_DIR, 'json', 'nba_players_cache.json')

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    filename=os.path.join(BASE_DIR, 'debug.log'),
    filemode='w',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger()

NBA_ABBRS = {
    'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
    'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
    'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS',
}

_NBA_ROSTER_CACHE = {
    'at': 0.0,
    'players': [],
}


# ── Team abbreviation lookup ───────────────────────────────────────────────────
_TEAM_ABBR: dict[str, str] = {
    # NBA (English)
    'atlanta hawks': 'ATL', 'boston celtics': 'BOS', 'brooklyn nets': 'BKN',
    'charlotte hornets': 'CHA', 'chicago bulls': 'CHI', 'cleveland cavaliers': 'CLE',
    'dallas mavericks': 'DAL', 'denver nuggets': 'DEN', 'detroit pistons': 'DET',
    'golden state warriors': 'GSW', 'houston rockets': 'HOU', 'indiana pacers': 'IND',
    'los angeles clippers': 'LAC', 'la clippers': 'LAC',
    'los angeles lakers': 'LAL', 'la lakers': 'LAL',
    'memphis grizzlies': 'MEM', 'miami heat': 'MIA', 'milwaukee bucks': 'MIL',
    'minnesota timberwolves': 'MIN', 'new orleans pelicans': 'NOP',
    'new york knicks': 'NYK', 'oklahoma city thunder': 'OKC', 'orlando magic': 'ORL',
    'philadelphia 76ers': 'PHI', 'philadelphia sixers': 'PHI',
    'phoenix suns': 'PHX', 'portland trail blazers': 'POR',
    'sacramento kings': 'SAC', 'san antonio spurs': 'SAS', 'toronto raptors': 'TOR',
    'utah jazz': 'UTA', 'washington wizards': 'WAS',
    # NBA (Russian — flashscorekz.com)
    'атланта хокс': 'ATL', 'бостон селтикс': 'BOS', 'бруклин нетс': 'BKN',
    'шарлотт хорнетс': 'CHA', 'чикаго буллс': 'CHI', 'кливленд кавальерс': 'CLE',
    'даллас маверикс': 'DAL', 'денвер наггетс': 'DEN', 'детройт пистонс': 'DET',
    'голден стэйт уорриорз': 'GSW', 'хьюстон рокетс': 'HOU', 'индиана пэйсерс': 'IND',
    'лос-анджелес клипперс': 'LAC', 'лос анджелес клипперс': 'LAC',
    'лос-анджелес лейкерс': 'LAL', 'лос анджелес лейкерс': 'LAL',
    'мемфис гриззлис': 'MEM', 'майами хит': 'MIA', 'милуоки бакс': 'MIL',
    'миннесота тимбервулвз': 'MIN', 'нью-орлеан пеликанс': 'NOP',
    'нью-йорк никс': 'NYK', 'оклахома-сити тандер': 'OKC', 'оклахома сити тандер': 'OKC',
    'орландо мэджик': 'ORL', 'филадельфия 76ers': 'PHI', 'финикс санс': 'PHX',
    'портленд трэйл блэйзерс': 'POR', 'сакраменто кингс': 'SAC',
    'сан-антонио спёрс': 'SAS', 'торонто рэпторс': 'TOR',
    'юта джаз': 'UTA', 'вашингтон уизардс': 'WAS',
    # EuroLeague / FIBA
    'olympiacos': 'OLY', 'olympiacos piraeus': 'OLY', 'олимпиакос': 'OLY',
    'real madrid': 'MAD', 'реал мадрид': 'MAD',
    'cska moscow': 'CSK', 'cska': 'CSK', 'цска': 'CSK',
    'fenerbahce': 'FEN', 'fenerbahçe': 'FEN', 'фенербахче': 'FEN',
    'anadolu efes': 'EFE', 'анадолу эфес': 'EFE',
    'fc barcelona': 'BAR', 'barcelona': 'BAR', 'барселона': 'BAR',
    'fc bayern munich': 'BAY', 'bayern munich': 'BAY', 'бавария': 'BAY',
    'maccabi tel aviv': 'MTA', 'маккаби': 'MTA',
    'panathinaikos': 'PAN', 'панатинаикос': 'PAN',
    'zalgiris': 'ZAL', 'žalgiris': 'ZAL', 'жальгирис': 'ZAL',
    'baskonia': 'BAS', 'баскония': 'BAS',
    'virtus bologna': 'VIR', 'виртус': 'VIR',
    'ax armani exchange': 'MIL', 'armani milano': 'MIL',
    'alba berlin': 'ALB', 'as monaco': 'MON', 'monaco': 'MON', 'монако': 'MON',
    'paris basketball': 'PAR', 'paris': 'PAR',
}


# ── Helpers ────────────────────────────────────────────────────────────────────
def make_abbr(name: str) -> str:
    """Return a proper team abbreviation using a lookup table, then initials fallback."""
    if not name:
        return '???'
    key = name.strip().lower()
    # Exact lookup
    if key in _TEAM_ABBR:
        return _TEAM_ABBR[key]
    # Partial lookup: check if any known key is a substring of (or equal to) the name
    for team_key, abbr in _TEAM_ABBR.items():
        if team_key in key:
            return abbr
    # Fallback: first letter of each significant word (up to 3)
    words = [re.sub(r'[^A-Za-zА-Яа-яЁё]', '', w) for w in name.split()]
    words = [w for w in words if len(w) >= 2]
    if len(words) >= 3:
        return ''.join(w[0] for w in words[:3]).upper()
    elif len(words) == 2:
        return (words[0][0] + words[1][:2]).upper()
    elif len(words) == 1:
        return words[0][:3].upper()
    return name[:3].upper()


def empty_team() -> dict:
    return {
        "name": "", "abbr": "", "logo": "",
        "total": "", "q1": "", "q2": "", "q3": "", "q4": "", "ot": "",
        "FG": "", "3P": "", "FT": "",
        "REB": "", "AST": "", "TOV": "", "PF": ""
    }


def empty_result() -> dict:
    return {
        "status": "scheduled",
        "quarter": "",
        "time": "",
        "home": empty_team(),
        "away": empty_team()
    }


def empty_player(match_key: str = '') -> dict:
    return {
        'schema_version': 2,
        'visible': False,
        'mode': 'hidden',
        'updated_at': '',
        'source': 'scraper',
        'team_side': '',
        'match_key': match_key,
        'name': '',
        'number': '',
        'position': '',
        'team': '',
        'photo': '',
        'photo_source': '',
        'photo_status': '',
        'stats': {
            'PPG': '',
            'RPG': '',
            'APG': '',
            'STL': '',
            'BLK': '',
            'FG': '',
            '3P': '',
            'FT': '',
            'MIN': '',
        },
    }


def now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def write_json_atomic(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(data, dict):
        meta = data.get('_meta') if isinstance(data.get('_meta'), dict) else {}
        meta.update({
            'updated_at': now_iso(),
            'source': meta.get('source') or 'scraper',
            'schema_version': meta.get('schema_version') or data.get('schema_version') or 1,
            'generation': int(meta.get('generation') or 0) + 1,
        })
        data['_meta'] = meta
    fd, tmp_path = tempfile.mkstemp(prefix='.tmp-', suffix='.json', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        root, ext = os.path.splitext(path)
        if ext.lower() == '.json':
            last_good_path = f'{root}.last_good.json'
            fd2, tmp_last_good = tempfile.mkstemp(prefix='.tmp-last-good-', suffix='.json', dir=os.path.dirname(path))
            try:
                with os.fdopen(fd2, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_last_good, last_good_path)
            finally:
                if os.path.exists(tmp_last_good):
                    os.remove(tmp_last_good)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def read_json_dict(path: str) -> dict:
    root, ext = os.path.splitext(path)
    candidates = [path]
    if ext.lower() == '.json':
        candidates.append(f'{root}.last_good.json')
    for candidate in candidates:
        try:
            with open(candidate, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def _cfg_bool(cfg: dict, key: str, default: bool) -> bool:
    raw = cfg.get(key, default)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in ('1', 'true', 'yes', 'on')
    if isinstance(raw, (int, float)):
        return bool(raw)
    return default


def clear_player_cache():
    if not os.path.isdir(PLAYER_CACHE_DIR):
        return
    for name in os.listdir(PLAYER_CACHE_DIR):
        path = os.path.join(PLAYER_CACHE_DIR, name)
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass


def _to_float(value: str) -> float:
    try:
        return float(str(value).replace(',', '.'))
    except Exception:
        return 0.0


def _normalize_name(value: str) -> str:
    txt = re.sub(r'[^A-Za-zА-Яа-яЁё\s\-\']', ' ', value or '').lower()
    txt = re.sub(r'\s+', ' ', txt).strip()
    return txt


_CYR_TO_LAT = str.maketrans({
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e',
    'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
    'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
    'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
    'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
})

NBA_NAME_HINTS = {
    'wembanyama': '1641705', 'vembanyama': '1641705', 'вембаньяма': '1641705',
    'gilgeous alexander': '1628983', 'gildzhes aleksander': '1628983', 'гилджес александер': '1628983',
    'fox': '1628368', 'foks': '1628368', 'фокс': '1628368',
    'vassell': '1630170', 'vassel': '1630170', 'васселл': '1630170',
    'castle': '1642264', 'kasl': '1642264', 'касл': '1642264',
    'holmgren': '1631096', 'холмгрен': '1631096',
    'jalen williams': '1631114', 'williams': '1631114', 'уильямс': '1631114',
    'keldon johnson': '1629640', 'johnson': '1629640', 'джонсон': '1629640',
    'chris paul': '101108', 'paul': '101108', 'пол': '101108',
    'harrison barnes': '203084', 'barnes': '203084', 'барнс': '203084',
    'dort': '1629652', 'дорту': '1629652',
    'hartenstein': '1628392', 'хартенштейн': '1628392',
    'caruso': '1627936', 'карузо': '1627936',
    'wallace': '1641717', 'уоллес': '1641717',
    'champagnie': '1630577', 'шампани': '1630577',
    'sochan': '1631110', 'сохан': '1631110',
    'tre jones': '1630200', 'jones': '1630200', 'джонс': '1630200',
    'brunson': '1628973', 'брансон': '1628973',
    'anunoby': '1628384', 'ануноби': '1628384', 'og anunoby': '1628384',
    'mikal bridges': '1628969', 'bridges': '1628969', 'бриджес': '1628969',
    'towns': '1626157', 'таунс': '1626157',
    'josh hart': '1628404', 'hart': '1628404', 'харт': '1628404',
    'mitchell': '1628378', 'митчелл': '1628378',
    'mobley': '1630596', 'мобли': '1630596',
    'garland': '1629636', 'гарланд': '1629636',
    'jarrett allen': '1628386', 'allen': '1628386', 'аллен': '1628386',
    'strus': '1629622', 'струс': '1629622',
    'deuce mcbride': '1630540', 'mcbride': '1630540', 'макбрайд': '1630540',
}


def _latinize_name(value: str) -> str:
    text = str(value or '').lower().translate(_CYR_TO_LAT)
    text = text.replace('dzhes', 'geous').replace('dzh', 'j').replace('ks', 'x')
    text = re.sub(r'[^a-z\s\-\']', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def is_nba_match(url: str, result: dict) -> bool:
    url_has_nba = 'nba' in (url or '').lower()
    home_abbr = str(result.get('home', {}).get('abbr', '')).upper()
    away_abbr = str(result.get('away', {}).get('abbr', '')).upper()
    teams_are_nba = home_abbr in NBA_ABBRS and away_abbr in NBA_ABBRS
    return teams_are_nba or url_has_nba


def _read_cached_nba_players() -> list[dict]:
    try:
        with open(NBA_PLAYERS_CACHE_PATH, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _write_cached_nba_players(players: list[dict]) -> None:
    if not players:
        return
    try:
        os.makedirs(os.path.dirname(NBA_PLAYERS_CACHE_PATH), exist_ok=True)
        with open(NBA_PLAYERS_CACHE_PATH, 'w', encoding='utf-8') as f:
            json.dump(players, f, ensure_ascii=False)
    except OSError:
        pass


def _nba_roster() -> list[dict]:
    ttl = 3600.0
    now_ts = time.time()
    if _NBA_ROSTER_CACHE['players'] and (now_ts - _NBA_ROSTER_CACHE['at'] < ttl):
        return _NBA_ROSTER_CACHE['players']

    endpoint = 'https://cdn.nba.com/static/json/liveData/players.json'
    req = urllib.request.Request(
        endpoint,
        headers={
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
            )
        },
    )
    players = []
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode('utf-8', errors='ignore'))
        players = payload.get('league', {}).get('standard', [])
    except Exception:
        try:
            season_start = datetime.datetime.now(datetime.UTC).year
            if datetime.datetime.now(datetime.UTC).month < 7:
                season_start -= 1
            season = f'{season_start}-{str(season_start + 1)[-2:]}'
            stats_url = (
                'https://stats.nba.com/stats/commonallplayers'
                f'?LeagueID=00&Season={season}&IsOnlyCurrentSeason=1'
            )
            stats_req = urllib.request.Request(
                stats_url,
                headers={
                    'Host': 'stats.nba.com',
                    'Accept': 'application/json, text/plain, */*',
                    'Origin': 'https://www.nba.com',
                    'Referer': 'https://www.nba.com/',
                    'User-Agent': (
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
                    ),
                    'x-nba-stats-origin': 'stats',
                    'x-nba-stats-token': 'true',
                },
            )
            with urllib.request.urlopen(stats_req, timeout=15) as resp:
                payload = json.loads(resp.read().decode('utf-8', errors='ignore'))
            result_sets = payload.get('resultSets', [])
            first_set = result_sets[0] if result_sets else {}
            headers = first_set.get('headers', [])
            rows = first_set.get('rowSet', [])
            idx = {name: i for i, name in enumerate(headers)}
            players = []
            for row in rows:
                full_name = str(row[idx.get('DISPLAY_FIRST_LAST', 2)]).strip()
                parts = full_name.split()
                players.append({
                    'firstName': parts[0] if parts else '',
                    'lastName': ' '.join(parts[1:]) if len(parts) > 1 else '',
                    'personId': str(row[idx.get('PERSON_ID', 0)]).strip(),
                })
        except Exception as e:
            log.warning(f'NBA roster fetch failed, trying local cache: {e}')
            cached = _read_cached_nba_players()
            if cached:
                _NBA_ROSTER_CACHE['players'] = cached
                _NBA_ROSTER_CACHE['at'] = now_ts
                return cached
            return []
    players = players if isinstance(players, list) else []
    normalized = [p for p in players if isinstance(p, dict)]
    if normalized:
        _write_cached_nba_players(normalized)
    _NBA_ROSTER_CACHE['players'] = normalized
    _NBA_ROSTER_CACHE['at'] = now_ts
    return _NBA_ROSTER_CACHE['players']


def find_nba_player_id(full_name: str) -> str:
    target = _normalize_name(full_name)
    target_latin = _latinize_name(full_name)
    if not target and not target_latin:
        return ''

    hint_key = target.replace('-', ' ')
    hint_latin = target_latin.replace('-', ' ')
    for key, pid in NBA_NAME_HINTS.items():
        if key in hint_key or key in hint_latin or hint_latin.split(' ')[0:1] == [key]:
            return pid

    exact = ''
    best_pid = ''
    best_score = 0.0
    target_parts = target_latin.split()
    target_surname = target_parts[0] if target_parts else ''
    target_initial = target_parts[1][0] if len(target_parts) > 1 and target_parts[1] else ''

    for p in _nba_roster():
        first_name = str(p.get('firstName', '')).strip()
        last_name = str(p.get('lastName', '')).strip()
        pid = str(p.get('personId', '')).strip()
        if not pid:
            continue
        name = _normalize_name(f'{first_name} {last_name}')
        first_norm = _normalize_name(first_name)
        last_norm = _normalize_name(last_name)
        if not name:
            continue

        if name == target or name == target_latin:
            exact = pid
            break

        if target and target in name and best_score < 0.9:
            best_pid = pid
            best_score = 0.9

        if target_latin and target_latin in name and best_score < 0.92:
            best_pid = pid
            best_score = 0.92

        if target_surname and last_norm:
            surname_score = difflib.SequenceMatcher(None, target_surname, last_norm).ratio()
            if first_norm and target_initial and first_norm.startswith(target_initial):
                surname_score += 0.08
            if surname_score > best_score:
                best_pid = pid
                best_score = surname_score

    return exact or (best_pid if best_score >= 0.78 else '')


def download_nba_headshot(person_id: str) -> str:
    if not person_id:
        return ''
    safe_id = urllib.parse.quote(person_id)
    remote = f'https://cdn.nba.com/headshots/nba/latest/1040x760/{safe_id}.png'
    local_name = f'{person_id}.png'
    local_path = os.path.join(PLAYER_CACHE_DIR, local_name)
    req = urllib.request.Request(
        remote,
        headers={
            'Referer': 'https://www.nba.com/',
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
            ),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        if len(data) < 1000:
            return ''
        os.makedirs(PLAYER_CACHE_DIR, exist_ok=True)
        with open(local_path, 'wb') as f:
            f.write(data)
        return f'json/players/{local_name}'
    except (urllib.error.URLError, OSError, ValueError):
        return ''


def _sportsdb_photo_url(player_name: str) -> str:
    target = _latinize_name(player_name)
    tokens = [t for t in target.split() if t]
    if not tokens:
        return ''

    queries: list[str] = []
    full = ' '.join(tokens)
    if full:
        queries.append(full)
    surname = tokens[0]
    if surname and surname not in queries:
        queries.append(surname)

    for query in queries:
        if len(query) < 3:
            continue
        endpoint = (
            'https://www.thesportsdb.com/api/v1/json/3/searchplayers.php?p='
            f'{urllib.parse.quote(query)}'
        )
        req = urllib.request.Request(
            endpoint,
            headers={
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
                )
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode('utf-8', errors='ignore'))
        except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError):
            continue

        players = payload.get('player', []) if isinstance(payload, dict) else []
        if not isinstance(players, list):
            continue

        best_url = ''
        best_score = 0.0
        for item in players:
            if not isinstance(item, dict):
                continue
            sport = str(item.get('strSport', '')).strip().lower()
            if sport and sport != 'basketball':
                continue
            display_name = _latinize_name(str(item.get('strPlayer', '')))
            score = 0.0
            if display_name:
                score = difflib.SequenceMatcher(None, display_name, full).ratio()
                if surname and surname in display_name:
                    score += 0.2

            image_url = (
                str(item.get('strThumb', '')).strip()
                or str(item.get('strCutout', '')).strip()
                or str(item.get('strRender', '')).strip()
                or str(item.get('strFanart1', '')).strip()
            )
            if not image_url:
                continue

            if score > best_score:
                best_score = score
                best_url = image_url

        if best_url:
            return best_url

    return ''


def _download_external_photo(photo_url: str, prefix: str = 'ext') -> str:
    if not photo_url:
        return ''
    digest = hashlib.sha1(photo_url.encode('utf-8', errors='ignore')).hexdigest()[:12]
    path = urllib.parse.urlparse(photo_url).path
    _, ext = os.path.splitext(path)
    ext = ext.lower() if ext else '.jpg'
    if ext not in {'.png', '.jpg', '.jpeg', '.webp'}:
        ext = '.jpg'
    local_name = f'{prefix}_{digest}{ext}'
    local_path = os.path.join(PLAYER_CACHE_DIR, local_name)
    req = urllib.request.Request(
        photo_url,
        headers={
            'Referer': 'https://www.thesportsdb.com/',
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
            ),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        if len(data) < 1000:
            return ''
        os.makedirs(PLAYER_CACHE_DIR, exist_ok=True)
        with open(local_path, 'wb') as f:
            f.write(data)
        return f'json/players/{local_name}'
    except (urllib.error.URLError, OSError, ValueError):
        return ''


def el_text(driver, css: str) -> str:
    try:
        return driver.find_element(By.CSS_SELECTOR, css).text.strip()
    except Exception:
        return ''


def els_text(driver, css: str) -> list:
    try:
        return [e.text.strip() for e in driver.find_elements(By.CSS_SELECTOR, css)]
    except Exception:
        return []


# Stats label → result key mapping (English + Russian/KZ Flashscore labels)
STAT_MAP = [
    (['field goals made', 'field goals', 'shots from play', 'fg made', 'field goal',
      'бросков с игры всего', 'бросков с игры реал', 'бросков с игры', 'броски с игры'], 'FG'),
    (['3-point field goals', '3pt', 'three point', '3 point', 'from 3', '3-pt',
      '3-х бросков', 'трёхочков', 'трехочков', '3-очков', '3 очков'], '3P'),
    (['free throws made', 'free throws', 'ft made',
      '1-х бросков', 'штрафные броски', 'штрафных', 'штрафные'], 'FT'),
    (['total rebounds', 'rebounds total',
      'всего подборов', 'всего подбор'], 'REB'),
    (['assists', 'ast',
      'передачи', 'передач', 'результативные'], 'AST'),
    (['turnovers', 'turn over', 'tov',
      'потери', 'потерь'], 'TOV'),
    (['personal fouls', 'total fouls', 'fouls', 'pf',
      'персональные фолы', 'фолы', 'фолов', 'нарушени', 'персональные'], 'PF'),
]


def map_stat_key(label_lower: str):
    for keywords, key in STAT_MAP:
        for kw in keywords:
            if kw in label_lower:
                return key
    return None


# ── Logo extraction ───────────────────────────────────────────────────────────
def get_logo_url(driver, side: str) -> str:
    """Extract team logo URL from Flashscore duelParticipant section."""
    # CSS selectors ordered by specificity
    selectors = [
        f'.duelParticipant__{side} [class*="participant__image"] img',
        f'.duelParticipant__{side} [class*="participant__logo"] img',
        f'.duelParticipant__{side} [class*="teamLogo"] img',
        f'.duelParticipant__{side} [class*="logo"] img',
    ]
    for sel in selectors:
        try:
            img = driver.find_element(By.CSS_SELECTOR, sel)
            src = img.get_attribute('src') or img.get_attribute('data-src') or ''
            if src and src.startswith('http') and 'spacer' not in src.lower():
                log.info(f'Logo {side}: {src!r}')
                return src
        except Exception:
            pass
    # JS fallback — scan all imgs inside the participant container
    try:
        src = driver.execute_script(f"""
            const c = document.querySelector('.duelParticipant__{side}');
            if (!c) return '';
            for (const img of c.querySelectorAll('img')) {{
                const s = img.src || img.getAttribute('data-src') || '';
                if (s && s.startsWith('http') && !s.toLowerCase().includes('spacer')) return s;
            }}
            return '';
        """) or ''
        if src:
            log.info(f'Logo {side} (JS): {src!r}')
            return src
    except Exception as e:
        log.debug(f'Logo JS: {e}')
    return ''


def download_logo(url: str, dest_path: str) -> bool:
    """Download a logo image to disk. Returns True on success."""
    if not url:
        return False
    try:
        req = urllib.request.Request(
            url,
            headers={
                'Referer': 'https://www.flashscorekz.com/',
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                ),
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
        if len(data) > 200:
            with open(dest_path, 'wb') as f:
                f.write(data)
            log.info(f'Logo saved: {dest_path!r}')
            return True
    except Exception as e:
        log.debug(f'download_logo: {e}')
    return False


# ── Chrome driver ──────────────────────────────────────────────────────────────
def get_driver() -> ChromeWebDriver:
    opts = Options()
    opts.add_argument('--headless=new')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--window-size=1920,1080')
    opts.add_argument('--disable-blink-features=AutomationControlled')
    opts.add_experimental_option('excludeSwitches', ['enable-automation'])
    opts.add_experimental_option('useAutomationExtension', False)
    opts.add_argument(
        'user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36'
    )
    chrome_path = r'C:\Users\Evgeniy\AppData\Local\Google\Chrome\Application\chrome.exe'
    if os.path.exists(chrome_path):
        opts.binary_location = chrome_path
        log.info(f"Using Chrome at {chrome_path}")
    svc = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=svc, options=opts)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    log.info("Chrome launched OK")
    return driver


# ── Scraper ────────────────────────────────────────────────────────────────────
def close_consent(driver):
    for sel in [
        '#onetrust-accept-btn-handler',
        'button.fc-button.fc-cta-consent',
        '[aria-label="Accept All"]',
        '[class*="cookieBanner"] button',
    ]:
        try:
            driver.find_element(By.CSS_SELECTOR, sel).click()
            time.sleep(0.8)
            return
        except Exception:
            pass


def parse_quarter_scores(driver, result: dict):
    """Try multiple strategies to fill q1-q4 and ot for home/away."""
    q_keys = ['q1', 'q2', 'q3', 'q4', 'ot']

    # Strategy A (primary): smh__part elements (current Flashscore SPA structure)
    try:
        # Wait briefly for quarter elements to render
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '[class*="smh__part--1"]'))
            )
        except Exception:
            pass
        found_any = False
        for i, k in enumerate(q_keys, 1):
            h_val = el_text(driver, f'[class*="smh__home"][class*="smh__part--{i}"]')
            a_val = el_text(driver, f'[class*="smh__away"][class*="smh__part--{i}"]')
            if h_val or a_val:
                result['home'][k] = h_val
                result['away'][k] = a_val
                found_any = True
        if found_any:
            log.info(f"smh__ quarters — H: {[result['home'][k] for k in q_keys]} A: {[result['away'][k] for k in q_keys]}")
            return True
    except Exception as e:
        log.debug(f"smh__ strategy: {e}")

    # Strategy B: duelParticipant partialScore spans
    for side, sel in [
        ('home', '.duelParticipant__home [class*="partialScore"]'),
        ('away', '.duelParticipant__away [class*="partialScore"]'),
    ]:
        vals = els_text(driver, sel)
        if vals:
            log.info(f"partialScore {side}: {vals}")
            for i, k in enumerate(q_keys):
                if i < len(vals):
                    result[side][k] = vals[i]
            return True

    # Strategy B: matchDetailPeriods table - all period score cells
    # Structure: header row (1 2 3 4 OT), home row, away row
    try:
        all_cells = driver.find_elements(
            By.CSS_SELECTOR, '[class*="matchDetailPeriods__periodScore"]'
        )
        vals = [c.text.strip() for c in all_cells]
        log.info(f"matchDetailPeriods__periodScore cells: {vals}")
        n = len(q_keys)
        if len(vals) >= n * 2:
            for i, k in enumerate(q_keys):
                result['home'][k] = vals[i] if i < len(vals) else ''
                result['away'][k] = vals[i + n] if i + n < len(vals) else ''
            return True
    except Exception as e:
        log.debug(f"matchDetailPeriods: {e}")

    # Strategy C: smv__periodsData numeric cells
    try:
        period_cells = driver.find_elements(
            By.CSS_SELECTOR, '[class*="smv__periodsData"] [class*="smv__score"]'
        )
        vals = [c.text.strip() for c in period_cells if re.match(r'^\d+$', c.text.strip())]
        log.info(f"smv__score numeric vals: {vals}")
        n = len(q_keys)
        if len(vals) >= n * 2:
            for i, k in enumerate(q_keys):
                result['home'][k] = vals[i]
                result['away'][k] = vals[i + n]
            return True
    except Exception as e:
        log.debug(f"smv: {e}")

    # Strategy D: JS dump any periods container and parse numbers
    try:
        info = driver.execute_script("""
            const sels = [
                '[class*="periodsData"]',
                '[class*="periodRow"]',
                '[class*="periodScore"]',
                '[class*="matchDetailScore"]',
            ];
            for (const s of sels) {
                const el = document.querySelector(s);
                if (el && el.innerText.trim()) return el.innerText;
            }
            return null;
        """)
        if info:
            log.info(f"JS period dump: {info!r}")
            nums = re.findall(r'\b(\d{1,3})\b', info)
            log.info(f"Extracted numbers: {nums}")
            n = len(q_keys)
            if len(nums) >= n * 2:
                for i, k in enumerate(q_keys):
                    result['home'][k] = nums[i]
                    result['away'][k] = nums[i + n]
                return True
    except Exception as e:
        log.debug(f"JS strategy: {e}")

    log.warning("Could not parse quarter scores with any strategy")
    return False


def _stats_base_url(driver) -> str:
    """Return base URL with query string but without hash fragment."""
    cur = driver.current_url
    return re.sub(r'#.*', '', cur).rstrip('/')


def parse_stats(driver, result: dict):
    """Extract FG/3P/FT/REB/AST/TOV/PF from the page."""

    # Strategy 1: try to click the СТАТИСТИКА subtab (not сТАТИСТИКА ИГРОКОВ)
    try:
        clicked = driver.execute_script("""
            const tabs = [...document.querySelectorAll(
                '[class*="filterOver__a"], [class*="menuMinority__item"], [class*="tabs__tab"]'
            )];
            const statsTab = tabs.find(t => {
                const txt = (t.innerText || '').trim();
                return txt === '\u0421\u0422\u0410\u0422\u0418\u0421\u0422\u0418\u041a\u0410' || txt.toLowerCase() === 'statistics' || txt.toLowerCase() === 'stats';
            });
            if (statsTab) { statsTab.click(); return true; }
            return false;
        """)
        if clicked:
            log.info("Clicked \u0421\u0422\u0410\u0422\u0418\u0421\u0422\u0418\u041a\u0410 tab")
            time.sleep(2)
    except Exception as e:
        log.debug(f"Tab click: {e}")

    # Strategy 2: navigate directly to stats URL (keeping ?mid= param)
    try:
        base = _stats_base_url(driver)
        # Build /summary/stats/ URL preserving ?mid= param
        import urllib.parse as _up
        parsed_url = _up.urlparse(base)
        stats_path = re.sub(r'/(?:summary|stats).*$', '', parsed_url.path).rstrip('/') + '/summary/stats/'
        stats_url = _up.urlunparse(parsed_url._replace(path=stats_path))
        driver.get(stats_url)
        log.info(f"Navigated to stats URL: {stats_url}")
        time.sleep(2)
    except Exception as e:
        log.warning(f"Could not navigate to stats: {e}")
        return

    # Try clicking "БОЛЬШЕ" / "MORE" expand button to reveal full stats
    try:
        expanded = driver.execute_script("""
            const btn = document.querySelector('[class*="extraContent__button"]');
            if (btn) { btn.click(); return true; }
            return false;
        """)
        if expanded:
            log.info("Clicked extraContent expand button")
            time.sleep(1)
    except Exception as e:
        log.debug(f"Expand button: {e}")

    # Strategy 3: parse wcl-row_* elements (current Flashscore SPA structure)
    row_els = driver.find_elements(By.CSS_SELECTOR, '[class*="wcl-row_"]')
    log.info(f"wcl-row_ elements found: {len(row_els)}")
    parsed = 0
    seen_keys = set()
    for row in row_els:
        try:
            txt = row.text.strip()
            parts = [p.strip() for p in txt.split('\n') if p.strip()]
            if len(parts) >= 3:
                home_val, label, away_val = parts[0], parts[1], parts[2]
                key = map_stat_key(label.lower())
                if key and key not in seen_keys:
                    # Skip percentage rows for FG/3P/FT (we want made/attempted, not %)
                    if home_val.endswith('%') or away_val.endswith('%'):
                        log.debug(f"  Skip % row for {key}: {home_val}/{away_val}")
                        continue
                    result['home'][key] = home_val
                    result['away'][key] = away_val
                    log.info(f"  wcl-row {key}: {home_val} / {away_val}")
                    parsed += 1
                    seen_keys.add(key)
        except Exception as e:
            log.debug(f"wcl-row parse error: {e}")

    if parsed > 0:
        log.info(f"Parsed {parsed} stats via wcl-row_")
        return

    # Fallback: old stat__row strategy
    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                '[class*="stat__row"],[class*="statRow"],[class*="stat__category"]'))
        )
    except Exception:
        pass

    stat_rows = driver.find_elements(By.CSS_SELECTOR, '[class*="stat__row"]')
    if not stat_rows:
        stat_rows = driver.find_elements(By.CSS_SELECTOR, '[class*="statRow"]')
    log.info(f"Stat rows found (fallback): {len(stat_rows)}")

    for row in stat_rows:
        try:
            row_text = row.text.strip()
            if not row_text:
                continue
            log.debug(f"Stat row: {row_text!r}")

            label = ''
            for lsel in ['[class*="stat__category"]', '[class*="stat__name"]',
                         '[class*="statCategory"]', '[class*="statName"]']:
                try:
                    label = row.find_element(By.CSS_SELECTOR, lsel).text.lower()
                    break
                except Exception:
                    pass

            if not label:
                parts = [p.strip() for p in row_text.split('\n') if p.strip()]
                if len(parts) >= 3:
                    label = parts[1].lower()
                elif len(parts) == 1:
                    m = re.match(r'^([\d/]+)\s+(.+?)\s+([\d/]+)$', parts[0])
                    if m:
                        label = m.group(2).lower()
                        key = map_stat_key(label)
                        if key:
                            result['home'][key] = m.group(1)
                            result['away'][key] = m.group(3)
                    continue

            key = map_stat_key(label)
            if not key:
                continue

            val_els = row.find_elements(By.CSS_SELECTOR,
                '[class*="stat__teamValue"], [class*="statValue"], [class*="stat__value"]')
            if len(val_els) >= 2:
                result['home'][key] = val_els[0].text.strip()
                result['away'][key] = val_els[-1].text.strip()
                log.info(f"  {key}: {result['home'][key]} / {result['away'][key]}")
            else:
                nums = re.findall(r'[\d/]+', row_text)
                if len(nums) >= 2:
                    result['home'][key] = nums[0]
                    result['away'][key] = nums[-1]
                    log.info(f"  {key} (fallback): {nums[0]} / {nums[-1]}")
        except Exception as e:
            log.debug(f"stat row error: {e}")


def _fmt_stat(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f'{value:.1f}'


def _player_extra_stats(raw_nums: list) -> dict:
    if not isinstance(raw_nums, list) or len(raw_nums) < 9:
        return {'FG': '', '3P': '', 'FT': '', 'MIN': '', 'PLUS_MINUS': '', 'TOV': '', 'PF': ''}

    def _raw(idx: int) -> str:
        if idx >= len(raw_nums):
            return ''
        return str(raw_nums[idx]).strip()

    def _pair(made_idx: int, attempt_idx: int) -> str:
        made = _raw(made_idx)
        attempt = _raw(attempt_idx)
        if not made or not attempt:
            return ''
        made_num = _to_float(made)
        attempt_num = _to_float(attempt)
        if made_num < 0 or attempt_num < made_num:
            return ''
        return f'{made} / {attempt}'

    return {
        'FG': _pair(3, 4),
        '3P': _pair(5, 6),
        'FT': _pair(7, 8),
        'MIN': '',
        'PLUS_MINUS': _raw(9),
        'TOV': _raw(len(raw_nums) - 1) if len(raw_nums) >= 12 else '',
        'PF': _raw(len(raw_nums) - 2) if len(raw_nums) >= 12 else '',
    }


def _clean_player_name(value: str) -> str:
    text = str(value or '').replace('\n', ' ').strip()
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'^\d+\s+', '', text)
    return text.strip()


def _extract_player_rows(driver) -> list[dict]:
    try:
        rows = driver.execute_script("""
            const allRows = [...document.querySelectorAll(
                '[class*="ui-table__row"], [class*="playerStatsTable__row"], [class*="lineup__row"], [class*="participant"], tr'
            )];
            const out = [];

            function guessNameFromText(raw) {
                const parts = raw.split('\\n').map(x => x.trim()).filter(Boolean);
                for (const p of parts) {
                    if (/^\\d+$/.test(p)) continue;
                    if (/^\\d{1,2}:\\d{2}$/.test(p)) continue;
                    if (/^[A-Z]{2,4}$/.test(p)) continue;
                    if (p.length < 3) continue;
                    return p;
                }
                return '';
            }

            function extractNums(parts, text) {
                const nums = [];
                for (const p of parts) {
                    if (/^-?\\d+(?:[.,]\\d+)?$/.test(p)) nums.push(p);
                }
                if (nums.length) return nums;
                return text.match(/-?\\d+(?:[.,]\\d+)?/g) || [];
            }

            for (const row of allRows) {
                const text = (row.innerText || '').trim();
                if (!text) continue;
                const parts = text.split('\\n').map(x => x.trim()).filter(Boolean);
                const nums = extractNums(parts, text);

                let name = '';
                const nameEl = row.querySelector(
                    '[class*="participant__participantName"], [class*="playerName"], [class*="name"], [class*="Name"], a, span'
                );
                if (nameEl) name = (nameEl.innerText || '').trim();
                if (!name) name = guessNameFromText(text);
                if (!name) continue;

                let playerUrl = '';
                const playerAnchor = row.querySelector('a[href*="/player/"]');
                if (playerAnchor) playerUrl = (playerAnchor.getAttribute('href') || '').trim();

                let photoUrl = '';
                const img = row.querySelector('img[src]');
                if (img) photoUrl = (img.getAttribute('src') || '').trim();

                name = name.replace(/^\\d+\\s+/, '').replace(/\\s+/g, ' ').trim();

                // Skip obviously non-player labels/noise.
                if (/^(home|away|summary|statistics|stats|totals?)$/i.test(name)) continue;
                if (name.length < 3 || name.length > 48) continue;

                let side = '';
                const sideScope = row.closest('[class*="home"], [class*="away"], [class*="participant"]');
                const sideText = ((row.className || '') + ' ' + (sideScope ? sideScope.className : '')).toLowerCase();
                if (sideText.includes('home')) side = 'home';
                else if (sideText.includes('away')) side = 'away';

                out.push({ name, side, nums, player_url: playerUrl, photo_url: photoUrl });
            }

            return out;
        """)
        return rows if isinstance(rows, list) else []
    except Exception as e:
        log.debug(f'Player rows extract failed: {e}')
        return []


def _player_stats_urls(match_url: str) -> list[str]:
    """Build likely player statistics URLs for both old and new Flashscore routing."""
    base = re.sub(r'#.*', '', match_url).rstrip('/')
    urls: list[str] = []

    # Legacy hash routes used by previous Flashscore SPA versions.
    urls.extend([
        base + '#/match-summary/player-statistics',
        base + '#/match-summary/player-statistics/0',
        base + '#/match-summary/player-statistics/player-statistics',
        base + '#/match-summary/player-stats/overall',
        base + '#/match-summary/player-stats/home-away',
    ])

    # Modern route style: /summary/player-stats/... (preserve query like ?mid=...)
    try:
        parsed = urllib.parse.urlparse(base)
        root_path = re.sub(r'/(?:summary|stats).*$', '', parsed.path).rstrip('/')
        modern_paths = [
            root_path + '/summary/player-stats/overall/',
            root_path + '/summary/player-stats/home-away/',
            root_path + '/summary/player-stats/',
            root_path + '/summary/player-statistics/',
            root_path + '/summary/player-statistics/home-away/',
        ]
        for path in modern_paths:
            urls.append(urllib.parse.urlunparse(parsed._replace(path=path, fragment='')))
    except Exception:
        pass

    # Keep order stable and remove accidental duplicates.
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(url)
    return unique


def _lineups_url(match_url: str) -> str:
    """Build summary lineups URL preserving query params."""
    base = re.sub(r'#.*', '', match_url).rstrip('/')
    parsed = urllib.parse.urlparse(base)
    root_path = re.sub(r'/(?:summary|stats).*$', '', parsed.path).rstrip('/')
    path = root_path + '/summary/lineups/'
    return urllib.parse.urlunparse(parsed._replace(path=path, fragment=''))


def _extract_lineup_rows(driver, match_url: str) -> list[dict]:
    """Fallback extraction from lineups page when player stats are unavailable."""
    try:
        lineup_url = _lineups_url(match_url)
        driver.get(lineup_url)
        time.sleep(1.8)

        rows = driver.execute_script("""
            const nodes = [...document.querySelectorAll(
                'a[href*="/player/"], [class*="lineup"] [class*="name"], [class*="lineUp"] [class*="name"], [class*="playerName"]'
            )];
            const out = [];
            for (const el of nodes) {
                const name = (el.innerText || '').trim();
                let cleanName = name.replace(/^\\d+\\s+/, '').replace(/\\s+/g, ' ').trim();
                if (!cleanName) continue;
                if (cleanName.length < 3 || cleanName.length > 48) continue;
                if (/^[A-Z]{2,4}$/.test(cleanName)) continue;

                let playerUrl = '';
                if (el.tagName && el.tagName.toLowerCase() === 'a') {
                    playerUrl = (el.getAttribute('href') || '').trim();
                } else {
                    const a = el.closest('a[href*="/player/"]');
                    if (a) playerUrl = (a.getAttribute('href') || '').trim();
                }

                let photoUrl = '';
                const photoScope = el.closest('[class*="lineup"], [class*="lineUp"], [class*="player"]') || el.parentElement;
                if (photoScope) {
                    const img = photoScope.querySelector('img[src]');
                    if (img) photoUrl = (img.getAttribute('src') || '').trim();
                }

                let side = '';
                const sideScope = el.closest('[class*="home"], [class*="away"], [class*="lineup__home"], [class*="lineup__away"]');
                const sideText = ((el.className || '') + ' ' + (sideScope ? sideScope.className : '')).toLowerCase();
                if (sideText.includes('home')) side = 'home';
                else if (sideText.includes('away')) side = 'away';

                out.push({ name: cleanName, side, nums: [], player_url: playerUrl, photo_url: photoUrl });
            }
            return out;
        """)
        return rows if isinstance(rows, list) else []
    except Exception as e:
        log.debug(f'Lineups fallback extract failed: {e}')
        return []


def _extract_rows_via_player_tab(driver, match_url: str) -> list[dict]:
    """Open match summary and click player stats tab directly in SPA navigation."""
    try:
        base = re.sub(r'#.*', '', match_url).rstrip('/')
        driver.get(base + '#/match-summary/match-summary')
        time.sleep(2.0)
        close_consent(driver)

        clicked = driver.execute_script("""
            const target = [...document.querySelectorAll('a[href*="player-stats"], a[href*="player-statistics"]')][0];
            if (!target) {
                return false;
            }
            target.click();
            return true;
        """)

        if not clicked:
            return []

        rows: list[dict] = []
        for _ in range(25):
            time.sleep(0.8)
            rows = _extract_player_rows(driver)
            has_stat_rows = any(
                isinstance(r.get('nums'), list) and len(r.get('nums')) >= 3
                for r in rows
                if isinstance(r, dict)
            )
            if has_stat_rows:
                break

        log.info(f'Player rows via tab-click: {len(rows)} url={driver.current_url}')
        return rows
    except Exception as e:
        log.debug(f'Player tab-click extract failed: {e}')
        return []


def parse_player_from_match(
    driver,
    result: dict,
    match_url: str,
    strict_match_players_only: bool = True,
    dump_player_candidates: bool = True,
) -> dict:
    player = empty_player(match_key=match_url)
    player['updated_at'] = now_iso()
    player['source'] = 'scraper-sync'

    candidates = _player_stats_urls(match_url)

    best = None
    debug_candidates: list[dict] = []
    seen_candidates: set[str] = set()

    lineup_rows = _extract_lineup_rows(driver, match_url)
    lineup_side_by_name: dict[str, str] = {}
    for row in lineup_rows:
        if not isinstance(row, dict):
            continue
        lineup_name = _clean_player_name(row.get('name', ''))
        lineup_side = str(row.get('side', '')).strip().lower()
        if lineup_name and lineup_side in ('home', 'away'):
            lineup_side_by_name[lineup_name.lower()] = lineup_side

    if lineup_side_by_name:
        log.info(f'Lineup side map prepared: {len(lineup_side_by_name)} players')
    else:
        log.info('Lineup side map is empty; fallback to row side detection only')

    tab_rows = _extract_rows_via_player_tab(driver, match_url)
    if tab_rows:
        candidates.insert(0, '__rows_from_tab_click__')

    home_name = _clean_player_name(result.get('home', {}).get('name', ''))
    away_name = _clean_player_name(result.get('away', {}).get('name', ''))
    team_name_norms = {_normalize_name(home_name), _normalize_name(away_name)}
    team_name_norms.discard('')
    team_abbrs = {
        str(result.get('home', {}).get('abbr', '')).strip().upper(),
        str(result.get('away', {}).get('abbr', '')).strip().upper(),
    }
    team_abbrs.discard('')

    for c_url in candidates:
        try:
            if c_url == '__rows_from_tab_click__':
                rows = tab_rows
            else:
                driver.get(c_url)
                time.sleep(1.5)
                rows = _extract_player_rows(driver)
            log.info(f'Player rows found on {c_url}: {len(rows)}')
            if not rows:
                continue

            for row in rows:
                name = _clean_player_name(row.get('name', ''))
                nums = row.get('nums', [])
                if not name or not isinstance(nums, list):
                    continue

                # Some Flashscore rows are team summary rows, not player rows.
                # Skip rows whose "name" equals current home/away team labels.
                name_norm = _normalize_name(name)
                if name_norm in team_name_norms:
                    continue
                upper_name = name.upper()
                if upper_name in team_abbrs:
                    continue

                vals = [_to_float(x) for x in nums]
                # Flashscore player-stats rows start with PTS, REB, AST.
                pts = vals[0] if len(vals) >= 1 else 0.0
                reb = vals[1] if len(vals) >= 2 else 0.0
                ast = vals[2] if len(vals) >= 3 else 0.0

                # STL/BLK columns vary by tournament view; keep conservative guesses.
                stl = vals[-4] if len(vals) >= 7 else 0.0
                blk = vals[-3] if len(vals) >= 6 else 0.0
                if stl > 10:
                    stl = 0.0
                if blk > 10:
                    blk = 0.0

                side = str(row.get('side', '')).strip().lower()
                if side not in ('home', 'away'):
                    side = lineup_side_by_name.get(name.lower(), '')

                dedupe_key = f"{name.lower()}|{side}|{pts}|{reb}|{ast}|{stl}|{blk}"
                if dedupe_key in seen_candidates:
                    continue
                seen_candidates.add(dedupe_key)

                score = pts * 10.0 + reb * 4.0 + ast * 4.0 + stl * 3.0 + blk * 3.0
                side_ok = side in ('home', 'away')
                min_stat_ok = len(vals) >= 5
                in_match_lineup = name.lower() in lineup_side_by_name
                candidate_allowed = min_stat_ok if strict_match_players_only else True

                if strict_match_players_only and in_match_lineup and min_stat_ok:
                    # Current Flashscore markup often omits home/away classes on stat rows.
                    # If the player is in this match lineups, keep the candidate and use lineup side.
                    candidate_allowed = True

                candidate = {
                    'name': name,
                    'side': side,
                    'pts': pts,
                    'reb': reb,
                    'ast': ast,
                    'stl': stl,
                    'blk': blk,
                    'score': score,
                    'allowed': candidate_allowed,
                    'raw_nums': nums,
                    'player_url': str(row.get('player_url', '')).strip(),
                    'photo_url': str(row.get('photo_url', '')).strip(),
                }
                debug_candidates.append(candidate)

                if not candidate_allowed:
                    continue

                if best is None or candidate['score'] > best['score']:
                    best = candidate

            if best:
                break
        except Exception as e:
            log.debug(f'Player parse candidate failed ({c_url}): {e}')

    if not debug_candidates:
        log.info(f'Lineup fallback rows found: {len(lineup_rows)}')
        seen_lineup: set[str] = set()
        for row in lineup_rows:
            name = _clean_player_name(row.get('name', ''))
            side = str(row.get('side', '')).strip().lower()
            if not name:
                continue
            dedupe_key = f'{side}:{name.lower()}'
            if dedupe_key in seen_lineup:
                continue
            seen_lineup.add(dedupe_key)
            candidate = {
                'name': name,
                'side': side,
                'pts': 0.0,
                'reb': 0.0,
                'ast': 0.0,
                'stl': 0.0,
                'blk': 0.0,
                'score': 0.0,
                'allowed': True,
                'raw_nums': [],
                'player_url': str(row.get('player_url', '')).strip(),
                'photo_url': str(row.get('photo_url', '')).strip(),
                'source': 'lineups-fallback',
            }
            debug_candidates.append(candidate)

        if debug_candidates:
            best = debug_candidates[0]

    if not best and debug_candidates:
        # Fallback: if strict mode filtered all entries, keep the top scorer candidate.
        fallback_best = sorted(debug_candidates, key=lambda x: x.get('score', 0), reverse=True)[0]
        best = fallback_best
        log.info(
            f"Player fallback selected (strict filtered all): {best.get('name', '')!r} "
            f"side={best.get('side', '')!r} score={best.get('score', 0)!r}"
        )

    if dump_player_candidates:
        try:
            payload = {
                'updated_at': now_iso(),
                'match_key': match_url,
                'strict_match_players_only': strict_match_players_only,
                'count': len(debug_candidates),
                'candidates': sorted(debug_candidates, key=lambda x: x.get('score', 0), reverse=True),
            }
            write_json_atomic(PLAYER_DEBUG_PATH, payload)
        except Exception as e:
            log.debug(f'Could not write player debug dump: {e}')

    if not best:
        log.warning('Could not parse player stats from match page')
        return player

    side = best['side'] if best['side'] in ('home', 'away') else ''
    team_name = result.get(side, {}).get('name', '') if side else ''

    player['visible'] = True
    player['mode'] = 'live'
    player['team_side'] = side
    player['name'] = best['name']
    player['team'] = team_name
    player['stats'] = {
        'PPG': _fmt_stat(best['pts']),
        'RPG': _fmt_stat(best['reb']),
        'APG': _fmt_stat(best['ast']),
        'STL': _fmt_stat(best['stl']),
        'BLK': _fmt_stat(best['blk']),
        **_player_extra_stats(best.get('raw_nums', [])),
    }

    if is_nba_match(match_url, result):
        try:
            person_id = find_nba_player_id(player['name'])
            if person_id:
                local_photo = download_nba_headshot(person_id)
                if local_photo:
                    player['photo'] = local_photo
                    player['photo_source'] = 'auto:nba'
                    player['photo_status'] = 'auto_found'
                else:
                    fallback_url = _sportsdb_photo_url(player['name'])
                    fallback_photo = _download_external_photo(fallback_url, prefix='sdb') if fallback_url else ''
                    if fallback_photo:
                        player['photo'] = fallback_photo
                        player['photo_source'] = 'auto:sportsdb'
                        player['photo_status'] = 'auto_found'
                    else:
                        player['photo_status'] = 'auto_missing'
            else:
                fallback_url = _sportsdb_photo_url(player['name'])
                fallback_photo = _download_external_photo(fallback_url, prefix='sdb') if fallback_url else ''
                if fallback_photo:
                    player['photo'] = fallback_photo
                    player['photo_source'] = 'auto:sportsdb'
                    player['photo_status'] = 'auto_found'
                else:
                    player['photo_status'] = 'auto_missing'
        except Exception as e:
            log.warning(f'NBA photo lookup failed: {e}')
            player['photo_status'] = 'auto_missing'

    log.info(
        f"Selected match player: {player['name']!r} side={player['team_side']!r} "
        f"PTS={player['stats']['PPG']} REB={player['stats']['RPG']} AST={player['stats']['APG']}"
    )
    return player


def scrape(
    driver,
    url: str,
    include_stats: bool = True,
    strict_match_players_only: bool = True,
    dump_player_candidates: bool = True,
) -> tuple[dict, dict]:
    result = empty_result()
    player = empty_player(match_key=url)
    # Strip only hash fragment — keep ?mid= query param (it identifies the specific game)
    base = re.sub(r'#.*', '', url).rstrip('/')

    # ── Summary page ─────────────────────────────────────────────────────
    driver.get(base + '#/match-summary/match-summary')
    # Wait for participant name (guarantees SPA has rendered)
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR,
                '.duelParticipant__home, [class*="participant__participantName"]'))
        )
    except Exception:
        time.sleep(4)
    close_consent(driver)
    log.info(f"Page title: {driver.title!r}")

    # Team names
    for side, primary, fallback in [
        ('home',
         '.duelParticipant__home .participant__participantName',
         '.duelParticipant__home [class*="participant__overflow"]'),
        ('away',
         '.duelParticipant__away .participant__participantName',
         '.duelParticipant__away [class*="participant__overflow"]'),
    ]:
        name = el_text(driver, primary) or el_text(driver, fallback)
        if name:
            result[side]['name'] = name
            result[side]['abbr'] = make_abbr(name)
            log.info(f"{side}: {name!r} → {result[side]['abbr']}")

    # Team logos — fetch URL then download locally so the overlay can serve them from localhost
    for side in ('home', 'away'):
        raw_url = get_logo_url(driver, side)
        fname   = f'logo-{side}.png'
        dest    = os.path.join(BASE_DIR, 'json', fname)
        if raw_url and download_logo(raw_url, dest):
            result[side]['logo'] = f'json/{fname}'
        elif os.path.exists(dest):
            result[side]['logo'] = f'json/{fname}'   # keep cached logo
        else:
            result[side]['logo'] = ''

    # Total score
    try:
        # Wait for score to appear
        try:
            WebDriverWait(driver, 6).until(
                EC.presence_of_element_located((By.CSS_SELECTOR,
                    '.detailScore__wrapper, [class*="currentScore"], [class*="detailScore__current"]'))
            )
        except Exception:
            pass
        spans = driver.find_elements(By.CSS_SELECTOR, '.detailScore__wrapper span')
        vals = [s.text.strip() for s in spans
                if s.text.strip() and s.text.strip() not in ('-', '–', ':')]
        log.info(f"Score spans: {vals}")
        if len(vals) >= 2:
            result['home']['total'] = vals[0]
            result['away']['total'] = vals[1]
        else:
            # Fallback selectors for finished games
            for sel in [
                '[class*="currentScore"]',
                '[class*="detailScore__current"]',
                '[class*="fixedHeaderDuel__scoreWrapper"] span',
            ]:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                vals2 = [e.text.strip() for e in els if re.match(r'^\d+$', e.text.strip())]
                log.info(f"Score fallback {sel}: {vals2}")
                if len(vals2) >= 2:
                    result['home']['total'] = vals2[0]
                    result['away']['total'] = vals2[1]
                    break
    except Exception as e:
        log.warning(f"Total score: {e}")

    # Match status / current quarter
    st = ''
    for sel in [
        '[class*="detailScore__status"]',
        '[class*="duelParticipant__status"]',
        '[class*="matchStatus"]',
        '[class*="eventStatus"]',
        '[class*="stage--live"]',
        '[class*="fixedHeaderDuel__status"]',
    ]:
        st = el_text(driver, sel)
        if st:
            log.info(f"Status ({sel}): {st!r}")
            break

    if not st:
        log.info("Status element not found, trying JS")
        try:
            st = driver.execute_script("""
                const sels = [
                    '[class*="detailScore__status"]',
                    '[class*="duelParticipant__status"]',
                    '[class*="matchStatus"]',
                    '[class*="eventStatus"]',
                ];
                for (const s of sels) {
                    const el = document.querySelector(s);
                    if (el && el.innerText.trim()) return el.innerText.trim();
                }
                return '';
            """) or ''
            if st:
                log.info(f"Status (JS): {st!r}")
        except Exception:
            pass

    st_lower = st.lower()
    # Check finished (English + Russian)
    _over_kw = ['finished', 'final', 'ended', 'after ot', 'aet', 'pen',
                'завершён', 'завершен', 'окончен', 'закончен', 'по ot', 'по от']
    _sched_kw = ['not started', 'ns', 'scheduled', 'postponed',
                 'не начат', 'запланирован', 'перенесён', 'перенесен']
    _live_kw  = ['live', 'четверть', 'период', 'half time', 'halftime', 'перерыв']
    if any(x in st_lower for x in _over_kw):
        result['status'] = 'over'
    elif any(x in st_lower for x in _sched_kw):
        result['status'] = 'scheduled'
    else:
        # English: Q1/Q2/Q3/Q4/OT
        m_q = re.search(r'(Q[1-4]|OT\d?|HT)', st, re.I)
        # Russian: "1-я четверть", "2-й период", "3-я" etc. + live keywords
        m_q_ru = re.search(r'(\d)[- ](я|й|ой|ей)\s*(чет|пер|кв)', st_lower)
        is_ru_live = any(x in st_lower for x in _live_kw)
        if m_q:
            result['status'] = 'live'
            result['quarter'] = m_q.group(1).upper()
        elif m_q_ru or is_ru_live:
            result['status'] = 'live'
            if m_q_ru:
                result['quarter'] = f"Q{m_q_ru.group(1)}"
        m_t = re.search(r'(\d{1,2}:\d{2})', st)
        if m_t:
            result['time'] = m_t.group(1)

    # If scores found but status still unknown AND no time running → treat as finished
    # (don't convert live status — live games have scores too)
    if result['status'] == 'scheduled' and result['home']['total'] and result['away']['total']:
        log.info("Scores found but status unknown → marking as over")
        result['status'] = 'over'

    # Quarter scores
    parse_quarter_scores(driver, result)

    # ── Statistics page ───────────────────────────────────────────────────
    if include_stats:
        try:
            parse_stats(driver, result)
        except Exception as e:
            log.warning(f"Stats scrape failed: {e}", exc_info=True)

    try:
        player = parse_player_from_match(
            driver,
            result,
            url,
            strict_match_players_only=strict_match_players_only,
            dump_player_candidates=dump_player_candidates,
        )
    except Exception as e:
        log.warning(f'Player scrape failed: {e}', exc_info=True)

    return result, player


# ── Main loop ──────────────────────────────────────────────────────────────────
def main():
    log.info("=== Basketball scraper started ===")

    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception as e:
        log.error(f"Cannot read config: {e}")
        return

    urls = cfg.get('urls', [])
    if not urls:
        log.error("No urls in config.json")
        return

    url = str(urls[0]).strip()
    freq = max(3, int(cfg.get('update_frequency', 30)))
    live_max_delay = max(2, min(5, freq))
    strict_match_players_only = _cfg_bool(cfg, 'strict_match_players_only', True)
    dump_player_candidates = _cfg_bool(cfg, 'dump_player_candidates', True)
    auto_switch_match_url = _cfg_bool(cfg, 'auto_switch_match_url', True)
    log.info(
        f"URL: {url}  |  frequency: {freq}s  |  live_max_delay: {live_max_delay}s  "
        f"strict_players={strict_match_players_only}"
    )

    driver = None
    try:
        driver = get_driver()
        while True:
            cycle_started = time.time()
            log.info("─── Scrape start ───")

            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    live_cfg = json.load(f)
                live_urls = live_cfg.get('urls', [])
                new_url = str(live_urls[0]).strip() if isinstance(live_urls, list) and live_urls else url
                new_freq = max(3, int(live_cfg.get('update_frequency', freq)))
                new_strict = _cfg_bool(live_cfg, 'strict_match_players_only', strict_match_players_only)
                new_dump = _cfg_bool(live_cfg, 'dump_player_candidates', dump_player_candidates)
                new_auto_switch = _cfg_bool(live_cfg, 'auto_switch_match_url', auto_switch_match_url)

                if new_auto_switch and new_url and new_url != url:
                    log.info(f'Match URL changed in config, switching scraper source to: {new_url}')
                    clear_player_cache()
                    url = new_url

                freq = new_freq
                live_max_delay = max(2, min(5, freq))
                strict_match_players_only = new_strict
                dump_player_candidates = new_dump
                auto_switch_match_url = new_auto_switch
            except Exception as e:
                log.debug(f'Live config reload skipped: {e}')

            result, player = scrape(
                driver,
                url,
                include_stats=True,
                strict_match_players_only=strict_match_players_only,
                dump_player_candidates=dump_player_candidates,
            )

            existing_player = read_json_dict(PLAYER_PATH)
            existing_mode = str(existing_player.get('mode', '')).strip().lower()
            existing_match_key = str(existing_player.get('match_key', '')).strip()
            locked_modes = {'manual_lock', 'manual_hidden_lock'}
            if existing_mode in locked_modes and existing_match_key == url and existing_player.get('name'):
                player = existing_player
                log.info(
                    f"PLAYER LOCK active from manager: {player.get('name', '')!r} mode={existing_mode!r}"
                )

            write_json_atomic(RESULT_PATH, result)
            write_json_atomic(PLAYER_PATH, player)

            log.info(
                f"Written result.json: status={result['status']!r}  "
                f"quarter={result['quarter']!r}  time={result['time']!r}"
            )
            log.info(
                f"  HOME {result['home']['abbr']}  total={result['home']['total']}  "
                f"Q1={result['home']['q1']} Q2={result['home']['q2']} "
                f"Q3={result['home']['q3']} Q4={result['home']['q4']}"
            )
            log.info(
                f"  AWAY {result['away']['abbr']}  total={result['away']['total']}  "
                f"Q1={result['away']['q1']} Q2={result['away']['q2']} "
                f"Q3={result['away']['q3']} Q4={result['away']['q4']}"
            )
            log.info(f"  FG  {result['home']['FG']} / {result['away']['FG']}")
            log.info(f"  3P  {result['home']['3P']} / {result['away']['3P']}")
            log.info(f"  FT  {result['home']['FT']} / {result['away']['FT']}")
            log.info(
                f"  PLAYER {player.get('name', '')!r} team={player.get('team', '')!r} "
                f"photo={player.get('photo_status', '')!r}"
            )
            log.info(
                f"  FLAGS strict_players={strict_match_players_only} dump_candidates={dump_player_candidates} "
                f"auto_switch_match_url={auto_switch_match_url}"
            )

            elapsed = time.time() - cycle_started
            delay = max(1.0, freq - elapsed)
            if result.get('status') == 'live':
                delay = min(delay, float(live_max_delay))
            log.info(f"Cycle elapsed: {elapsed:.1f}s, sleep: {delay:.1f}s")
            time.sleep(delay)

    except KeyboardInterrupt:
        log.info("Stopped by user (Ctrl+C)")
    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
    log.info("=== Scraper finished ===")


if __name__ == '__main__':
    if '--self-check' in sys.argv:
        payload = {
            'ok': os.path.exists(CONFIG_PATH),
            'config_path': CONFIG_PATH,
            'result_path': RESULT_PATH,
            'player_path': PLAYER_PATH,
            'json_dir_writable': os.access(os.path.dirname(CONFIG_PATH), os.W_OK),
            'chrome_cache_note': 'webdriver is checked during normal scraper startup',
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        raise SystemExit(0 if payload['ok'] and payload['json_dir_writable'] else 1)
    main()
