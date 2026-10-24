#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
================================================================================
 桌面时钟 · 国际化版   TimeClock i18n
 ================================================================================
 特性
   · 无边框 / 始终置顶 / 整窗拖拽 / ⬇ 一键沉底 + Ctrl+Shift+1 全局热键
   · 全量时区：zoneinfo 598 个时区，界面里可搜索、实时切换
   · 五大工作语言：中 zh / 英 en / 法 fr / 俄 ru / 西 es，主语言 + 可选副语言
   · 节假日：holidays 判放假，chinesecalendar 判「调休上班」，双拼双语显示
   · 番茄钟：可设时长的倒计时 + 提示音 + 自动复位
   · 长文本按单词边界折行，绝不切断单词（safewrap 见 safe_wraplength）

 ------------------------------------------------------------------------------
 依赖
 ------------------------------------------------------------------------------
     pip install holidays chinesecalendar tzdata

   · holidays         节假日数据（501 个国家）
   · chinesecalendar  中国调休/补班（仅中国用到，缺了只是没有"调休上班"标记）
   · tzdata           Windows 没有 IANA 时区库，zoneinfo 需要它

 ------------------------------------------------------------------------------
 打包（PyInstaller --onedir）
 ------------------------------------------------------------------------------
     python -m PyInstaller --noconfirm --clean --noconsole --onedir ^
       --name TimeClock ^
       --collect-data tzdata ^
       --collect-all holidays ^
       --collect-all chinese_calendar ^
       main_i18n.py
================================================================================
"""

from __future__ import annotations   # 让 str | None 这类注解在 3.9 也能用

import json
import os
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from tkinter import ttk
from zoneinfo import ZoneInfo, available_timezones, ZoneInfoNotFoundError
# ===========================================================================
#  1. 可选依赖（缺了也不崩，只是对应功能静默降级）
# ===========================================================================
try:
    import holidays as holidays_lib
    HAS_HOLIDAYS = True
except Exception:                                # noqa: BLE001
    holidays_lib = None
    HAS_HOLIDAYS = False

try:
    import chinese_calendar as cn_cal
    HAS_CN_CAL = True
except Exception:                                # noqa: BLE001
    cn_cal = None
    HAS_CN_CAL = False

try:
    if sys.platform == "win32":
        import winsound
        HAS_WINSOUND = True
    else:
        winsound = None
        HAS_WINSOUND = False
except Exception:                                # noqa: BLE001
    winsound = None
    HAS_WINSOUND = False


# ===========================================================================
#  2. 外观与行为配置
# ===========================================================================
APP_TITLE = "TimeClock i18n"

# 颜色（深色底 + 淡银主文字，和原版一致）
BG_COLOR = "#1e1e1e"
BG_TOP = "#252525"              # 顶栏
FG_SILVER = "#c8ccd2"           # 主文字
FG_DIM = "#7d8288"              # 次要文字
COLOR_WEEKEND = "#9fe0a3"       # 周六日：绿色
COLOR_HOLIDAY = "#ff9f1c"       # 节假日/调休：统一暖橙
COLOR_NORMAL = "#9a9a9a"        # 普通日
COLOR_ACCENT = "#4aa8ff"        # 强调（⚙、时区名）
COLOR_REST = "#ff4d4f"          # 番茄钟休息中

WINDOW_ALPHA = 0.90
# ★ 扁平长条布局：宽 820、高约 120（有节假日时会自动长高一点）
WIN_WIDTH = 1090                 # 固定宽度，保证折行宽度稳定
WIN_MIN_H = 185               # 高度下限（多了一行副语言日期，+25）
WIN_MAX_H = 340                  # 高度上限（长语言折行时也能装下）                 # 高度上限（内容再多也不无限长）
TOP_H = 30                      # 顶栏高度（⚙ + 时区框 + 番茄钟 + 🔄 + ⬇）
WRAP_BASE = 500                 # 中间「日期/节假日」列的折行基准宽度

# 字号（单位 pt）。
# ★ 实测：这台机器是 2560×1600 @150%，Tk 的 tk scaling ≈ 2.0，
#   也就是 1pt 渲染成 2px；标签高度 ≈ 字号 × 2.78。
FONT_FAMILY_CANDIDATES = ["Microsoft YaHei UI", "微软雅黑", "Segoe UI",
                          "DejaVu Sans", "Arial"]
SIZE_DATE = 18          # 日期正常大小
SIZE_HOLIDAY = 14       # 节假日正常大小
SIZE_HHMM = 46          # 大时间 52 刚刚好，有冲击力但不会撑爆
SIZE_SS = 22            # 秒数
SIZE_SMALL = 12
SIZE_POMO = 10
SIZE_TZ2 = 28           # 副时区放大一点，清晰可见
SIZE_AMPM = 20          # 上午/下午小字（只有 12 小时制显示）

# 番茄钟
POMO_WORK_MIN = 45              # 默认专注时长（分钟）
POMO_TICK_MS = 200

# 全局热键：默认 Ctrl+Shift+T（不再写死 Ctrl+Shift+1，避免和别人软件冲突）
# ★ 用户可在【设置面板】里点击快捷键框直接按组合键修改，
#   也可以手工编辑 config.json 的 "hotkey" 字段；
#   设为空字符串 "" 表示不启用全局热键。
DEFAULT_HOTKEY = "ctrl+shift+t"
HOTKEY_POLL_MS = 80
PIN_TEXT_UP = "⬇"
PIN_TEXT_DOWN = "📌"

TZ2_WRAP = 200                  # 右列折行宽度（超长就折行，不截断）
# 时钟刷新
CLOCK_TICK_MS = 200             # 200ms 刷新一次，切时区无延迟感

# ---- 休息时段提醒 ----
# ★ 某时区落在 [23:00, 次日 07:00) 就认为"可能在休息"：
#   该时区的时间变红，并在旁边提示「我方可能在休息 / 对方可能在休息」。
#   12 小时制下也是同一个区间（"下午 11 点 → 次日上午 7 点"），
#   因为判断用的是 24 小时制的钟点，和显示制式无关。
REST_START_HOUR = 23            # 开始算休息的小时（含）
REST_END_HOUR = 7               # 结束的小时（不含）
COLOR_REST = "#ff4d4f"          # 休息提示用红色

DEFAULT_TZ = "Asia/Shanghai"
DEFAULT_TZ2 = "America/Los_Angeles"      # 第二时区（可设为不显示）


# ===========================================================================
#  2.5 配置持久化
# ===========================================================================
# 存的位置（Windows 用 %APPDATA%，Linux 用 ~/.config），
# 这样无论直接跑 py 还是跑打包后的 exe，都能找到同一份配置。
CONFIG_DIR_NAME = "TimeClockI18n"
CONFIG_FILE_NAME = "config.json"
CONFIG_VERSION = 1


def config_path():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, CONFIG_DIR_NAME, CONFIG_FILE_NAME)


def load_config():
    """
    读配置。返回 dict（可能为空）。

    ★ 任何异常都吞掉：配置损坏/不存在时用默认值启动，
      绝不能因为一个 json 文件坏了就开不了时钟。
    """
    path = config_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        print(f"[config] 读取失败，使用默认配置：{exc}")
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def save_config(cfg):
    """
    写配置（原子写入：先写 .tmp 再替换，避免断电/崩溃留下半个文件）。
    """
    path = config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)          # 原子替换
        return True
    except OSError as exc:
        print(f"[config] 保存失败：{exc}")
        return False


def _valid_tz(name):
    if not name or not isinstance(name, str):
        return False
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return False


def _valid_lang(code):
    return isinstance(code, str) and code in LANGUAGES


def normalize_hotkey(spec):
    """
    把快捷键规整成 "ctrl+shift+t" 小写形式。

      返回 "" 表示不启用；返回 None 表示格式非法。
    只支持 字母/数字 作主键（和 parse_hotkey 保持一致）。
    """
    if spec is None:
        return ""
    s = str(spec).strip().lower().replace(" ", "")
    if not s:
        return ""
    alias = {"control": "ctrl", "super": "win", "meta": "win", "option": "alt"}
    mods, key = [], None
    for p in s.split("+"):
        if not p:
            continue
        p = alias.get(p, p)
        if p in ("ctrl", "shift", "alt", "win"):
            if p not in mods:
                mods.append(p)
        elif len(p) == 1 and p.isalnum():
            key = p
        else:
            return None
    if key is None:
        return None
    order = ("ctrl", "shift", "alt", "win")
    return "+".join([m for m in order if m in mods] + [key])


def state_from_config(cfg):
    """
    用配置构造 ClockState，逐项校验：
      时区不存在 → 回默认；语言不认识 → 回默认；数值越界 → 夹到范围内。
    """
    st = ClockState()
    if _valid_tz(cfg.get("tz")):
        st.tz = cfg["tz"]
    tz2 = cfg.get("tz2", DEFAULT_TZ2)
    if tz2 is None:
        st.tz2 = None
    elif _valid_tz(tz2):
        st.tz2 = tz2
    if _valid_lang(cfg.get("primary")):
        st.primary = cfg["primary"]
    if cfg.get("secondary", "en") is None:
        st.secondary = None
    elif _valid_lang(cfg.get("secondary")):
        st.secondary = cfg["secondary"]
    if isinstance(cfg.get("hour24"), bool):
        st.hour24 = cfg["hour24"]
    wm = cfg.get("work_minutes")
    if isinstance(wm, int) and 1 <= wm <= 180:
        st.work_minutes = wm
    # 快捷键：格式非法就退回默认，缺省也用默认
    hk = normalize_hotkey(cfg.get("hotkey", DEFAULT_HOTKEY))
    st.hotkey = DEFAULT_HOTKEY if hk is None else hk
    return st


def config_from_state(st, window=None):
    cfg = {
        "version": CONFIG_VERSION,
        "tz": st.tz,
        "tz2": st.tz2,
        "primary": st.primary,
        "secondary": st.secondary,
        "hour24": st.hour24,
        "work_minutes": st.work_minutes,
        "hotkey": st.hotkey,
    }
    if window:
        cfg["window"] = {"x": int(window[0]), "y": int(window[1])}
    return cfg


# ===========================================================================
#  3. 语言字典
# ===========================================================================
LANGUAGES = ["zh", "en", "fr", "ru", "es"]

LANGUAGE_DICT = {
    "zh": {
        "name": "中文",
        "weekdays_long": ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"],
        "weekdays_short": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
        "months_long": ["一月", "二月", "三月", "四月", "五月", "六月",
                        "七月", "八月", "九月", "十月", "十一月", "十二月"],
        "date_fmt": "{y}年{m}月{d}日",
        "settings": "设置", "language": "语言", "primary": "主语言",
        "secondary": "副语言", "none": "（不显示）", "timezone": "时区",
        "timezone2": "第二时区", "search_tz": "搜索时区…", "hour24": "24 小时制",
        "pomodoro": "番茄钟", "work_minutes": "专注时长（分钟）",
        "start": "开始", "pause": "暂停", "reset": "重置",
        "holiday": "节假日", "makeup": "调休上班",
        "close": "关闭", "apply": "应用",
        "pomo_idle": "就绪", "pomo_running": "专注中", "pomo_done": "时间到",
        "tomorrow_is": "明天是",
        "date_long_fmt": "{y}年{m}月{d}日",
        "am": "上午", "pm": "下午",
    },
    "en": {
        "name": "English",
        "weekdays_long": ["Monday", "Tuesday", "Wednesday", "Thursday",
                          "Friday", "Saturday", "Sunday"],
        "weekdays_short": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "months_long": ["January", "February", "March", "April", "May", "June",
                        "July", "August", "September", "October", "November", "December"],
        "date_fmt": "{m}/{d}/{y}",
        "settings": "Settings", "language": "Language", "primary": "Primary",
        "secondary": "Secondary", "none": "(none)", "timezone": "Time zone",
        "timezone2": "Second zone", "search_tz": "Search time zone…",
        "hour24": "24-hour clock",
        "pomodoro": "Pomodoro", "work_minutes": "Focus minutes",
        "start": "Start", "pause": "Pause", "reset": "Reset",
        "holiday": "Holiday", "makeup": "Work day (makeup)",
        "close": "Close", "apply": "Apply",
        "pomo_idle": "Ready", "pomo_running": "Focusing", "pomo_done": "Time's up",
        "tomorrow_is": "Tomorrow is",
        "date_long_fmt": "{month} {d}, {y}",
        "am": "AM", "pm": "PM",
    },
    "fr": {
        "name": "Français",
        "weekdays_long": ["lundi", "mardi", "mercredi", "jeudi",
                          "vendredi", "samedi", "dimanche"],
        "weekdays_short": ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."],
        "months_long": ["janvier", "février", "mars", "avril", "mai", "juin",
                        "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
        "date_fmt": "{d}/{m}/{y}",
        "settings": "Paramètres", "language": "Langue", "primary": "Principale",
        "secondary": "Secondaire", "none": "(aucune)", "timezone": "Fuseau horaire",
        "timezone2": "Second fuseau", "search_tz": "Rechercher un fuseau…",
        "hour24": "Format 24 h",
        "pomodoro": "Pomodoro", "work_minutes": "Minutes de focus",
        "start": "Démarrer", "pause": "Pause", "reset": "Réinitialiser",
        "holiday": "Jour férié", "makeup": "Jour travaillé",
        "close": "Fermer", "apply": "Appliquer",
        "pomo_idle": "Prêt", "pomo_running": "Concentration", "pomo_done": "Terminé",
        "tomorrow_is": "Demain :",
        "date_long_fmt": "{d} {month} {y}",
        "am": "AM", "pm": "PM",     # CLDR 里法语的 am/pm 就是这两个
    },
    "ru": {
        "name": "Русский",
        "weekdays_long": ["понедельник", "вторник", "среда", "четверг",
                          "пятница", "суббота", "воскресенье"],
        "weekdays_short": ["пн", "вт", "ср", "чт", "пт", "сб", "вс"],
        "months_long": ["января", "февраля", "марта", "апреля", "мая", "июня",
                        "июля", "августа", "сентября", "октября", "ноября", "декабря"],
        "date_fmt": "{d}.{m}.{y}",
        "settings": "Настройки", "language": "Язык", "primary": "Основной",
        "secondary": "Дополнительный", "none": "(нет)", "timezone": "Часовой пояс",
        "timezone2": "Второй пояс", "search_tz": "Поиск часового пояса…",
        "hour24": "24-часовой формат",
        "pomodoro": "Помодоро", "work_minutes": "Минут фокуса",
        "start": "Старт", "pause": "Пауза", "reset": "Сброс",
        "holiday": "Праздник", "makeup": "Рабочий день",
        "close": "Закрыть", "apply": "Применить",
        "pomo_idle": "Готов", "pomo_running": "Фокус", "pomo_done": "Время вышло",
        "tomorrow_is": "Завтра",
        "date_long_fmt": "{d} {month} {y}",
        "am": "AM", "pm": "PM",     # CLDR 里俄语的 am/pm 也是这两个
    },
    "es": {
        "name": "Español",
        "weekdays_long": ["lunes", "martes", "miércoles", "jueves",
                          "viernes", "sábado", "domingo"],
        "weekdays_short": ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"],
        "months_long": ["enero", "febrero", "marzo", "abril", "mayo", "junio",
                        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
        "date_fmt": "{d}/{m}/{y}",
        "settings": "Ajustes", "language": "Idioma", "primary": "Principal",
        "secondary": "Secundario", "none": "(ninguno)", "timezone": "Zona horaria",
        "timezone2": "Segunda zona", "search_tz": "Buscar zona horaria…",
        "hour24": "Formato de 24 h",
        "pomodoro": "Pomodoro", "work_minutes": "Minutos de enfoque",
        "start": "Iniciar", "pause": "Pausar", "reset": "Reiniciar",
        "holiday": "Día festivo", "makeup": "Día laborable",
        "close": "Cerrar", "apply": "Aplicar",
        "pomo_idle": "Listo", "pomo_running": "Enfoque", "pomo_done": "Tiempo agotado",
        "tomorrow_is": "Mañana es",
        "date_long_fmt": "{d} de {month} de {y}",
        "am": "a. m.", "pm": "p. m.",
    },
}


# 快捷键相关的补充文案（单独一张表，方便以后加语言时不碰主字典）
_EXTRA_I18N = {
    "zh": {"hotkey": "全局快捷键", "press_keys": "按下组合键…",
           "hotkey_off": "（未启用）", "need_modifier": "需带 Ctrl/Alt/Shift",
           "rest_mine": "我方可能在休息", "rest_theirs": "对方可能在休息"},
    "en": {"hotkey": "Global hotkey", "press_keys": "Press keys…",
           "hotkey_off": "(disabled)", "need_modifier": "Need Ctrl/Alt/Shift",
           "rest_mine": "You may be resting", "rest_theirs": "They may be resting"},
    "fr": {"hotkey": "Raccourci global", "press_keys": "Appuyez…",
           "hotkey_off": "(désactivé)", "need_modifier": "Avec Ctrl/Alt/Shift",
           "rest_mine": "Vous vous reposez peut-être",
           "rest_theirs": "L'autre se repose peut-être"},
    "ru": {"hotkey": "Глобальная горячая клавиша", "press_keys": "Нажмите…",
           "hotkey_off": "(отключено)", "need_modifier": "Нужен Ctrl/Alt/Shift",
           "rest_mine": "Возможно, вы отдыхаете",
           "rest_theirs": "Возможно, они отдыхают"},
    "es": {"hotkey": "Atajo global", "press_keys": "Pulsa teclas…",
           "hotkey_off": "(desactivado)", "need_modifier": "Con Ctrl/Alt/Shift",
           "rest_mine": "Quizás estés descansando",
           "rest_theirs": "Quizás esté descansando"},
}
for _k, _v in _EXTRA_I18N.items():
    LANGUAGE_DICT.setdefault(_k, {}).update(_v)


def t(key, lang, **kw):
    """
    取文案：当前语言 → 中文 → key 本身，永不 KeyError。
    """
    s = (LANGUAGE_DICT.get(lang) or {}).get(key)
    if s is None:
        s = (LANGUAGE_DICT.get("zh") or {}).get(key, key)
    if kw and isinstance(s, str):
        try:
            return s.format(**kw)
        except (KeyError, IndexError):
            return s
    return s


def weekday_name(d, lang, short=False):
    """0=周一 … 6=周日"""
    key = "weekdays_short" if short else "weekdays_long"
    arr = (LANGUAGE_DICT.get(lang) or {}).get(key) \
        or LANGUAGE_DICT["zh"][key]
    return arr[d.weekday()]


def month_name(month, lang):
    arr = (LANGUAGE_DICT.get(lang) or {}).get("months_long") \
        or LANGUAGE_DICT["zh"]["months_long"]
    return arr[max(0, min(11, month - 1))]


def fmt_date(d, lang):
    return t("date_fmt", lang).format(y=d.year, m=d.month, d=d.day)


def is_resting(dt):
    """
    这个时刻是否落在休息时段（默认 23:00 – 次日 07:00）。

    ★ 用 24 小时制的 hour 判断，所以 12 小时制下同样生效
      （下午 11 点 = hour 23，上午 7 点 = hour 7）。
    """
    try:
        h = dt.hour
    except AttributeError:
        return False
    if REST_START_HOUR <= REST_END_HOUR:                 # 普通区间，如 1–6
        return REST_START_HOUR <= h < REST_END_HOUR
    return h >= REST_START_HOUR or h < REST_END_HOUR     # 跨零点，如 23–7


def date_long(d, lang):
    """
    长日期：英文是 "October 24, 2026"，中文是 "2026年10月24日"。
    ★ 用来做中间列的副语言日期（带上月份全称，比 10/24/2026 更易读）。
    """
    fmt = t("date_long_fmt", lang) or t("date_fmt", lang)
    try:
        return fmt.format(y=d.year, m=d.month, d=d.day,
                          month=month_name(d.month, lang))
    except (KeyError, IndexError, ValueError):
        return fmt_date(d, lang)


# ===========================================================================
#  4. 节日翻译表
# ===========================================================================
# key = holidays 返回的英文原名（先用 normalize_name 归一化）
HOLIDAY_I18N = {
    "New Year's Day": {"zh": "元旦", "en": "New Year's Day",
                       "fr": "Jour de l'an", "ru": "Новый год", "es": "Año Nuevo"},
    "New Year Holidays": {"zh": "元旦假期", "en": "New Year Holidays",
                          "fr": "Vacances du Nouvel An", "ru": "Новогодние каникулы",
                          "es": "Vacaciones de Año Nuevo"},
    "Martin Luther King Jr. Day": {"zh": "马丁·路德·金纪念日",
                                   "en": "Martin Luther King Jr. Day",
                                   "fr": "Journée Martin Luther King",
                                   "ru": "День Мартина Лютера Кинга",
                                   "es": "Día de Martin Luther King"},
    "Washington's Birthday": {"zh": "总统日", "en": "Washington's Birthday",
                              "fr": "Anniversaire de Washington",
                              "ru": "День рождения Вашингтона",
                              "es": "Cumpleaños de Washington"},
    "Memorial Day": {"zh": "阵亡将士纪念日", "en": "Memorial Day",
                     "fr": "Memorial Day", "ru": "День памяти",
                     "es": "Día de los Caídos"},
    "Juneteenth National Independence Day": {
        "zh": "六月节", "en": "Juneteenth", "fr": "Juneteenth",
        "ru": "День освобождения", "es": "Juneteenth"},
    "Independence Day": {"zh": "独立日", "en": "Independence Day",
                         "fr": "Jour de l'indépendance",
                         "ru": "День независимости",
                         "es": "Día de la Independencia"},
    "Labor Day": {"zh": "劳动节", "en": "Labor Day", "fr": "Fête du Travail",
                  "ru": "День труда", "es": "Día del Trabajo"},
    "Columbus Day": {"zh": "哥伦布日", "en": "Columbus Day",
                     "fr": "Jour de Christophe Colomb",
                     "ru": "День Колумба", "es": "Día de la Raza"},
    "Veterans Day": {"zh": "退伍军人节", "en": "Veterans Day",
                     "fr": "Jour des anciens combattants",
                     "ru": "День ветеранов", "es": "Día de los Veteranos"},
    "Thanksgiving Day": {"zh": "感恩节", "en": "Thanksgiving Day",
                         "fr": "Thanksgiving", "ru": "День благодарения",
                         "es": "Día de Acción de Gracias"},
    "Christmas Day": {"zh": "圣诞节", "en": "Christmas Day", "fr": "Noël",
                      "ru": "Рождество", "es": "Navidad"},
    "Mother's Day": {"zh": "母亲节", "en": "Mother's Day", "fr": "Fête des mères",
                     "ru": "День матери", "es": "Día de la Madre"},
    "Father's Day": {"zh": "父亲节", "en": "Father's Day", "fr": "Fête des pères",
                     "ru": "День отца", "es": "Día del Padre"},
    # ---- 法国 ----
    "Easter Monday": {"zh": "复活节星期一", "en": "Easter Monday",
                      "fr": "Lundi de Pâques", "ru": "Пасхальный понедельник",
                      "es": "Lunes de Pascua"},
    "Ascension": {"zh": "耶稣升天节", "en": "Ascension Day", "fr": "Ascension",
                  "ru": "Вознесение", "es": "Ascensión"},
    "Whit Monday": {"zh": "圣灵降临节星期一", "en": "Whit Monday",
                    "fr": "Lundi de Pentecôte", "ru": "Духов день",
                    "es": "Lunes de Pentecostés"},
    "Fête du Travail": {"zh": "劳动节", "en": "Labour Day", "fr": "Fête du Travail",
                        "ru": "День труда", "es": "Fiesta del Trabajo"},
    "Fête de la Victoire": {"zh": "胜利日", "en": "Victory Day",
                            "fr": "Fête de la Victoire", "ru": "День Победы",
                            "es": "Día de la Victoria"},
    "Bastille Day": {"zh": "巴士底日", "en": "Bastille Day",
                     "fr": "Fête nationale", "ru": "День взятия Бастилии",
                     "es": "Fiesta Nacional de Francia"},
    "Assumption of Mary to Heaven": {"zh": "圣母升天节", "en": "Assumption Day",
                                     "fr": "Assomption", "ru": "Успение",
                                     "es": "Asunción"},
    "All Saints' Day": {"zh": "万圣节", "en": "All Saints' Day",
                        "fr": "Toussaint", "ru": "День всех святых",
                        "es": "Todos los Santos"},
    "Armistice Day": {"zh": "停战纪念日", "en": "Armistice Day",
                      "fr": "Armistice", "ru": "День перемирия",
                      "es": "Día del Armisticio"},
    # ---- 俄罗斯 ----
    "Defender of the Fatherland Day": {"zh": "祖国保卫者日",
                                       "en": "Defender of the Fatherland Day",
                                       "fr": "Fête du défenseur de la patrie",
                                       "ru": "День защитника Отечества",
                                       "es": "Día del Defensor de la Patria"},
    "International Women's Day": {"zh": "国际妇女节", "en": "International Women's Day",
                                  "fr": "Journée internationale des femmes",
                                  "ru": "Международный женский день",
                                  "es": "Día Internacional de la Mujer"},
    "Spring and Labour Day": {"zh": "春天与劳动节", "en": "Spring and Labour Day",
                              "fr": "Fête du printemps et du travail",
                              "ru": "Праздник Весны и Труда",
                              "es": "Fiesta de la Primavera y el Trabajo"},
    "Victory Day": {"zh": "胜利日", "en": "Victory Day", "fr": "Jour de la Victoire",
                    "ru": "День Победы", "es": "Día de la Victoria"},
    "Russia Day": {"zh": "俄罗斯日", "en": "Russia Day", "fr": "Fête de la Russie",
                   "ru": "День России", "es": "Día de Rusia"},
    "Unity Day": {"zh": "民族团结日", "en": "Unity Day",
                  "fr": "Jour de l'unité", "ru": "День народного единства",
                  "es": "Día de la Unidad"},
    # ---- 西班牙 ----
    "Epiphany": {"zh": "主显节", "en": "Epiphany", "fr": "Épiphanie",
                 "ru": "Богоявление", "es": "Epifanía"},
    "Good Friday": {"zh": "耶稣受难日", "en": "Good Friday", "fr": "Vendredi saint",
                    "ru": "Страстная пятница", "es": "Viernes Santo"},
    "Fiesta del Trabajo": {"zh": "劳动节", "en": "Labour Day",
                           "fr": "Fête du Travail", "ru": "День труда",
                           "es": "Fiesta del Trabajo"},
    "Día de la Constitución": {"zh": "宪法日", "en": "Constitution Day",
                               "fr": "Jour de la Constitution",
                               "ru": "День Конституции",
                               "es": "Día de la Constitución"},
    "Inmaculada Concepción": {"zh": "圣母无染原罪节", "en": "Immaculate Conception",
                              "fr": "Immaculée Conception",
                              "ru": "Непорочное зачатие",
                              "es": "Inmaculada Concepción"},
    # ---- 通用 ----
    "National Day": {"zh": "国庆节", "en": "National Day", "fr": "Fête nationale",
                     "ru": "Национальный день", "es": "Fiesta Nacional"},
    "Labour Day": {"zh": "劳动节", "en": "Labour Day", "fr": "Fête du Travail",
                   "ru": "День труда", "es": "Día del Trabajo"},
    # ---- 中国（holidays.CN 直接返回中文名，所以 key 也用中文）----
    "元旦": {"zh": "元旦", "en": "New Year's Day", "fr": "Jour de l'an",
             "ru": "Новый год", "es": "Año Nuevo"},
    "春节": {"zh": "春节", "en": "Spring Festival", "fr": "Nouvel An chinois",
             "ru": "Китайский Новый год", "es": "Año Nuevo Chino"},
    "农历除夕": {"zh": "除夕", "en": "Chinese New Year's Eve",
                 "fr": "Réveillon du Nouvel An chinois",
                 "ru": "Канун Нового года", "es": "Nochevieja china"},
    "清明节": {"zh": "清明节", "en": "Qingming Festival", "fr": "Fête de Qingming",
               "ru": "Праздник Цинмин", "es": "Festival Qingming"},
    "劳动节": {"zh": "劳动节", "en": "Labour Day", "fr": "Fête du Travail",
               "ru": "День труда", "es": "Día del Trabajo"},
    "端午节": {"zh": "端午节", "en": "Dragon Boat Festival",
               "fr": "Fête des bateaux-dragons", "ru": "Праздник Дуаньу",
               "es": "Festival del Barco Dragón"},
    "中秋节": {"zh": "中秋节", "en": "Mid-Autumn Festival",
               "fr": "Fête de la mi-automne", "ru": "Праздник середины осени",
               "es": "Festival del Medio Otoño"},
    "国庆节": {"zh": "国庆节", "en": "National Day", "fr": "Fête nationale",
               "ru": "Национальный день", "es": "Fiesta Nacional"},
    # ★ 别名校验：chinese_calendar 返回的是【英文】节日名，holidays.CN 返回【中文】。
    #   两个库名字不一致，必须都有 key，否则补班日会显示成英文原文。
    "休息日": {"zh": "调休放假", "en": "Compensatory day off",
               "fr": "Jour de repos compensateur", "ru": "Отгул",
               "es": "Día libre compensatorio"},
    "Spring Festival": {"zh": "春节", "en": "Spring Festival",
                        "fr": "Nouvel An chinois", "ru": "Китайский Новый год",
                        "es": "Año Nuevo Chino"},
    "Tomb-sweeping Day": {"zh": "清明节", "en": "Qingming Festival",
                          "fr": "Fête de Qingming", "ru": "Праздник Цинмин",
                          "es": "Festival Qingming"},
    "Dragon Boat Festival": {"zh": "端午节", "en": "Dragon Boat Festival",
                             "fr": "Fête des bateaux-dragons",
                             "ru": "Праздник Дуаньу",
                             "es": "Festival del Barco Dragón"},
    "Mid-autumn Festival": {"zh": "中秋节", "en": "Mid-Autumn Festival",
                            "fr": "Fête de la mi-automne",
                            "ru": "Праздник середины осени",
                            "es": "Festival del Medio Otoño"},
    "Mid-Autumn Festival": {"zh": "中秋节", "en": "Mid-Autumn Festival",
                            "fr": "Fête de la mi-automne",
                            "ru": "Праздник середины осени",
                            "es": "Festival del Medio Otoño"},
}


# ===========================================================================
#  5. 时区 → 国家
# ===========================================================================
# 精选表：这些时区能明确对应到国家
TZ_TO_COUNTRY = {
    # 中国
    "Asia/Shanghai": "CN", "Asia/Chongqing": "CN", "Asia/Urumqi": "CN",
    "Asia/Harbin": "CN", "PRC": "CN",
    "Asia/Hong_Kong": "HK", "Asia/Macau": "MO", "Asia/Taipei": "TW",
    # 欧洲
    "Europe/Paris": "FR", "Europe/Monaco": "FR",
    "Europe/Madrid": "ES", "Atlantic/Canary": "ES", "Africa/Ceuta": "ES",
    "Europe/Moscow": "RU", "Europe/Kaliningrad": "RU", "Europe/Samara": "RU",
    "Asia/Yekaterinburg": "RU", "Asia/Novosibirsk": "RU", "Asia/Krasnoyarsk": "RU",
    "Asia/Irkutsk": "RU", "Asia/Yakutsk": "RU", "Asia/Vladivostok": "RU",
    "Europe/London": "GB", "Europe/Berlin": "DE", "Europe/Rome": "IT",
    "Europe/Amsterdam": "NL", "Europe/Brussels": "BE", "Europe/Vienna": "AT",
    "Europe/Warsaw": "PL", "Europe/Stockholm": "SE", "Europe/Oslo": "NO",
    "Europe/Copenhagen": "DK", "Europe/Helsinki": "FI", "Europe/Zurich": "CH",
    "Europe/Lisbon": "PT", "Europe/Athens": "GR", "Europe/Dublin": "IE",
    # 亚太
    "Asia/Tokyo": "JP", "Asia/Seoul": "KR", "Asia/Singapore": "SG",
    "Asia/Bangkok": "TH", "Asia/Kuala_Lumpur": "MY", "Asia/Jakarta": "ID",
    "Asia/Manila": "PH", "Asia/Ho_Chi_Minh": "VN", "Asia/Kolkata": "IN",
    "Asia/Karachi": "PK", "Asia/Dubai": "AE", "Asia/Jerusalem": "IL",
    # 美洲
    "America/New_York": "US", "America/Chicago": "US", "America/Denver": "US",
    "America/Phoenix": "US", "America/Los_Angeles": "US",
    "America/Anchorage": "US", "Pacific/Honolulu": "US",
    "America/Toronto": "CA", "America/Vancouver": "CA", "America/Edmonton": "CA",
    "America/Winnipeg": "CA", "America/Halifax": "CA", "America/Ottawa": "CA",
    "America/Sao_Paulo": "BR", "America/Argentina/Buenos_Aires": "AR",
    "America/Mexico_City": "MX", "America/Bogota": "CO", "America/Lima": "PE",
    "America/Santiago": "CL", "America/Caracas": "VE",
    # 大洋洲
    "Australia/Sydney": "AU", "Australia/Melbourne": "AU",
    "Australia/Brisbane": "AU", "Australia/Perth": "AU", "Australia/Adelaide": "AU",
    "Pacific/Auckland": "NZ",
}

# 前缀兜底（顺序敏感：具体的放前面）
_TZ_PREFIX_RULES = [
    ("America/Argentina", "AR"), ("America/Sao_Paulo", "BR"),
    ("America/Toronto", "CA"), ("America/Vancouver", "CA"),
    ("America/Edmonton", "CA"), ("America/Winnipeg", "CA"),
    ("America/Halifax", "CA"), ("America/Mexico_City", "MX"),
    ("America/", "US"),          # ★ 其余美洲时区默认当美国
    ("Australia/", "AU"),
    ("Pacific/Auckland", "NZ"),
    ("Europe/", None),           # 欧洲不猜，只认精选表
    ("Asia/", None),             # 亚洲不猜
    ("Africa/", None),
    ("Atlantic/", None), ("Indian/", None), ("Pacific/", None),
    ("Arctic/", None), ("Antarctica/", None), ("US/", "US"), ("Canada/", "CA"),
]


def tz_to_country(tz_name):
    """时区名 → 国家码；查不到返回 None（调用方据此静默关闭节日）"""
    if not tz_name:
        return None
    c = TZ_TO_COUNTRY.get(tz_name)
    if c:
        return c
    for prefix, country in _TZ_PREFIX_RULES:
        if tz_name.startswith(prefix):
            return country
    return None


# ===========================================================================
#  6. 节假日引擎
# ===========================================================================
_HOLIDAY_CACHE = {}          # {(country, year): HolidayBase|None}
_SUPPORTED_COUNTRIES = None


def _supported_countries():
    global _SUPPORTED_COUNTRIES
    if _SUPPORTED_COUNTRIES is None:
        try:
            _SUPPORTED_COUNTRIES = set(holidays_lib.list_supported_countries())
        except Exception:                        # noqa: BLE001
            _SUPPORTED_COUNTRIES = set()
    return _SUPPORTED_COUNTRIES


def _holidays_for(country, year):
    """按 国家+年份 缓存；任何异常都当成"没有节日"，绝不抛给 UI"""
    if not HAS_HOLIDAYS or not country:
        return None
    key = (country, year)
    if key not in _HOLIDAY_CACHE:
        try:
            if country in _supported_countries():
                _HOLIDAY_CACHE[key] = holidays_lib.country_holidays(
                    country, years=year)
            else:
                _HOLIDAY_CACHE[key] = None
        except Exception:                        # noqa: BLE001
            _HOLIDAY_CACHE[key] = None
    return _HOLIDAY_CACHE[key]


def normalize_name(name):
    """
    去掉节假日名里的括号备注，方便查翻译表。
    holidays 会返回 "Independence Day (observed)"、
    "休息日（由 2026-01-04 调休）" 这类变体。
    """
    if not name:
        return ""
    s = str(name)
    s = s.replace("（", "(").replace("）", ")")
    # 去掉末尾一层括号内容（可能有多层，最多去两次）
    for _ in range(2):
        new = s.rsplit("(", 1)[0].strip() if "(" in s else s
        if new == s:
            break
        s = new
    return s.strip()


def translate_holiday(name, lang):
    """节日名翻译：查表 → 原名；永不返回空"""
    if not name:
        return ""
    key = normalize_name(name)
    entry = HOLIDAY_I18N.get(key)
    if entry and entry.get(lang):
        return entry[lang]
    # 再试原始名（有些名字本身就带括号，是正式名的一部分）
    entry = HOLIDAY_I18N.get(str(name).strip())
    if entry and entry.get(lang):
        return entry[lang]
    return str(name).strip()


def cn_makeup_name(d):
    """
    中国「调休上班」判断：返回该节日的中文名，否则 None。

    ★ chinese_calendar.get_holiday_detail(d) 返回 (是否放假, 名称)，
      is_holiday=False 且 name 不为空 → 这就是一个调休补班日。
    """
    if not HAS_CN_CAL:
        return None
    try:
        is_holiday, name = cn_cal.get_holiday_detail(d)
    except Exception:                            # noqa: BLE001  超出覆盖年份
        return None
    if is_holiday is False and name:
        return str(name)
    return None


def holiday_info(d, tz_name):
    """
    返回 (kind, raw_name)：
        ("holiday", 原名)  放假
        ("makeup",  节日名) 调休上班（仅中国）
        (None, None)       无
    """
    country = tz_to_country(tz_name)

    # ---- 中国：先看是不是调休补班 ----
    if country == "CN":
        mk = cn_makeup_name(d)
        if mk:
            return "makeup", mk

    # ---- 放假 ----
    h = _holidays_for(country, d.year) if country else None
    if h:
        try:
            name = h.get(d)
        except Exception:                        # noqa: BLE001
            name = None
        if name:
            # 同一天多个节日时 holidays 用 "A; B" 连接，只取第一个
            first = str(name).split(";")[0].strip()
            return "holiday", first

    if not country:
        return None, None
    return None, None


def holiday_line(d, tz_name, primary, secondary):
    """
    拼出要显示的节假日文本；没有节日返回 None。
      放假  →  [主语言名]  [副语言名]
      调休  →  调休上班 [节日主语言名]
    """
    kind, raw = holiday_info(d, tz_name)
    if not kind:
        return None

    if kind == "makeup":
        label = t("makeup", primary)
        # ★ 实测：chinese_calendar.get_holiday_detail() 返回的节日名是【英文】
        #   （"New Year's Day" / "Spring Festival"），不是中文。
        #   所以这里要走翻译表，否则会拼出「调休上班 New Year's Day」这种中英混排。
        name = translate_holiday(raw, primary)
        parts = [f"{label} {name}"]
        if secondary:
            sec = translate_holiday(raw, secondary)
            if sec and sec != name:
                parts.append(sec)
        return "  ".join(parts)

    parts = [translate_holiday(raw, primary)]
    if secondary:
        sec = translate_holiday(raw, secondary)
        if sec and sec not in parts:
            parts.append(sec)
    return "  ".join(parts)


def eve_line(d, tz_name, primary, secondary):
    """
    节日提前一天提醒：返回「明天是 XXX」，没有则返回 None。

    ★ 关键细节：如果今天已经是同一个节日（比如春节连放 7 天），就不提醒。
      否则整个假期每天都会显示"明天是春节"，纯属噪音。
    """
    tomorrow = d + timedelta(days=1)
    kind2, raw2 = holiday_info(tomorrow, tz_name)
    if not kind2:
        return None

    # 与今天同一个节日 → 不重复提醒
    kind1, raw1 = holiday_info(d, tz_name)
    if kind1 == kind2 and normalize_name(raw1 or "") == normalize_name(raw2 or ""):
        return None

    prefix = t("tomorrow_is", primary)

    if kind2 == "makeup":
        return f"{prefix} {t('makeup', primary)}"

    parts = [translate_holiday(raw2, primary)]
    if secondary:
        sec = translate_holiday(raw2, secondary)
        if sec and sec not in parts:
            parts.append(sec)
    return f"{prefix} " + "  ".join(parts)


# ===========================================================================
#  7. 长文本防崩：按单词边界折行
# ===========================================================================
def safe_wraplength(text, font, base_px, pad=10):
    """
    保证 wraplength 不小于【最长单词】的宽度 + 余量。

    ★ 实测 tkinter 的行为：
        "Thanksgiving Day"  @ 81px  → 在空格处折行 ✓
        "Международный"     @ 88px  → 被字符级切断 ✗（变成 Междунаро / дный）
      所以只要把 wraplength 抬到最长单词宽度以上，就绝不会切断单词。
    """
    longest = 0
    for word in str(text or "").split():
        try:
            longest = max(longest, font.measure(word))
        except Exception:                        # noqa: BLE001
            continue
    return max(int(base_px), int(longest) + pad)


# ===========================================================================
#  8. Win32：沉底 / 置顶 / 全局热键（沿用原版已验证的实现）
# ===========================================================================
import ctypes

IS_WINDOWS = sys.platform == "win32"

_HWND_TOP = 0
_HWND_BOTTOM = 1
_HWND_TOPMOST = -1
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010
_SWP_SHOWWINDOW = 0x0040
_GWL_EXSTYLE = -20
_WS_EX_TOPMOST = 0x00000008
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_NOREPEAT = 0x4000
_WM_HOTKEY = 0x0312
_WM_QUIT = 0x0012
_HOTKEY_ID = 0x5A11

if IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                     ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    _user32.SetWindowPos.restype = ctypes.c_int
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    try:
        _user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        _user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        _get_style = _user32.GetWindowLongPtrW
    except AttributeError:
        _user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        _user32.GetWindowLongW.restype = ctypes.c_long
        _get_style = _user32.GetWindowLongW
else:
    _user32 = None
    _get_style = None


def _hwnd_value(signed):
    """HWND_TOPMOST(-1) 必须按指针宽度转成无符号，否则 API 会当成无效值"""
    bits = 8 * ctypes.sizeof(ctypes.c_void_p)
    return signed & ((1 << bits) - 1)


def get_hwnd(root):
    root.update_idletasks()
    try:
        return int(root.wm_frame(), 16)
    except Exception:                            # noqa: BLE001
        return root.winfo_id()


def win_set_pos(hwnd, insert_after, flags):
    if not IS_WINDOWS:
        return False
    return bool(_user32.SetWindowPos(hwnd, _hwnd_value(insert_after),
                                     0, 0, 0, 0, flags))


def win_is_topmost(hwnd):
    if not IS_WINDOWS:
        return False
    return bool(_get_style(hwnd, _GWL_EXSTYLE) & _WS_EX_TOPMOST)


def key_state(vk):
    if not IS_WINDOWS:
        return 0
    return _user32.GetAsyncKeyState(vk)


def parse_hotkey(spec):
    mods = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B}
    vks = []
    for part in str(spec).lower().replace(" ", "").split("+"):
        if not part:
            continue
        if part in mods:
            vks.append(mods[part])
        elif len(part) == 1 and part.isdigit():
            vks.append(0x30 + int(part))
        elif len(part) == 1 and "a" <= part <= "z":
            vks.append(ord(part.upper()))
        else:
            raise ValueError(f"快捷键格式不对：{part!r}")
    return vks


def parse_hotkey_win(spec):
    mask, vk = 0, None
    table = {"ctrl": _MOD_CONTROL, "shift": _MOD_SHIFT,
             "alt": 0x0001, "win": 0x0008}
    for part in str(spec).lower().replace(" ", "").split("+"):
        if not part:
            continue
        if part in table:
            mask |= table[part]
        elif len(part) == 1 and part.isdigit():
            vk = 0x30 + int(part)
        elif len(part) == 1 and "a" <= part <= "z":
            vk = ord(part.upper())
        else:
            raise ValueError(f"快捷键格式不对：{part!r}")
    if vk is None:
        raise ValueError("快捷键必须包含一个字母或数字主键")
    return mask, vk


if IS_WINDOWS:
    from ctypes import wintypes
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.GetCurrentThreadId.restype = ctypes.c_ulong
    _user32.RegisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                       ctypes.c_uint, ctypes.c_uint]
    _user32.RegisterHotKey.restype = ctypes.c_int
    _user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), ctypes.c_void_p,
                                    ctypes.c_uint, ctypes.c_uint]
    _user32.GetMessageW.restype = ctypes.c_int
    _user32.PostThreadMessageW.argtypes = [ctypes.c_ulong, ctypes.c_uint,
                                           ctypes.c_void_p, ctypes.c_void_p]


class HotkeyWatcher:
    """
    独立线程里 RegisterHotKey。沉底后窗口没有焦点，这是唯一能叫回来的方式。
    """

    def __init__(self, spec, out_queue, tk_module=tk):
        self.spec = spec
        self.out_queue = out_queue
        self.tk = tk_module
        self.ok = False
        self.error = None
        self._tid = None
        self._stopping = False
        self._thread = None

    def start(self):
        import threading
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        if not IS_WINDOWS:
            return
        try:
            mask, vk = parse_hotkey_win(self.spec)
        except Exception as exc:                 # noqa: BLE001
            self.error = str(exc)
            return
        self._tid = _kernel32.GetCurrentThreadId()
        if not _user32.RegisterHotKey(None, _HOTKEY_ID, mask | _MOD_NOREPEAT, vk):
            self.error = f"热键 {self.spec} 注册失败（可能被其它程序占用）"
            return
        self.ok = True
        msg = wintypes.MSG()
        try:
            while not self._stopping:
                ret = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0 or ret == -1:
                    break
                if msg.message == _WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                    self.out_queue.put(True)
        finally:
            _user32.UnregisterHotKey(None, _HOTKEY_ID)

    def stop(self):
        self._stopping = True
        if self._tid and IS_WINDOWS:
            try:
                _user32.PostThreadMessageW(self._tid, _WM_QUIT, 0, 0)
            except Exception:                    # noqa: BLE001
                pass


# ===========================================================================
#  9. 状态
# ===========================================================================
@dataclass
class ClockState:
    tz: str = DEFAULT_TZ
    tz2: str | None = DEFAULT_TZ2
    primary: str = "zh"
    secondary: str | None = "en"
    hour24: bool = True
    work_minutes: int = POMO_WORK_MIN
    hotkey: str = DEFAULT_HOTKEY
    pinned: bool = True

    def zone(self, second=False):
        name = self.tz2 if second else self.tz
        if not name:
            return None
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            return None


# ===========================================================================
#  10. 主窗口
# ===========================================================================
class ClockApp:

    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load_config()                     # ★ 先读配置
        self.state = state_from_config(self.cfg)     # ★ 逐项校验后构造
        self.closing = False
        self._drag = (0, 0)
        self._tick_job = None
        self._hotkey_job = None
        self._hotkey_prev = False
        self._hotkey_armed_at = 0.0
        self._hotkey_queue = None
        self._hotkey_watcher = None
        self._settings_win = None
        self._capturing = False          # 是否正在捕获快捷键
        self._hotkey_vks = []

        # 番茄钟
        self.pomo_remaining = 0.0
        self.pomo_running = False
        self.pomo_end_at = 0.0

        self._pick_fonts()
        self._build_window()
        self._build_ui()
        self._place(self.cfg.get("window"))          # ★ 恢复上次的窗口位置
        self._start_hotkey()
        self.tick()
        # ★ 首次运行时自动生成配置文件（含全部可配置项）
        try:
            if not os.path.exists(config_path()):
                self._save_config()
        except Exception:                        # noqa: BLE001
            pass

    # ---------- 字体 ----------
    def _pick_fonts(self):
        try:
            available = set(tkfont.families())
        except Exception:                        # noqa: BLE001
            available = set()
        family = next((f for f in FONT_FAMILY_CANDIDATES if f in available),
                      FONT_FAMILY_CANDIDATES[-1])
        self.family = family
        self.f_date = (family, SIZE_DATE)
        self.f_holiday = (family, SIZE_HOLIDAY)
        self.f_hhmm = (family, SIZE_HHMM, "bold")
        self.f_ampm = (family, SIZE_AMPM, "bold")   # 上午/下午，永远是小字
        self.f_tz2_date = (family, SIZE_SMALL)    # 第二时区的日期行
        self.f_ss = (family, SIZE_SS)
        self.f_small = (family, SIZE_SMALL)
        self.f_pomo = (family, SIZE_POMO)
        self.f_tz2 = (family, SIZE_TZ2)
        # 折行测量要用 Font 对象（有 .measure）
        self.m_holiday = tkfont.Font(family=family, size=SIZE_HOLIDAY)
        self.m_date = tkfont.Font(family=family, size=SIZE_DATE)
        self.m_hhmm = tkfont.Font(family=family, size=SIZE_HHMM, weight="bold")
        self.m_tz2d = tkfont.Font(family=family, size=SIZE_SMALL)

    # ---------- 列宽保底：防止「星期五」被截断 ----------
    def _info_minsize(self):
        """
        中间列保底宽度。

        ★ 必须把 grid 的 padx 也算进去：padx 是"控件外部"的间距，
          列宽 = padx + 控件宽。漏掉它就会出现「想要的宽 412、
          实际只给 406」这种差几像素的截断。
        """
        widest = 0
        for lang in LANGUAGES:
            try:
                sample = (fmt_date(date(2026, 10, 23), lang) + "  " +
                          weekday_name(date(2026, 10, 23), lang))
                widest = max(widest, self.m_date.measure(sample))
                # 副语言日期（小字）也一并量，避免它比主日期更宽
                sample2 = (date_long(date(2026, 10, 23), lang) + "  " +
                           weekday_name(date(2026, 10, 23), lang))
                widest = max(widest, self.m_date2.measure(sample2))
            except Exception:                    # noqa: BLE001
                continue
        self._info_min = widest + 20 + 12        # 帧 padx(12+8) + Label padx + 余量
        return self._info_min

    def _wrap_base(self):
        """
        节假日/明天的折行宽度。

        ★ 取 WRAP_BASE（配置值）与"列实际可用宽"的较小值——
          否则 wraplength 比列还宽时，Tk 会直接裁掉而不是折行。
        """
        base = getattr(self, "_info_min", WRAP_BASE + 24) - 24
        return max(160, min(WRAP_BASE, base))

    def _time_minsize(self):
        """大时间列的保底宽度（内容本身更宽时以内容为准）"""
        try:
            return self.m_hhmm.measure("23:59") + 40
        except Exception:                        # noqa: BLE001
            return 300

    def _tz2_minsize(self):
        """副时区列只需要一个防抖下限，实际宽度由内容撑开"""
        return 150

    # ---------- 窗口骨架 ----------
    def _build_window(self):
        r = self.root
        r.overrideredirect(True)                 # 无边框
        r.attributes("-topmost", True)           # 置顶
        try:
            r.attributes("-alpha", WINDOW_ALPHA)
        except tk.TclError:
            pass
        r.configure(bg=BG_COLOR)
        r.title(APP_TITLE)
        # ★ 拖拽不绑 root：绑在 root 上会让下拉框/按钮的点击也被当成拖窗。
        #   改为在 _build_ui 里逐个绑到"装饰性"控件上。
        r.bind("<ButtonRelease-1>", self._on_drag_end)   # 拖完存位置
        r.bind("<Escape>", lambda e: self.close())
        self._style_ttk()

    def _style_ttk(self):
        """把下拉框刷成深色，否则白底在深色界面上很突兀"""
        try:
            style = ttk.Style(self.root)
            if "clam" in style.theme_names():
                style.theme_use("clam")
            style.configure("TCombobox",
                            fieldbackground=BG_TOP, background=BG_TOP,
                            foreground=FG_SILVER, arrowcolor=FG_SILVER,
                            selectbackground=BG_TOP, selectforeground=FG_SILVER,
                            borderwidth=0, relief="flat", padding=2)
            style.map("TCombobox",
                      fieldbackground=[("readonly", BG_TOP), ("active", BG_TOP),
                                       ("focus", BG_TOP)],
                      foreground=[("readonly", FG_SILVER), ("active", FG_SILVER),
                                  ("focus", FG_SILVER)],
                      background=[("active", BG_TOP), ("focus", BG_TOP)],
                      arrowcolor=[("active", COLOR_ACCENT)])
            # 下拉列表本身（Listbox）只能用 option 数据库上色
            self.root.option_add("*TCombobox*Listbox.background", BG_TOP)
            self.root.option_add("*TCombobox*Listbox.foreground", FG_SILVER)
            self.root.option_add("*TCombobox*Listbox.selectBackground", COLOR_ACCENT)
            self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
            self.root.option_add("*TCombobox*Listbox.font", self.f_pomo)
        except Exception:                        # noqa: BLE001
            pass

    def _build_ui(self):
        f = self.family

        # ================= 顶栏（固定 26px 高，横向塞满）=================
        #  ⚙  [时区搜索框]              🍅 45:00 ▶ ↺        ⬇
        top = tk.Frame(self.root, bg=BG_TOP, height=TOP_H)
        top.pack(side="top", fill="x")
        top.pack_propagate(False)                # 锁死高度，不被内容撑开

        self.btn_settings = tk.Label(top, text="⚙", font=(f, 13),
                                     fg=COLOR_ACCENT, bg=BG_TOP, cursor="hand2")
        self.btn_settings.pack(side="left", padx=(8, 5))
        self.btn_settings.bind("<Button-1>", lambda e: self.open_settings())

        # 时区搜索框直接嵌在顶栏里，不占竖向空间
        self.combo_top = self._make_tz_picker(top, self.state.tz, width=22)
        self.combo_top.pack(side="left", pady=1)

        # 右端：⬇（置顶/沉底）
        self.btn_pin = tk.Label(top, text=PIN_TEXT_UP, font=(f, 11),
                                fg=COLOR_ACCENT, bg=BG_TOP, cursor="hand2")
        self.btn_pin.pack(side="right", padx=(4, 8))
        self.btn_pin.bind("<Button-1>", lambda e: self.toggle_pin())

        # 右端：🔄 主副时区一键互换
        self.btn_swap = tk.Label(top, text="🔄", font=(f, 10),
                                 fg=COLOR_ACCENT, bg=BG_TOP, cursor="hand2")
        self.btn_swap.pack(side="right", padx=3)
        self.btn_swap.bind("<Button-1>", lambda e: self.swap_zones())

        # 右端：番茄钟（↺ / ▶ / 时间）
        self.btn_reset = tk.Label(top, text="↺", font=(f, 12), fg=FG_DIM,
                                  bg=BG_TOP, cursor="hand2")
        self.btn_reset.pack(side="right", padx=3)
        self.btn_reset.bind("<Button-1>", lambda e: self.pomo_reset())

        self.btn_pomo = tk.Label(top, text="▶", font=(f, 12), fg=COLOR_ACCENT,
                                 bg=BG_TOP, cursor="hand2")
        self.btn_pomo.pack(side="right", padx=3)
        self.btn_pomo.bind("<Button-1>", lambda e: self.pomo_toggle())

        self.lbl_pomo = tk.Label(top, text="", font=self.f_pomo, fg=FG_DIM,
                                 bg=BG_TOP, anchor="e")
        self.lbl_pomo.pack(side="right", padx=(6, 2))

        # ================= 主区：一行三列 =================
        #  ┌──────────┬────────────────────────┬──────────────┐
        #  │ 14:32 45 │ 2026年10月24日 星期六   │  21:32       │
        #  │          │ 感恩节 Thanksgiving Day │  Los Angeles │
        #  │          │ 明天是 国庆节           │              │
        #  └──────────┴────────────────────────┴──────────────┘
        main = tk.Frame(self.root, bg=BG_COLOR)
        main.pack(side="top", fill="both", expand=True, padx=10, pady=(2, 6))
        # ★ minsize 是防止"星期五"被截断的关键：
        #   weight 只决定多余空间怎么分，minsize 才是给列保底宽度。
        main.columnconfigure(0, weight=0, minsize=self._time_minsize())
        main.columnconfigure(1, weight=1, minsize=self._info_minsize())
        main.columnconfigure(2, weight=0, minsize=self._tz2_minsize())
        main.rowconfigure(0, weight=1)

        # ---- 列 0：大时间 +（右下角）秒 / 上午下午 ----
        clock = tk.Frame(main, bg=BG_COLOR)
        # ★ 贴顶（nw）：时间的 y 位置只由顶栏高度决定，
        #   不会因为中间列多一行/少一行而上下跳。
        clock.grid(row=0, column=0, sticky="nw")
        self.lbl_hhmm = tk.Label(clock, text="", font=self.f_hhmm,
                                 fg=FG_SILVER, bg=BG_COLOR)
        self.lbl_hhmm.pack(side="left", anchor="n")

        # 右侧竖排小字：秒在上、AM/PM 在下（都贴右下角，不抢主时间焦点）
        tail = tk.Frame(clock, bg=BG_COLOR)
        tail.pack(side="left", anchor="n", padx=(4, 0), pady=(4, 0))
        self.lbl_ss = tk.Label(tail, text="", font=self.f_ss,
                               fg=FG_DIM, bg=BG_COLOR, anchor="e")
        self.lbl_ss.pack(anchor="e")
        self.lbl_ampm = tk.Label(tail, text="", font=self.f_ampm,
                                 fg=COLOR_ACCENT, bg=BG_COLOR, anchor="e")
        # ★ 始终占位（24 小时制只是清空文字），这样切换制式时布局不跳
        self.lbl_ampm.pack(anchor="e")

        # ---- 列 1：日期 / 节假日 / 明天是（左对齐纵向堆叠）----
        info = tk.Frame(main, bg=BG_COLOR)
        info.grid(row=0, column=1, sticky="nw", padx=(12, 2))
        # 我方休息提示（红色小字，放在日期上方）
        self.lbl_rest_mine = tk.Label(info, text="", font=(f, SIZE_SMALL),
                                      fg=COLOR_REST, bg=BG_COLOR, anchor="w")
        self.lbl_date = tk.Label(info, text="", font=self.f_date,
                                 fg=FG_SILVER, bg=BG_COLOR, anchor="w")
        self.lbl_date.pack(anchor="w")
        # 副语言日期（灰色小字，和主日期上下对照；副语言不显示时隐藏）
        self.f_date2 = (f, SIZE_SMALL)
        self.m_date2 = tkfont.Font(family=f, size=SIZE_SMALL)
        self.lbl_date2 = tk.Label(info, text="", font=self.f_date2,
                                  fg=FG_DIM, bg=BG_COLOR, anchor="w")
        # 不 pack，按需插到 lbl_date 下面
        self.lbl_holiday = tk.Label(info, text="", font=self.f_holiday,
                                    fg=COLOR_HOLIDAY, bg=BG_COLOR,
                                    justify="left", anchor="w")
        self.m_eve = tkfont.Font(family=f, size=SIZE_SMALL + 1)
        self.lbl_eve = tk.Label(info, text="", font=(f, SIZE_SMALL + 1),
                                fg=FG_DIM, bg=BG_COLOR,
                                justify="left", anchor="w")

        # ---- 列 2：第二时区（右对齐两行）----
        tz2f = tk.Frame(main, bg=BG_COLOR)
        tz2f.grid(row=0, column=2, sticky="ne", padx=(0, 8))
        self.lbl_tz2 = tk.Label(tz2f, text="", font=self.f_tz2,
                                fg=COLOR_NORMAL, bg=BG_COLOR, anchor="e")
        self.lbl_tz2.pack(anchor="e")
        self.lbl_tz2_name = tk.Label(tz2f, text="", font=(f, SIZE_SMALL),
                                     fg=FG_DIM, bg=BG_COLOR, anchor="e",
                                     justify="right", wraplength=TZ2_WRAP)
        self.lbl_tz2_name.pack(anchor="e")
        # 第二时区的日期 + 星期（带节假日/周末配色）
        self.lbl_tz2_date = tk.Label(tz2f, text="", font=self.f_tz2_date,
                                     fg=FG_DIM, bg=BG_COLOR, anchor="e",
                                     justify="right", wraplength=TZ2_WRAP)
        self.lbl_tz2_date.pack(anchor="e")
        # 对方休息提示（红色小字，放在最下方）
        self.lbl_rest_theirs = tk.Label(tz2f, text="", font=self.f_tz2_date,
                                        fg=COLOR_REST, bg=BG_COLOR, anchor="e",
                                        justify="right", wraplength=TZ2_WRAP)

        # ================= 拖拽：只绑"装饰性"控件 =================
        # 刻意不绑 combobox 和几个按钮，否则点下拉框会拖动窗口
        for w in (top, main, clock, tail, info, tz2f,
                  self.lbl_hhmm, self.lbl_ss, self.lbl_ampm, self.lbl_date,
                  self.lbl_holiday, self.lbl_eve, self.lbl_date2,
                  self.lbl_rest_mine, self.lbl_rest_theirs,
                  self.lbl_tz2, self.lbl_tz2_name, self.lbl_tz2_date,
                  self.lbl_pomo):
            w.bind("<Button-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)

        self._reset_pomo_state()

    def _place(self, saved=None):
        """放到屏幕右侧偏上；有保存过的位置就还原（并夹回屏幕内）"""
        self.root.update_idletasks()
        w = WIN_WIDTH
        h = max(WIN_MIN_H, min(WIN_MAX_H, self.root.winfo_reqheight()))
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()

        x = y = None
        if isinstance(saved, dict):
            try:
                x, y = int(saved["x"]), int(saved["y"])
            except (KeyError, TypeError, ValueError):
                x = y = None
        if x is None or y is None:
            x, y = max(10, sw - w - 20), 40

        # 换过显示器时旧坐标可能落在屏幕外，夹回来
        x = max(0, min(x, max(0, sw - w)))
        y = max(0, min(y, max(0, sh - h)))
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ---------- 拖拽 ----------
    def _start_drag(self, event):
        self._drag = (event.x, event.y)

    def _on_drag(self, event):
        x = self.root.winfo_x() + event.x - self._drag[0]
        y = self.root.winfo_y() + event.y - self._drag[1]
        self.root.geometry(f"+{x}+{y}")

    def _on_drag_end(self, event):
        """拖完才写配置，避免拖动过程中疯狂落盘"""
        self._save_config()

    def _save_config(self):
        """把当前状态（含窗口位置）写回配置文件"""
        try:
            pos = (self.root.winfo_x(), self.root.winfo_y())
        except Exception:                        # noqa: BLE001
            pos = None
        try:
            self.cfg = config_from_state(self.state, pos)
            save_config(self.cfg)
        except Exception as exc:                 # noqa: BLE001
            print(f"[config] 保存异常：{exc}")

    # ---------- 置顶 / 沉底 ----------
    def _pin_text(self):
        return PIN_TEXT_UP if self.state.pinned else PIN_TEXT_DOWN

    def toggle_pin(self):
        if self.state.pinned:
            self.sink_to_bottom()
        else:
            self.raise_to_top()

    def sink_to_bottom(self):
        self.state.pinned = False
        try:
            self.root.attributes("-topmost", False)
        except tk.TclError:
            pass
        if IS_WINDOWS:
            win_set_pos(get_hwnd(self.root), _HWND_BOTTOM,
                        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE)
        self.btn_pin.config(text=PIN_TEXT_DOWN)
        # 配色统一交给 refresh()：休息红 > 沉底暗 > 正常银
        # （不要在这里直接设颜色，否则会把"休息中"的红色盖掉）
        self.refresh()

    def raise_to_top(self):
        self.state.pinned = True
        try:
            self.root.deiconify()
        except Exception:                        # noqa: BLE001
            pass
        try:
            self.root.attributes("-topmost", True)
        except tk.TclError:
            pass
        if IS_WINDOWS:
            win_set_pos(get_hwnd(self.root), _HWND_TOPMOST,
                        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_SHOWWINDOW | _SWP_NOACTIVATE)
        try:
            self.root.lift()
        except Exception:                        # noqa: BLE001
            pass
        self.btn_pin.config(text=PIN_TEXT_UP)
        self.refresh()

    # ---------- 热键 ----------
    def _start_hotkey(self):
        """启动热键轮询循环，并按当前配置注册热键"""
        import queue
        self._hotkey_queue = queue.Queue()
        self._apply_hotkey()
        self._hotkey_job = self.root.after(HOTKEY_POLL_MS, self._poll_hotkey)

    def _apply_hotkey(self):
        """
        按 state.hotkey 重新注册全局热键 —— 设置面板改完立刻生效，不用重启。
        空字符串 = 不启用。
        """
        if self._hotkey_watcher is not None:
            try:
                self._hotkey_watcher.stop()
            except Exception:                    # noqa: BLE001
                pass
        self._hotkey_watcher = None
        self._hotkey_vks = []
        self._hotkey_prev = False

        spec = self.state.hotkey
        if spec and IS_WINDOWS:
            if self._hotkey_queue is None:
                import queue
                self._hotkey_queue = queue.Queue()
            self._hotkey_watcher = HotkeyWatcher(spec, self._hotkey_queue)
            self._hotkey_watcher.start()
            try:
                self._hotkey_vks = parse_hotkey(spec)
            except Exception:                    # noqa: BLE001
                self._hotkey_vks = []
        self._hotkey_armed_at = time.monotonic() + 0.4

    def _hotkey_display(self):
        """把 'ctrl+shift+t' 显示成 'Ctrl+Shift+T'"""
        spec = self.state.hotkey
        if not spec:
            return t("hotkey_off", self.state.primary)
        names = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "win": "Win"}
        return "+".join(names.get(p, p.upper()) for p in spec.split("+"))

    def _begin_hotkey_capture(self, event=None):
        """点击快捷键框 → 进入"等待按键"状态"""
        self._capturing = True
        try:
            self.var_hotkey.set(t("press_keys", self.state.primary))
            self.ent_hotkey.focus_set()
        except Exception:                        # noqa: BLE001
            pass
        return "break"

    def _on_hotkey_key(self, event):
        """捕获按键组合：修饰键 + 字母/数字 → 'ctrl+shift+t'"""
        if not getattr(self, "_capturing", False):
            return "break"
        ks = event.keysym
        # 纯修饰键不构成组合，继续等
        if ks in ("Control_L", "Control_R", "Shift_L", "Shift_R",
                  "Alt_L", "Alt_R", "Win_L", "Win_R", "Super_L", "Super_R",
                  "Caps_Lock", "Num_Lock"):
            return "break"
        # Esc 放弃
        if ks == "Escape":
            self._capturing = False
            self.var_hotkey.set(self._hotkey_display())
            return "break"
        # Backspace/Delete 清空 = 不启用
        if ks in ("BackSpace", "Delete"):
            self._capturing = False
            self.state.hotkey = ""
            self.var_hotkey.set(self._hotkey_display())
            self._apply_hotkey()
            self._save_config()
            return "break"

        st = event.state
        mods = []
        if st & 0x0004:
            mods.append("ctrl")
        if st & 0x0001:
            mods.append("shift")
        if st & 0x0008 or st & 0x20000:
            mods.append("alt")
        key = ks.lower()
        if len(key) != 1 or not key.isalnum():
            return "break"
        if not mods:
            self.var_hotkey.set(t("need_modifier", self.state.primary))
            return "break"

        self.state.hotkey = normalize_hotkey("+".join(mods + [key])) or ""
        self._capturing = False
        self.var_hotkey.set(self._hotkey_display())
        self._apply_hotkey()                     # ★ 立刻生效
        self._save_config()
        return "break"

    def _poll_hotkey(self):
        if self.closing:
            return
        try:
            while True:
                try:
                    self._hotkey_queue.get_nowait()
                except Exception:                # noqa: BLE001  queue.Empty
                    break
                self.toggle_pin()

            w = self._hotkey_watcher
            if (w is not None and not w.ok
                    and time.monotonic() >= self._hotkey_armed_at
                    and self._hotkey_vks):
                held = all(key_state(vk) & 0x8000 for vk in self._hotkey_vks)
                if held and not self._hotkey_prev:
                    self.toggle_pin()
                self._hotkey_prev = held
        except Exception:                        # noqa: BLE001
            pass
        try:
            self._hotkey_job = self.root.after(HOTKEY_POLL_MS, self._poll_hotkey)
        except Exception:                        # noqa: BLE001
            pass

    # ======================================================================
    #  11. 刷新链路（单一定时器，切时区不重启循环）
    # ======================================================================
    def tick(self):
        if self.closing:
            return
        try:
            self.refresh()
        except Exception as exc:                 # noqa: BLE001
            # 任何渲染异常都不能让时钟停摆
            print("[refresh error]", exc)
        self._tick_job = self.root.after(CLOCK_TICK_MS, self.tick)

    def refresh(self):
        st = self.state
        tz = st.zone()
        now = datetime.now(tz) if tz else datetime.now()
        relayout = False

        # ---- 中间列：主日期 / 副语言日期 / 节假日 / 明天是 ----
        #  统一按固定顺序重排，避免 pack 顺序因显隐变化而错乱
        line = holiday_line(now.date(), st.tz, st.primary, st.secondary)
        eve = eve_line(now.date(), st.tz, st.primary, st.secondary)

        # 主时区是否在休息时段
        rest1 = is_resting(now)
        # ★ 优先级：休息红 > 沉底暗 > 正常银
        #   沉底只是"不想挡视线"，不代表不关心休息状态，所以红色必须保留。
        if rest1:
            self.lbl_hhmm.config(fg=COLOR_REST)          # 休息中 → 永远红
        elif not st.pinned:
            self.lbl_hhmm.config(fg="#5b6066")           # 已沉底 → 变暗
        else:
            self.lbl_hhmm.config(fg=FG_SILVER)

        date1 = fmt_date(now, st.primary) + "  " + weekday_name(now, st.primary)
        date2 = ""
        if st.secondary and st.secondary != st.primary:
            date2 = (date_long(now, st.secondary) + "  " +
                     weekday_name(now, st.secondary))

        wrap = self._wrap_base()
        rows = (
            (self.lbl_rest_mine, t("rest_mine", st.primary) if rest1 else "",
             rest1),
            (self.lbl_date, date1, True),
            (self.lbl_date2, date2, bool(date2)),
            (self.lbl_holiday, line or "", bool(line)),
            (self.lbl_eve, eve or "", bool(eve)),
        )
        for i, (lbl, txt, vis) in enumerate(rows):
            if txt:
                if lbl is self.lbl_holiday:
                    lbl.config(text=txt, fg=COLOR_HOLIDAY,
                               wraplength=safe_wraplength(txt, self.m_holiday,
                                                          wrap))
                elif lbl is self.lbl_eve:
                    lbl.config(text=txt,
                               wraplength=safe_wraplength(txt, self.m_eve, wrap))
                else:
                    lbl.config(text=txt)
            if vis and not lbl.winfo_ismapped():
                prev = next((r[0] for r in reversed(rows[:i]) if r[2]), None)
                if prev is not None:
                    lbl.pack(anchor="w", after=prev)
                else:
                    # 第一个可见行必须排在主日期【之前】（休息提示在日期上方）
                    lbl.pack(anchor="w", before=self.lbl_date)
                relayout = True
            elif not vis and lbl.winfo_ismapped():
                lbl.pack_forget()
                relayout = True

        # 周末绿色（有节日时仍用橙色，优先级：节日 > 周末）
        if not line and now.weekday() >= 5:
            self.lbl_date.config(fg=COLOR_WEEKEND)
        elif not line:
            self.lbl_date.config(fg=FG_SILVER)

        # ---- 时间（12 小时制：主时间字号恒定，AM/PM 走右下角小字）----
        if st.hour24:
            self.lbl_hhmm.config(text=now.strftime("%H:%M"))
            self.lbl_ampm.config(text="")
        else:
            h12 = now.hour % 12 or 12               # 0 点显示 12
            self.lbl_hhmm.config(text=f"{h12}:{now.minute:02d}")
            self.lbl_ampm.config(
                text=t("am" if now.hour < 12 else "pm", st.primary))
        self.lbl_ss.config(text=now.strftime("%S"))

        # ---- 第二时区（右列三行：时间 / 城市 / 日期+星期）----
        tz2 = st.zone(second=True)
        if tz2 and st.tz2:
            n2 = datetime.now(tz2)
            if st.hour24:
                self.lbl_tz2.config(text=n2.strftime("%H:%M"))
            else:
                h12 = n2.hour % 12 or 12
                self.lbl_tz2.config(
                    text=f"{h12}:{n2.minute:02d} "
                         f"{t('am' if n2.hour < 12 else 'pm', st.primary)}")
            self.lbl_tz2_name.config(
                text=st.tz2.split("/")[-1].replace("_", " "))

            # 日期 + 星期，配色规则和主时区完全一致
            d2 = n2.date()
            wd2 = weekday_name(n2, st.primary, short=True)
            self.lbl_tz2_date.config(text=f"{d2:%Y-%m-%d} {wd2}")
            if holiday_line(d2, st.tz2, st.primary, st.secondary):
                self.lbl_tz2_date.config(fg=COLOR_HOLIDAY)      # 有节日 → 暖橙
            elif d2.weekday() >= 5:
                self.lbl_tz2_date.config(fg=COLOR_WEEKEND)      # 周末 → 绿
            else:
                self.lbl_tz2_date.config(fg=FG_DIM)

            # ---- 对方是否在休息时段 ----
            rest2 = is_resting(n2)
            self.lbl_tz2.config(fg=COLOR_REST if rest2 else COLOR_NORMAL)
            if rest2:
                self.lbl_rest_theirs.config(
                    text=t("rest_theirs", st.primary))
                if not self.lbl_rest_theirs.winfo_ismapped():
                    self.lbl_rest_theirs.pack(anchor="e")
                    relayout = True
            elif self.lbl_rest_theirs.winfo_ismapped():
                self.lbl_rest_theirs.pack_forget()
                relayout = True

            if not self.lbl_tz2.winfo_ismapped():
                self.lbl_tz2.pack(anchor="e")
                self.lbl_tz2_name.pack(anchor="e")
                self.lbl_tz2_date.pack(anchor="e")
                relayout = True
        elif self.lbl_tz2.winfo_ismapped():
            self.lbl_tz2.pack_forget()
            self.lbl_tz2_name.pack_forget()
            self.lbl_tz2_date.pack_forget()
            self.lbl_rest_theirs.pack_forget()
            relayout = True

        # 🔄 没有第二时区时置灰（点了也没意义）
        try:
            self.btn_swap.config(fg=COLOR_ACCENT if st.tz2 else "#4a4f55")
        except Exception:                        # noqa: BLE001
            pass

        # ---- 番茄钟 ----
        self._refresh_pomo()

        # ★ 内容签名：只要有任何一个字变了（含语言切换导致的行数变化），
        #   就重算窗口高度。否则切到法语/俄语时右列折成两行会被切掉。
        sig = (date1, date2, line or "", eve or "", rest1,
               t("rest_theirs", st.primary) if rest2 else "",
               st.primary, st.secondary, st.tz, st.tz2)
        if sig != getattr(self, "_last_sig", None):
            self._last_sig = sig
            relayout = True

        if relayout:
            self.root.after_idle(self._relayout)

    # ======================================================================
    #  12. 番茄钟
    # ======================================================================
    def _reset_pomo_state(self):
        self.pomo_running = False
        self.pomo_remaining = float(self.state.work_minutes) * 60
        self._update_pomo_label()

    def _update_pomo_label(self):
        total = max(0, int(round(self.pomo_remaining)))
        mm, ss = divmod(total, 60)
        icon = "🍅" if not self.pomo_running else ("⏸" if False else "🍅")
        self.lbl_pomo.config(text=f"{icon} {mm:02d}:{ss:02d}",
                             fg=FG_SILVER if self.pomo_running else FG_DIM)
        self.btn_pomo.config(text="⏸" if self.pomo_running else "▶")

    def _refresh_pomo(self):
        if not self.pomo_running:
            return
        left = self.pomo_end_at - time.monotonic()
        if left <= 0:
            self.pomo_remaining = 0
            self.pomo_running = False
            self._update_pomo_label()
            self._pomo_alert()
            # 自动复位到下一轮
            self.pomo_remaining = float(self.state.work_minutes) * 60
            self._update_pomo_label()
            return
        self.pomo_remaining = left
        self._update_pomo_label()

    def pomo_toggle(self):
        if self.pomo_running:
            self.pomo_running = False
            self.pomo_remaining = max(0.0, self.pomo_end_at - time.monotonic())
        else:
            if self.pomo_remaining <= 0:
                self.pomo_remaining = float(self.state.work_minutes) * 60
            self.pomo_running = True
            self.pomo_end_at = time.monotonic() + self.pomo_remaining
        self._update_pomo_label()

    def pomo_reset(self):
        self.pomo_running = False
        self.pomo_remaining = float(self.state.work_minutes) * 60
        self._update_pomo_label()

    def _pomo_alert(self):
        """提示音 + 闪烁提醒"""
        try:
            if HAS_WINSOUND:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:                        # noqa: BLE001
            pass
        self.lbl_pomo.config(fg=COLOR_REST)

    # ======================================================================
    #  13. 设置面板
    # ======================================================================
    def open_settings(self):
        if self._settings_win is not None:
            try:
                self._settings_win.lift()
                return
            except Exception:                    # noqa: BLE001
                self._settings_win = None

        win = tk.Toplevel(self.root)
        self._settings_win = win
        win.title(t("settings", self.state.primary))
        win.configure(bg=BG_COLOR)
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win.protocol("WM_DELETE_WINDOW", self._close_settings)

        pad = {"padx": 12, "pady": 6}
        row = 0
        st = self.state

        def label(text, r, col=0):
            tk.Label(win, text=text, font=self.f_small, fg=FG_SILVER,
                     bg=BG_COLOR).grid(row=r, column=col, sticky="w", **pad)

        # ---- 主语言 ----
        label(t("primary", st.primary), row)
        self.var_primary = tk.StringVar(value=st.primary)
        cb1 = ttk.Combobox(win, textvariable=self.var_primary, state="readonly",
                           width=18, values=[f"{k} · {LANGUAGE_DICT[k]['name']}"
                                             for k in LANGUAGES])
        cb1.current(LANGUAGES.index(st.primary))
        cb1.grid(row=row, column=1, sticky="w", **pad)
        cb1.bind("<<ComboboxSelected>>",
                 lambda e: self._set_lang(primary=self._lang_of(cb1)))
        row += 1

        # ---- 副语言 ----
        label(t("secondary", st.primary), row)
        self.var_secondary = tk.StringVar(
            value=st.secondary or t("none", st.primary))
        sec_values = [t("none", st.primary)] + \
                     [f"{k} · {LANGUAGE_DICT[k]['name']}" for k in LANGUAGES]
        cb2 = ttk.Combobox(win, textvariable=self.var_secondary, state="readonly",
                           width=18, values=sec_values)
        cb2.current(0 if not st.secondary
                    else LANGUAGES.index(st.secondary) + 1)
        cb2.grid(row=row, column=1, sticky="w", **pad)
        cb2.bind("<<ComboboxSelected>>",
                 lambda e: self._set_lang(secondary=self._lang_of(cb2, allow_none=True)))
        row += 1

        # ---- 主时区 ----
        label(t("timezone", st.primary), row)
        self.combo_tz = self._make_tz_picker(win, st.tz)
        self.combo_tz.grid(row=row, column=1, sticky="w", **pad)
        row += 1

        # ---- 第二时区 ----
        label(t("timezone2", st.primary), row)
        self.combo_tz2 = self._make_tz_picker(win, st.tz2, allow_none=True)
        self.combo_tz2.grid(row=row, column=1, sticky="w", **pad)
        row += 1

        # ---- 24 小时制 ----
        self.var_h24 = tk.BooleanVar(value=st.hour24)
        tk.Checkbutton(win, text=t("hour24", st.primary), variable=self.var_h24,
                       command=self._on_h24,
                       bg=BG_COLOR, fg=FG_SILVER, selectcolor=BG_TOP,
                       activebackground=BG_COLOR, activeforeground=FG_SILVER,
                       font=self.f_small).grid(row=row, column=0, columnspan=2,
                                               sticky="w", **pad)
        row += 1

        # ---- 番茄钟时长 ----
        label(t("work_minutes", st.primary), row)
        self.var_work = tk.StringVar(value=str(st.work_minutes))
        sp = tk.Spinbox(win, from_=1, to=180, width=6, textvariable=self.var_work,
                        command=self._on_work_minutes, bg=BG_TOP, fg=FG_SILVER,
                        insertbackground=FG_SILVER)
        sp.grid(row=row, column=1, sticky="w", **pad)
        sp.bind("<FocusOut>", lambda e: self._on_work_minutes())
        row += 1

        # ---- 全局快捷键（点击后直接按组合键捕获）----
        label(t("hotkey", st.primary), row)
        self.var_hotkey = tk.StringVar(value=self._hotkey_display())
        self.ent_hotkey = tk.Entry(win, textvariable=self.var_hotkey, width=18,
                                   state="readonly", relief="flat",
                                   readonlybackground=BG_TOP, fg=FG_SILVER,
                                   justify="center", cursor="hand2")
        self.ent_hotkey.grid(row=row, column=1, sticky="w", **pad)
        self.ent_hotkey.bind("<Button-1>", self._begin_hotkey_capture)
        self.ent_hotkey.bind("<KeyPress>", self._on_hotkey_key)
        row += 1

        # ---- 关闭 ----
        tk.Button(win, text=t("close", st.primary), command=self._close_settings,
                  bg=BG_TOP, fg=FG_SILVER, activebackground=BG_COLOR,
                  relief="flat", padx=14, pady=4).grid(
            row=row, column=0, columnspan=2, pady=(12, 12))

        win.update_idletasks()
        # 放到主窗口左边，避免挡住
        x = max(10, self.root.winfo_x() - win.winfo_reqwidth() - 12)
        y = self.root.winfo_y()
        win.geometry(f"+{x}+{y}")

    def _close_settings(self):
        if self._settings_win is not None:
            try:
                self._settings_win.destroy()
            except Exception:                    # noqa: BLE001
                pass
            self._settings_win = None
        self.combo_tz = None                     # 控件已销毁，别再被同步到

    def _lang_of(self, combo, allow_none=False):
        """从 'zh · 中文' 里取出 zh；'（不显示）' 返回 None"""
        txt = combo.get()
        if allow_none and txt.startswith("(") or (allow_none and "（" in txt):
            return None
        code = txt.split("·")[0].strip().lower()
        return code if code in LANGUAGES else None

    def _set_lang(self, primary=None, secondary="__unset__"):
        if primary:
            self.state.primary = primary
        if secondary != "__unset__":
            self.state.secondary = secondary
        self.refresh()
        self._save_config()

    def _on_h24(self):
        self.state.hour24 = bool(self.var_h24.get())
        self.refresh()
        self._save_config()

    def _on_work_minutes(self):
        try:
            v = int(self.var_work.get())
        except ValueError:
            return
        v = max(1, min(180, v))
        if v == self.state.work_minutes:
            return
        self.state.work_minutes = v
        if not self.pomo_running:
            self.pomo_reset()
        self._save_config()

    # ---- 可搜索时区下拉框 ----
    def _make_tz_picker(self, parent, current, allow_none=False, width=32):
        """
        键盘实时过滤的时区下拉框。

        ★ 只保留一个 after 循环来刷新时钟，切换时区不重启定时器
          （否则连续切几次会叠出多个 after，秒针会跳得飞快）。

        用法：
          点进输入框 → 全选（打字即覆盖）→ 输入 tokyo/london → 列表实时过滤
          → ↑↓ 选择 → 回车生效；Esc 放弃并恢复原值。
        """
        zones = sorted(available_timezones())
        zone_set = set(zones)
        values = ([t("none", self.state.primary)] if allow_none else []) + zones
        current = current or ""

        combo = ttk.Combobox(parent, values=values, width=width)
        combo.set(current)

        def _hits(typed):
            """按输入过滤；输入框里就是当前时区名时，视为"想浏览全部" """
            txt = typed.strip().lower()
            if not txt or txt in (current.lower(), self.state.tz.lower()):
                return zones
            out = []
            for z in zones:
                if txt in z.lower():
                    out.append(z)
                    continue
                city = z.split("/")[-1].replace("_", " ").lower()
                if txt in city:
                    out.append(z)
            return out

        def refresh_values(event=None):
            """下拉列表打开前刷新候选（鼠标点箭头也能用）"""
            combo["values"] = _hits(combo.get())

        def on_key(event):
            """
            按键实时过滤。

            ★ 必须【同步】调用 refresh_values，不能用 after_idle：
              KeyRelease 触发时字符已经插进输入框，同步刷新是准的；
              而 after_idle 在测试/自动化场景下可能错过本轮事件循环。
            """
            # 方向键/回车/退出交给下拉框自己处理
            if event.keysym in ("Up", "Down", "Return", "KP_Enter", "Escape",
                                "Tab", "Left", "Right", "Home", "End",
                                "Shift_L", "Shift_R", "Control_L", "Control_R",
                                "Alt_L", "Alt_R", "Delete"):
                return
            refresh_values()                   # ← 同步，立刻生效
            # ★ 绝对不要在这里自动弹出下拉列表！
            #   一旦 Post 了 popdown，键盘焦点会跑到列表上，后面打的字就全丢了
            #   （这就是"只能滚鼠标、打不进字"的根因）。
            #   想浏览列表，用户按 ↓ 或点箭头即可。

        def popup():
            """把下拉列表弹出来（ttk 内部命令，失败就退回 <Down>）"""
            try:
                combo.tk.call("ttk::combobox::Post", combo)
            except Exception:                    # noqa: BLE001
                try:
                    combo.event_generate("<Down>")
                except Exception:                # noqa: BLE001
                    pass

        def commit(text):
            """应用选中的时区"""
            if allow_none and (text.startswith("(") or "（" in text):
                self.state.tz2 = None
            elif allow_none:
                if text in zone_set:
                    self.state.tz2 = text
                else:
                    return False
            else:
                if text not in zone_set:
                    return False
                self.state.tz = text
            current_valid[0] = text
            self._sync_tz_widgets()
            self.refresh()
            self._relayout()
            self._save_config()
            return True

        current_valid = [current]

        def on_select(event=None):
            commit(combo.get().strip())

        def on_return(event=None):
            """回车：能精确匹配就用它，否则取过滤结果的第一条"""
            txt = combo.get().strip()
            if not commit(txt):
                hits = _hits(txt)
                if hits:
                    combo.set(hits[0])
                    commit(hits[0])
            return "break"

        def on_escape(event=None):
            combo.set(current_valid[0])
            combo["values"] = values
            return "break"

        def on_focus_in(event=None):
            # 全选：一打字就把旧的时区名替换掉
            try:
                combo.selection_range(0, "end")
                combo.icursor("end")
            except Exception:                    # noqa: BLE001
                pass

        def on_click(event=None):
            """
            ★ 无边框窗口（overrideredirect）不会被系统当作可激活窗口，
              点一下并不会自动把键盘焦点给它。
              所以点击时必须【显式】激活窗口 + 把焦点塞进输入框，
              否则打字会落到别处（表现就是"完全没法输入"）。
            """
            try:
                self.root.focus_force()      # 先激活整个窗口
                combo.focus_set()            # 再把键盘焦点给输入框
                combo.icursor("end")
            except Exception:                # noqa: BLE001
                pass
            return None

        def on_focus_in(event=None):
            # 全选：一打字就把旧的时区名替换掉
            try:
                combo.selection_range(0, "end")
                combo.icursor("end")
            except Exception:                # noqa: BLE001
                pass

        combo.configure(postcommand=refresh_values)
        combo.bind("<Button-1>", on_click)     # 点击抢焦点
        combo.bind("<FocusIn>", on_focus_in)
        combo.bind("<KeyRelease>", on_key)
        combo.bind("<<ComboboxSelected>>", on_select)
        combo.bind("<Return>", on_return)
        combo.bind("<KP_Enter>", on_return)
        combo.bind("<Escape>", on_escape)
        return combo

    def swap_zones(self):
        """
        主副时区一键互换。

        ★ 只换时区，不换语言，也不动窗口位置/尺寸——
          换完立刻落盘，下次启动保持互换后的状态。
        """
        st = self.state
        if not st.tz2:
            return                               # 没有第二时区，点了没意义
        st.tz, st.tz2 = st.tz2, st.tz
        self._sync_tz_widgets()
        self.refresh()
        self._relayout()
        self._save_config()

    def _sync_tz_widgets(self):
        """把 state.tz 同步到所有时区下拉框（顶栏那个 + 设置面板里那个）"""
        for name in ("combo_top", "combo_tz"):
            c = getattr(self, name, None)
            if c is not None:
                try:
                    c.set(self.state.tz)
                except Exception:                # noqa: BLE001
                    pass

    def _relayout(self):
        """内容变化后重算高度（夹在 [WIN_MIN_H, WIN_MAX_H]），位置不动"""
        try:
            self.root.update_idletasks()
            h = max(WIN_MIN_H, min(WIN_MAX_H, self.root.winfo_reqheight()))
            x, y = self.root.winfo_x(), self.root.winfo_y()
            self.root.geometry(f"{WIN_WIDTH}x{h}+{x}+{y}")
        except Exception:                        # noqa: BLE001
            pass

    # ======================================================================
    #  14. 退出
    # ======================================================================
    def close(self):
        if self.closing:
            return
        self.closing = True
        self._save_config()              # ★ 退出前保存最后一次状态
        for job in (self._tick_job, self._hotkey_job):
            if job:
                try:
                    self.root.after_cancel(job)
                except Exception:                # noqa: BLE001
                    pass
        self._tick_job = self._hotkey_job = None
        try:
            if self._hotkey_watcher:
                self._hotkey_watcher.stop()
        except Exception:                        # noqa: BLE001
            pass
        self._close_settings()
        try:
            self.root.destroy()
        except Exception:                        # noqa: BLE001
            pass


# ===========================================================================
#  15. 入口
# ===========================================================================
def enable_dpi_awareness():
    """高分屏下保持清晰"""
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:                            # noqa: BLE001
        pass


def main():
    # 让 ttk 的下拉框在深色背景下不至于太难看
    enable_dpi_awareness()
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:                            # noqa: BLE001
        pass
    app = ClockApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
