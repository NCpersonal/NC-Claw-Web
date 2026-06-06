#!/usr/bin/env python3
__version__ = "0.7.4"
"""
Claw v0.7.4 — Terminal AI Assistant
  Multi-Agent · Group Chat · Per-Agent API · Skills · Web Gateway
Usage: python claw.py
Zero dependencies — Python 3.8+ stdlib only.
"""

import json, os, sys, subprocess, platform, re, time, shutil, signal, readline, threading, datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

# ━━━ Config ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONFIG_FILE = Path.home() / ".claw_config.json"
HISTORY_FILE = Path.home() / ".claw_history"
SKILLS_DIR = Path.home() / ".claw" / "workspace" / "skills"
WORKSPACE_FILE = Path.home() / ".claw" / "workspace" / "AGENTS.md"
AGENTS_FILE = Path.home() / ".claw" / "agents.json"
GROUPS_FILE = Path.home() / ".claw" / "groups.json"

MAX_HISTORY = 20
MAX_TOKENS = 4096
TEMPERATURE = 0.7
MAX_CHAIN_DEPTH = 5

config = {
    "api_key": os.getenv("AI_API_KEY", ""),
    "api_base": os.getenv("AI_API_BASE", "https://api.openai.com/v1"),
    "model": os.getenv("AI_MODEL", "gpt-4o"),
    "skills": [],
}

if CONFIG_FILE.exists():
    try:
        with open(CONFIG_FILE) as f:
            saved = json.load(f)
        config.update({k: v for k, v in saved.items() if v})
    except Exception:
        pass


def save_config():
    s = {}
    for k, v in config.items():
        if k != "api_key" or v:
            s[k] = v
    CONFIG_FILE.write_text(json.dumps(s, indent=2))


# ━━━ Colors ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class C:
    R = "\033[0m"
    B = "\033[1m"
    D = "\033[2m"
    RED = "\033[31m"
    GRN = "\033[32m"
    YEL = "\033[33m"
    BLU = "\033[34m"
    MAG = "\033[35m"
    CYN = "\033[36m"
    WHT = "\033[37m"
    DIM = "\033[90m"


AGENT_COLOR_LIST = [C.GRN, C.BLU, C.MAG, C.YEL, C.RED, C.CYN]
AGENT_COLOR_NAMES = ["green", "blue", "magenta", "yellow", "red", "cyan"]

# ━━━ Log System ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

log_level = 1  # 0=off, 1=normal, 2=verbose
log_lock = threading.Lock()


def gw_log(level, tag, msg, color=""):
    """Thread-safe gateway log to terminal."""
    if log_level < level:
        return
    now = datetime.datetime.now().strftime("%H:%M:%S")
    c = color or C.DIM
    with log_lock:
        sys.stdout.write("\r\033[K")  # clear current line
        sys.stdout.write("  {}{}{} {}{}{}{} {}\n".format(
            C.DIM, now, C.R, c, tag, C.R, C.DIM, msg, C.R))
        sys.stdout.write("{}you{}> ".format(C.BLU, C.R) if current_mode == "default" else "")
        sys.stdout.flush()


def gw_log_info(tag, msg):
    gw_log(1, tag, msg, C.DIM)


def gw_log_chat(tag, msg):
    gw_log(1, tag, msg, C.GRN)


def gw_log_error(tag, msg):
    gw_log(1, tag, msg, C.RED)


def gw_log_verbose(tag, msg):
    gw_log(2, tag, msg, C.DIM)


# ━━━ Token Usage ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

token_usage = {
    "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
    "requests": 0, "last_prompt": 0, "last_completion": 0,
}


def _print_tokens():
    lp, lc = token_usage["last_prompt"], token_usage["last_completion"]
    if lp > 0 or lc > 0:
        print("  {}{}p:{} {} {}c:{} {} {}t:{} {}{}".format(
            C.DIM, C.CYN, C.R, lp, C.CYN, C.R, lc, C.CYN, C.R, lp + lc, C.DIM, C.R))


# ━━━ Skills System ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BUILTIN_SKILLS = {
    "coder": {"name": "Coder", "desc": "编程助手", "prompt": "## Skill: Coder\nYou are an expert programmer."},
    "analyst": {"name": "Analyst", "desc": "数据分析", "prompt": "## Skill: Analyst\nYou are a data analyst."},
    "writer": {"name": "Writer", "desc": "写作助手", "prompt": "## Skill: Writer\nYou are a professional writer."},
    "sysadmin": {"name": "SysAdmin", "desc": "运维助手", "prompt": "## Skill: SysAdmin\nYou are a Linux sysadmin."},
    "translator": {"name": "Translator", "desc": "翻译助手", "prompt": "## Skill: Translator\nYou are a professional translator."},
}


def get_all_skills():
    skills = dict(BUILTIN_SKILLS)
    if SKILLS_DIR.exists():
        for d in sorted(SKILLS_DIR.iterdir()):
            if not d.is_dir():
                continue
            f = d / "SKILL.md"
            if f.exists():
                content = f.read_text("utf-8", errors="replace")
                lines = content.strip().split("\n")
                name, desc = d.name, ""
                if lines and lines[0].startswith("# "): name = lines[0][2:].strip()
                if len(lines) > 1 and lines[1].startswith("> "): desc = lines[1][2:].strip()
                skills[d.name] = {"name": name, "desc": desc or d.name, "prompt": content}
    return skills


def get_loaded_skills():
    all_s = get_all_skills()
    return [all_s[s] for s in config.get("skills", []) if s in all_s]


def skill_prompt():
    loaded = get_loaded_skills()
    return "\n\n".join(s["prompt"] for s in loaded) if loaded else ""


def cmd_skill(args):
    all_skills = get_all_skills()
    if not args or args == "list":
        loaded_ids = set(config.get("skills", []))
        print("\n  {}Skills{}\n".format(C.CYN, C.R))
        for sid, s in BUILTIN_SKILLS.items():
            m = "{}*{}".format(C.GRN, C.R) if sid in loaded_ids else " "
            print("    {} {}{:<14}{} {}".format(m, C.B, sid, C.R, s["desc"]))
        custom = {k: v for k, v in all_skills.items() if k not in BUILTIN_SKILLS}
        if custom:
            print()
            for sid, s in custom.items():
                m = "{}*{}".format(C.GRN, C.R) if sid in loaded_ids else " "
                print("    {} {}{:<14}{} {}".format(m, C.B, sid, C.R, s["desc"]))
        if loaded_ids:
            print("\n  {}Loaded:{} {}".format(C.D, C.R, ", ".join(loaded_ids)))
        print()
        return
    parts = args.split(None, 1)
    action, target = parts[0], parts[1].strip() if len(parts) > 1 else ""
    if action == "load":
        if target not in all_skills:
            print("  {}Not found{}\n".format(C.RED, C.R)); return
        if target not in config["skills"]:
            config["skills"].append(target); save_config()
        print("  {}Loaded: {}{}\n".format(C.GRN, target, C.R))
    elif action == "unload":
        if target in config["skills"]:
            config["skills"].remove(target); save_config()
        print("  {}Unloaded{}\n".format(C.D, C.R))
    elif action == "clear":
        config["skills"] = []; save_config()
        print("  {}Cleared{}\n".format(C.D, C.R))
    else:
        print("  {}Usage: /skill [list|load|unload|clear]{}\n".format(C.D, C.R))


# ━━━ System Prompt ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

messages = []


def build_system():
    si = "{} {} ({})".format(platform.system(), platform.release(), platform.machine())
    sh = "cmd/PowerShell" if platform.system() == "Windows" else os.getenv("SHELL", "/bin/bash")
    cmd_list = (
        "  //exec <cmd>              Shell command\n"
        "  //read <path>             Read file / list dir\n"
        "  //write <path>            Write file (content until //end)\n"
        "  //copy <src> <dst>        Copy file/dir\n"
        "  //move <src> <dst>        Move / rename\n"
        "  //mkdir <path>            Create directory\n"
        "  //tree <dir> [--depth N]  Directory tree\n"
        "  //search <pat> <dir>      Find + grep\n"
        "  //info                    System info\n"
        "  //process [--filter <n>]  Processes\n"
        "  //kill <pid|name>         Kill process\n"
        "  //env <key>               Env variable\n"
        "  //time                    Date/time\n"
        "  //ip                      IP addresses\n"
        "  //ping <host>             Ping\n"
        "  //python <code>           Python snippet\n"
        "  //git <args>              Git command\n"
        "  //open <target>           Open app/file/URL\n"
        "  //browse <url>            Fetch URL as text\n"
        "  //download <url> <path>   Download file\n"
    )
    base = (
        "You are Claw, a local AI assistant. Execute commands to help the user.\n"
        "\n## Commands (embed naturally in your reply)\n" + cmd_list +
        "\n## CRITICAL: Command Format Rules\n"
        "- EVERY command MUST start with // on its own line. No exceptions.\n"
        "- WRONG:  dpkg -l | grep foo        (missing // — will NOT run)\n"
        "- RIGHT:  //exec dpkg -l | grep foo  (has // — will run)\n"
        "- WRONG:  ls /home                   (missing // — will NOT run)\n"
        "- RIGHT:  //exec ls /home            (has // — will run)\n"
        "- Single-line: //exec ls -la\n"
        "- Multi-line (write, python): start with //keyword, content on next lines, end with //end\n"
        "- Example:\n"
        "  //write /tmp/test.py\n"
        "  print('hello')\n"
        "  //end\n"
        "- NEVER wrap commands in backticks or code fences\n"
        "- Pipes (|) only work with //exec, NOT with //read\n"
        "- //python does NOT support -c flag, write code directly after //python\n"
        "\n## Rules\n"
        "- Use commands when helpful, naturally within text\n"
        "- Multiple commands OK; results return automatically, then continue\n"
        "- Ask before destructive ops. Be concise.\n"
        "\nEnvironment: " + si + " | Shell: " + sh + " | CWD: " + os.getcwd() + "\n"
    )


    if WORKSPACE_FILE.exists():
        try:
            w = WORKSPACE_FILE.read_text("utf-8", errors="replace")
            if w.strip(): base += "\n\n## Workspace\n" + w
        except Exception: pass
    sp = skill_prompt()
    if sp: base += "\n\n" + sp
    return base


# ━━━ Agent API ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_agent_api(name):
    a = agents.get(name, {})
    return (a.get("api_key") or config["api_key"], a.get("api_base") or config["api_base"], a.get("model") or config["model"])

def get_agent_api_display(name):
    key, base, model = get_agent_api(name)
    a = agents.get(name, {})
    return {"api_key": key, "api_key_source": "agent" if a.get("api_key") else "global",
            "api_base": base, "api_base_source": "agent" if a.get("api_base") else "global",
            "model": model, "model_source": "agent" if a.get("model") else "global"}

def _mask_key(key):
    if not key: return "(not set)"
    return key[:8] + "..." + key[-4:] if len(key) > 12 else "***"


# ━━━ Agent/Group State ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

agents = {}
groups = {}
current_mode = "default"
current_target = None
sudo_password = ""  # In-memory only, never persisted

def load_agents():
    global agents
    if AGENTS_FILE.exists():
        try: agents = json.loads(AGENTS_FILE.read_text("utf-8"))
        except: pass

def save_agents():
    AGENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    AGENTS_FILE.write_text(json.dumps(agents, indent=2, ensure_ascii=False), "utf-8")

def load_groups():
    global groups
    if GROUPS_FILE.exists():
        try: groups = json.loads(GROUPS_FILE.read_text("utf-8"))
        except: pass

def save_groups():
    GROUPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    GROUPS_FILE.write_text(json.dumps(groups, indent=2, ensure_ascii=False), "utf-8")

def get_agent_color(name):
    if name in agents:
        return AGENT_COLOR_LIST[agents[name].get("color_idx", 0) % len(AGENT_COLOR_LIST)]
    return C.GRN

def next_color_idx():
    used = {a.get("color_idx", -1) for a in agents.values()}
    for i in range(len(AGENT_COLOR_LIST)):
        if i not in used: return i
    return len(used) % len(AGENT_COLOR_LIST)

def get_prompt():
    if current_mode == "agent" and current_target:
        c = get_agent_color(current_target)
        return "{}you{} {}→{}{}{}> ".format(C.BLU, C.R, C.D, c, current_target, C.R)
    if current_mode == "group" and current_target:
        return "{}you{} {}[{}{}{}]{}> ".format(C.BLU, C.R, C.D, C.GRN, current_target, C.D, C.R)
    return "{}you{}> ".format(C.BLU, C.R)

def build_agent_system(name):
    a = agents.get(name, {})
    return build_system() + "\n\n## Agent Identity\nYou are '{}' (@{}).\n{}\nStay in character. Be concise.".format(
        a.get("display_name", name), name, a.get("role", ""))

def build_group_system(agent_name, group_name):
    a = agents.get(agent_name, {})
    g = groups.get(group_name, {})
    base = build_system()
    members = []
    for m in g.get("members", []):
        if m in agents:
            tag = " (You)" if m == agent_name else ""
            members.append("  - @{}{}: {} — {}".format(m, tag, agents[m]["display_name"], agents[m].get("role", "")[:80]))
    return base + """

## Agent Identity
You are '{}' (@{}).
{}

## Group Chat: {}
Members:
{}

### Rules:
- Use @username to direct messages to specific members
- When @mentioned, you MUST respond
- Keep responses concise and on-topic
- Stay in character as {}""".format(
        a.get("display_name", agent_name), agent_name, a.get("role", ""),
        group_name, "\n".join(members), a.get("display_name", agent_name))

def extract_mentions(text):
    return list(set(re.findall(r'@(\w+)', text)))

def group_to_api_msgs(group_name, agent_name):
    group = groups.get(group_name, {})
    sys_content = build_group_system(agent_name, group_name)
    api_msgs = [{"role": "system", "content": sys_content}]
    for m in group.get("history", [])[-MAX_HISTORY * 2:]:
        sender, content = m.get("agent", "user"), m.get("content", "")
        if sender == agent_name and m.get("role") == "assistant":
            api_msgs.append({"role": "assistant", "content": content})
        else:
            formatted = content if sender in ("user", "system") else "[{}]: {}".format(sender, content)
            if api_msgs and api_msgs[-1]["role"] == "user":
                api_msgs[-1]["content"] += "\n\n" + formatted
            else:
                api_msgs.append({"role": "user", "content": formatted})
    return api_msgs


# ━━━ Agent Commands (terminal) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def cmd_agent(args):
    global current_mode, current_target
    if not args or args == "list":
        print("\n  {}Agents{}\n".format(C.CYN, C.R))
        if not agents:
            print("  {}None. /agent create <name>{}\n".format(C.D, C.R)); return
        for name, a in agents.items():
            c = get_agent_color(name)
            active = (current_mode == "agent" and current_target == name)
            marker = "{}\u25cf{}".format(c, C.R) if active else " "
            _, base, model = get_agent_api(name)
            bs = base.split("//")[-1].split("/")[0][:25]
            print("  {} {}{:<12}{} {:<14} {}{}{} @ {}{}{}".format(
                marker, c, name, C.R, a["display_name"], C.D, model, C.R, C.D, bs, C.R))
        print()
        return
    parts = args.split(None, 1)
    action, rest = parts[0], parts[1].strip() if len(parts) > 1 else ""

    if action == "create":
        if not rest: print("  {}/agent create <name>{}\n".format(C.YEL, C.R)); return
        name = rest.split()[0].lower()
        if not re.match(r'^[a-zA-Z]\w*$', name): print("  {}Invalid{}\n".format(C.RED, C.R)); return
        if name in agents: print("  {}Exists{}\n".format(C.RED, C.R)); return
        dn = input("  {}Display name [{}]: {}".format(C.D, name.title(), C.R)).strip() or name.title()
        role = input("  {}Role: {}".format(C.D, C.R)).strip()
        print("  {}API (blank=global){}".format(C.YEL, C.R))
        ak = input("  {}Key:    {}".format(C.D, C.R)).strip()
        ab = input("  {}Base:   {}".format(C.D, C.R)).strip()
        am = input("  {}Model:  {}".format(C.D, C.R)).strip()
        agents[name] = {"display_name": dn, "role": role or "Helpful assistant.",
            "api_key": ak or None, "api_base": ab or None, "model": am or None,
            "color_idx": next_color_idx(), "history": []}
        save_agents()
        print("\n  {}Created:{} {}{}{}\n".format(C.GRN, C.R, get_agent_color(name), name, C.R))

    elif action == "switch":
        if not rest or rest not in agents: print("  {}Not found{}\n".format(C.RED, C.R)); return
        current_mode, current_target = "agent", rest
        print("  {}\u2192 {}{}{}\n".format(C.GRN, get_agent_color(rest), agents[rest]["display_name"], C.R))

    elif action == "back":
        current_mode, current_target = "default", None
        print("  {}Default mode{}\n".format(C.D, C.R))

    elif action == "delete":
        if rest not in agents: print("  {}Not found{}\n".format(C.RED, C.R)); return
        del agents[rest]
        for g in groups.values():
            if rest in g.get("members", []): g["members"].remove(rest)
        save_agents(); save_groups()
        if current_mode == "agent" and current_target == rest: current_mode, current_target = "default", None
        print("  {}Deleted: {}{}\n".format(C.D, rest, C.R))

    elif action == "api":
        if not rest: print("  {}/agent api <name> [model=x api_key=x api_base=x]{}\n".format(C.YEL, C.R)); return
        tokens = rest.split(None, 1)
        name = tokens[0]
        if name not in agents: print("  {}Not found{}\n".format(C.RED, C.R)); return
        if len(tokens) < 2:
            eff = get_agent_api_display(name)
            print("\n  {}Model:{} {} ({})".format(C.D, C.R, eff["model"], eff["model_source"]))
            print("  {}Base:{}  {} ({})".format(C.D, C.R, eff["api_base"], eff["api_base_source"]))
            print("  {}Key:{}   {} ({})\n".format(C.D, C.R, _mask_key(eff["api_key"]), eff["api_key_source"]))
            return
        parsed = dict(re.findall(r'(api_key|api_base|model)\s*=\s*(\S+)', tokens[1]))
        a = agents[name]
        for k, v in parsed.items():
            a[k] = None if v.lower() == "clear" else v
            print("  {}{}{} \u2192 {}".format(C.GRN, k, C.R, v))
        save_agents()
        print()

    elif action in ("info", "prompt", "model", "rename", "clear"):
        # Keep existing logic for these subcommands
        if action == "info" and rest in agents:
            a = agents[rest]
            eff = get_agent_api_display(rest)
            print("\n  {}{}{} @{}".format(get_agent_color(rest), a["display_name"], C.R, rest))
            print("  {}Role:{} {}".format(C.D, C.R, a.get("role", "N/A")))
            print("  {}Model:{} {} ({})".format(C.D, C.R, eff["model"], eff["model_source"]))
            print("  {}Base:{}  {} ({})".format(C.D, C.R, eff["api_base"], eff["api_base_source"]))
            print("  {}Key:{}   {} ({})\n".format(C.D, C.R, _mask_key(eff["api_key"]), eff["api_key_source"]))
        elif action == "prompt":
            p = rest.split(None, 1)
            if p and p[0] in agents:
                if len(p) > 1: agents[p[0]]["role"] = p[1]; save_agents(); print("  {}Updated{}\n".format(C.GRN, C.R))
                else: print("  {}{}{}\n".format(C.D, C.R, agents[p[0]].get("role", "N/A")))
        elif action == "model":
            p = rest.split(None, 1)
            if p and p[0] in agents:
                if len(p) > 1: agents[p[0]]["model"] = p[1]; save_agents(); print("  {}{}\u2192{}{}\n".format(C.GRN, p[0], p[1], C.R))
                else: print("  {}{}: {}{}\n".format(C.D, p[0], get_agent_api_display(p[0])["model"], C.R))
        elif action == "rename":
            p = rest.split(None, 1)
            if len(p) >= 2 and p[0] in agents:
                old, new = p[0], p[1].strip().lower()
                agents[new] = agents.pop(old)
                for g in groups.values():
                    if old in g.get("members", []): g["members"] = [new if m == old else m for m in g["members"]]
                save_agents(); save_groups()
                if current_target == old: current_target = new
                print("  {}{} \u2192 {}{}\n".format(C.GRN, old, new, C.R))
        elif action == "clear" and rest in agents:
            agents[rest]["history"] = []; save_agents()
            print("  {}Cleared{}\n".format(C.D, C.R))
    else:
        print("  {}/agent [list|create|switch|back|delete|info|api|prompt|model|rename|clear]{}\n".format(C.D, C.R))


# ━━━ Group Commands (terminal) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def cmd_group(args):
    global current_mode, current_target
    if not args or args == "list":
        print("\n  {}Groups{}\n".format(C.CYN, C.R))
        if not groups:
            print("  {}None. /group create <name>{}\n".format(C.D, C.R)); return
        for gn, g in groups.items():
            active = (current_mode == "group" and current_target == gn)
            m = "{}\u25cf{}".format(C.GRN, C.R) if active else " "
            ms = ", ".join("@{}".format(x) for x in g.get("members", []))
            print("  {} {}{:<14}{} [{}]".format(m, C.B, gn, C.R, ms))
        print()
        return
    parts = args.split(None, 1)
    action, rest = parts[0], parts[1].strip() if len(parts) > 1 else ""

    if action == "create":
        if not rest: print("  {}/group create <name>{}\n".format(C.YEL, C.R)); return
        name = rest.split()[0].lower()
        if name in groups: print("  {}Exists{}\n".format(C.RED, C.R)); return
        desc = input("  {}Description: {}".format(C.D, C.R)).strip()
        avail = ", ".join(agents.keys()) or "(none)"
        print("  {}Agents: {}{}".format(C.D, avail, C.R))
        mi = input("  {}Members (comma): {}".format(C.D, C.R)).strip()
        members = [x.strip().lower() for x in mi.split(",") if x.strip()]
        inv = [x for x in members if x not in agents]
        if inv: print("  {}Unknown: {}{}\n".format(C.RED, ", ".join(inv), C.R)); return
        groups[name] = {"desc": desc, "members": members, "history": []}
        save_groups()
        print("\n  {}Created:{} {} [{}]\n".format(C.GRN, C.R, name, ", ".join(members)))

    elif action == "enter":
        if rest not in groups: print("  {}Not found{}\n".format(C.RED, C.R)); return
        current_mode, current_target = "group", rest
        ms = " ".join("{}@{}{}".format(get_agent_color(m), m, C.R) for m in groups[rest]["members"])
        print("  {}Entered:{} {} {}[{}]{}\n".format(C.GRN, C.R, C.B, rest, ms, C.R))

    elif action == "leave":
        if current_mode == "group":
            print("  {}Left {}{}\n".format(C.D, current_target, C.R))
            current_mode, current_target = "default", None
        else: print("  {}Not in group{}\n".format(C.D, C.R))

    elif action == "delete":
        if rest not in groups: print("  {}Not found{}\n".format(C.RED, C.R)); return
        del groups[rest]; save_groups()
        if current_mode == "group" and current_target == rest: current_mode, current_target = "default", None
        print("  {}Deleted{}\n".format(C.D, C.R))

    elif action == "add":
        p = rest.split(None, 1)
        if len(p) < 2 or p[0] not in groups: print("  {}/group add <g> <a>{}\n".format(C.YEL, C.R)); return
        if p[1].strip() in agents and p[1].strip() not in groups[p[0]].get("members", []):
            groups[p[0]]["members"].append(p[1].strip()); save_groups()
            print("  {}Added{}\n".format(C.GRN, C.R))
        else: print("  {}Error{}\n".format(C.RED, C.R))

    elif action == "remove":
        p = rest.split(None, 1)
        if len(p) >= 2 and p[0] in groups and p[1].strip() in groups[p[0]].get("members", []):
            groups[p[0]]["members"].remove(p[1].strip()); save_groups()
            print("  {}Removed{}\n".format(C.D, C.R))

    elif action in ("info", "clear"):
        if action == "info" and rest in groups:
            g = groups[rest]
            print("\n  {}{}{} {}".format(C.B, rest, C.R, g.get("desc", "")))
            for m in g.get("members", []):
                if m in agents: print("    {}@{}{} — {}".format(get_agent_color(m), m, C.R, agents[m]["display_name"]))
            print()
        elif action == "clear" and rest in groups:
            groups[rest]["history"] = []; save_groups(); print("  {}Cleared{}\n".format(C.D, C.R))
    else:
        print("  {}/group [list|create|enter|leave|delete|add|remove|info|clear]{}\n".format(C.D, C.R))


# ━━━ Command Parser & Executor ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CMD_TYPES = [
    "exec", "open", "read", "write", "browse", "download",
    "copy", "move", "delete", "mkdir", "tree", "search",
    "info", "process", "kill", "env", "time", "ip", "ping",
    "python", "git",
    "ls", "cat", "head", "tail", "wc", "grep", "find",
    "df", "free", "uname", "whoami", "id", "pwd",
]

CMD_ALIAS = {
    "ls": "exec", "cat": "exec", "head": "exec", "tail": "exec",
    "wc": "exec", "grep": "exec", "find": "exec", "df": "exec",
    "free": "exec", "uname": "exec", "whoami": "exec", "id": "exec",
    "pwd": "exec",
}

MULTILINE_KEYWORDS = {"write", "python", "exec"}

SINGLELINE_KEYWORDS = {
    "read", "copy", "move", "mkdir", "tree", "search",
    "info", "process", "kill", "env", "time", "ip",
    "ping", "git", "open", "browse", "download",
    "ls", "cat", "head", "tail", "wc", "grep", "find",
    "df", "free", "uname", "whoami", "id", "pwd",
}

# Known shell binaries for bare-command fallback detection
SHELL_BINS = {
    "ls", "cat", "head", "tail", "grep", "find", "df", "free",
    "uname", "whoami", "id", "pwd", "wc", "awk", "sed", "sort",
    "ps", "top", "lsof", "ss", "ip", "ifconfig", "hostname",
    "dpkg", "apt", "rpm", "pacman", "snap",
    "systemctl", "journalctl", "dmesg", "mount", "blkid", "lsblk",
    "lscpu", "lsusb", "lspci", "lsmod", "modprobe",
    "ping", "curl", "wget", "ssh", "scp", "rsync",
    "git", "docker", "podman",
    "vcgencmd", "raspi-config", "gpio",
    "python", "python3", "node", "npm",
    "tar", "zip", "unzip", "gzip",
    "chmod", "chown", "mkdir", "cp", "mv", "touch", "ln",
    "echo", "date", "uptime", "file", "stat", "du",
    "make", "gcc", "g++",
    "htop", "nethogs", "tcpdump", "nmcli",
    "getent", "cut", "tr", "tee", "xargs", "which",
    "lsmod", "modinfo", "dmesg",
}

DANGER = [
    r'\brm\s+(-[a-zA-Z]*r|--recursive)\b', r'\bmkfs\b', r'\bdd\s+if=',
    r'\b(shutdown|reboot|halt)\b', r'\bkill\s+(-9\s+)?1\b', r'\brm\s+-rf\s+[~/]',
]


def is_dangerous(cmd):
    return any(re.search(p, cmd, re.I) for p in DANGER)


def _strip_artifacts(text):
    """Remove markdown fences/formatting but preserve // commands."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'```[a-zA-Z]*\s*\n', '\n', text)
    text = re.sub(r'```\s*\n', '\n', text)
    text = text.replace('```', '')
    text = re.sub(r'`([^`]*)`', r'\1', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    return text


def _parse_single_line(text):
    """Parse 'keyword args' into a command dict, or None."""
    text = text.strip().strip('`"\'*').rstrip('.,;:!?')
    if not text:
        return None
    parts = text.split(None, 1)
    if not parts:
        return None
    keyword = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""
    # Alias routing
    if keyword in CMD_ALIAS:
        args = keyword + (" " + args if args else "")
        keyword = CMD_ALIAS[keyword]
    if keyword not in CMD_TYPES:
        return None
    if keyword == "write" and not args:
        return None
    if keyword == "python" and not args:
        return None
    if keyword == "exec" and not args:
        return None
    return {"type": keyword, "args": args}


def parse_commands(text):
    """
    Parse commands from AI reply.

    Primary:   //keyword args          (single-line)
               //keyword [args]        (multi-line, body until //end)

    Fallback:  bare 'command args' lines when no // found at all
    """
    cmds = []
    clean = _strip_artifacts(text)
    lines = clean.split("\n")

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        # ── Look for //keyword ──
        cmd_match = re.match(r'^//(\w+)(?:\s+(.*))?$', stripped)
        if not cmd_match:
            i += 1
            continue

        keyword = cmd_match.group(1).lower()
        first_args = (cmd_match.group(2) or "").strip().rstrip('.,;:!?')

        # Skip stray //end
        if keyword == "end":
            i += 1
            continue

        # Alias routing
        if keyword in CMD_ALIAS:
            first_args = keyword + (" " + first_args if first_args else "")
            keyword = CMD_ALIAS[keyword]

        if keyword not in CMD_TYPES:
            i += 1
            continue

        # ── Single-line keyword: no body needed ──
        if keyword in SINGLELINE_KEYWORDS and keyword not in MULTILINE_KEYWORDS:
            if first_args:
                cmds.append({"type": keyword, "args": first_args})
            i += 1
            continue

        # ── Multi-line keyword: collect body until //end ──
        if keyword in MULTILINE_KEYWORDS:
            body_lines = []
            i += 1
            while i < len(lines):
                if lines[i].strip() == "//end":
                    break
                body_lines.append(lines[i])
                i += 1

            if i < len(lines) and lines[i].strip() == "//end":
                i += 1  # consume //end

            body = "\n".join(body_lines)

            if keyword == "write":
                path = first_args.strip('`"\'*') if first_args else ""
                if path:
                    cmds.append({"type": "write", "args": path, "content": body})

            elif keyword == "python":
                code = body
                if first_args:
                    cm = re.match(r'^-c\s+["\'](.*)["\']$', first_args, re.DOTALL)
                    if cm:
                        code = cm.group(1)
                    elif not body.strip():
                        code = first_args
                    else:
                        code = first_args + "\n" + body
                if code.strip():
                    cmds.append({"type": "python", "args": code.strip()})

            elif keyword == "exec":
                combined = (first_args + "\n" + body).strip() if first_args and body.strip() else body.strip() or first_args
                if combined:
                    cmds.append({"type": "exec", "args": combined})
            continue

        # ── Fallback: treat as single-line ──
        if first_args:
            cmd = _parse_single_line(keyword + " " + first_args)
            if cmd:
                cmds.append(cmd)
        i += 1

    # ── Ultimate fallback: detect bare commands (AI forgot //) ──
    if not cmds:
        for line in lines:
            stripped = line.strip()
            if not stripped or len(stripped) > 200:
                continue
            # Skip markdown/prose
            if stripped.startswith(("#", ">", "|", "-", "*", "1.", "2.", "3.")):
                continue
            if any(ch in stripped for ch in ("吗", "呢", "的", "是", "了", "在", "有", "我", "你")):
                continue
            parts = stripped.split(None, 1)
            if not parts:
                continue
            cmd_name = parts[0].lower()
            if cmd_name in SHELL_BINS:
                cmds.append({"type": "exec", "args": stripped})

    return cmds


def _run(cmd, timeout=30):
    global sudo_password
    use_sudo = False
    run_cmd = cmd

    if cmd.lstrip().startswith("sudo") and sudo_password:
        stripped = cmd.lstrip()
        run_cmd = "sudo -S" + stripped[4:] if not stripped.startswith("sudo -S") else stripped
        use_sudo = True

    try:
        if use_sudo:
            r = subprocess.run(run_cmd, shell=True, input=sudo_password + "\n",
                capture_output=True, text=True, timeout=timeout)
            if r.stderr:
                r.stderr = re.sub(r'$$sudo$$ password for .*?:\s*\n?', '', r.stderr)
        else:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "[Timeout 30s]"

    out = r.stdout
    if r.stderr.strip():
        out += ("\n" if out else "") + "[stderr] " + r.stderr
    if r.returncode != 0:
        out += "\n[exit: {}]".format(r.returncode)
    return (out or "[No output]").strip()[:10000]


def _is_binary(path):
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(8192)
    except:
        return False


def _quote_split(args, n):
    qparts = re.findall(r'(?:[^\s"]+|"[^"]*"|\'[^\']*\')+', args)
    if len(qparts) < n:
        return None
    return [p.strip('"\'') for p in qparts]


def execute_command(cmd):
    t, args = cmd["type"], cmd.get("args", "")

    # Alias routing
    if t in CMD_ALIAS:
        args = t + (" " + args if args else "")
        t = CMD_ALIAS[t]

    try:
        if t == "exec":
            if is_dangerous(args):
                return "[BLOCKED: {}]".format(args)
            return _run(args)
        if t == "open":
            s = platform.system()
            try:
                if s == "Windows":
                    os.startfile(args)
                    return "[Opened: {}]".format(args)
                elif s == "Darwin":
                    c = ["open", args]
                else:
                    c = ["xdg-open", args]
                r = subprocess.run(c, capture_output=True, text=True, timeout=10)
                if r.returncode != 0:
                    return "[Error: {}]".format(r.stderr.strip() or "code {}".format(r.returncode))
                return "[Opened: {}]".format(args)
            except FileNotFoundError:
                return "[Error: xdg-open not found]"
            except subprocess.TimeoutExpired:
                return "[Opened (background): {}]".format(args)
            except Exception as e:
                return "[Error: {}]".format(e)
        if t == "read":
            p = Path(args).expanduser().resolve()
            if not p.exists():
                return "[Not found: {}]".format(args)
            if p.is_dir():
                lines = ["{}  {}".format("[D]" if i.is_dir() else "[F]", i.name) for i in sorted(p.iterdir())[:200]]
                return "\n".join(lines) or "[Empty]"
            if _is_binary(p):
                return "[Binary: {}]".format(p)
            text = p.read_text("utf-8", errors="replace")
            ls = text.split("\n")
            return "\n".join(ls[:500]) + ("\n... [{} lines]".format(len(ls)) if len(ls) > 500 else "")
        if t == "write":
            p = Path(args).expanduser().resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            c = cmd.get("content", "")
            p.write_text(c, "utf-8")
            return "[Written {} chars to {}]".format(len(c), p)
        if t == "browse":
            import urllib.request
            req = urllib.request.Request(args, headers={"User-Agent": "Claw/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read().decode("utf-8", errors="replace")
            clean = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw, flags=re.DOTALL)
            clean = re.sub(r'<[^>]+>', ' ', clean)
            return re.sub(r'\s+', ' ', clean).strip()[:6000]
        if t == "download":
            import urllib.request
            from urllib.parse import urlparse as _urlparse
            parts = args.split()
            url = parts[0]
            dst = Path(parts[1]).expanduser().resolve() if len(parts) > 1 else Path(".") / (Path(_urlparse(url).path).name or "download")
            dst.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(url, str(dst))
            return "[Downloaded {} bytes to {}]".format(dst.stat().st_size, dst)
        if t == "copy":
            qp = _quote_split(args, 2)
            if not qp:
                return "[Usage: //copy <src> <dst>]"
            src, dst = Path(qp[0]).expanduser().resolve(), Path(qp[1]).expanduser().resolve()
            if not src.exists():
                return "[Not found: {}]".format(src)
            if src.is_dir():
                shutil.copytree(str(src), str(dst))
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
            return "[Copied to {}]".format(dst)
        if t == "move":
            qp = _quote_split(args, 2)
            if not qp:
                return "[Usage: //move <src> <dst>]"
            src, dst = Path(qp[0]).expanduser().resolve(), Path(qp[1]).expanduser().resolve()
            if not src.exists():
                return "[Not found: {}]".format(src)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return "[Moved to {}]".format(dst)
        if t == "delete":
            p = Path(args).expanduser().resolve()
            return "[BLOCKED: use //exec rm]" if p.exists() else "[Not found]"
        if t == "mkdir":
            Path(args).expanduser().resolve().mkdir(parents=True, exist_ok=True)
            return "[Created: {}]".format(args)
        if t == "tree":
            parts = args.split("--depth")
            dp = Path(parts[0].strip() or ".").expanduser().resolve()
            depth = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip() else 3
            if not dp.is_dir():
                return "[Not a dir]"
            lines = [str(dp)]
            def walk(d, prefix="", lvl=0):
                if lvl >= depth:
                    return
                try:
                    entries = sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
                except:
                    return
                for idx, e in enumerate(entries):
                    last = idx == len(entries) - 1
                    lines.append("{}--- {}{}".format(prefix, e.name, "/" if e.is_dir() else ""))
                    if e.is_dir():
                        walk(e, prefix + ("    " if last else "|   "), lvl + 1)
            walk(dp)
            return "\n".join(lines[:300])
        if t == "search":
            qp = re.findall(r'(?:[^\s"]+|"[^"]*"|\'[^\']*\')+', args)
            if len(qp) < 2:
                return "[Usage: //search <pat> <dir>]"
            sp = qp[0].strip('"\'')
            sd = Path(qp[-1].strip('"\'')).expanduser().resolve()
            results = []
            for p in sd.rglob("*{}*".format(sp)):
                results.append("[name] {}".format(p))
                if len(results) >= 50:
                    break
            for p in sd.rglob("*"):
                if not p.is_file() or p.stat().st_size > 1_000_000 or _is_binary(p):
                    continue
                try:
                    for ii, line in enumerate(p.read_text("utf-8", errors="replace").split("\n"), 1):
                        if re.search(re.escape(sp), line, re.I):
                            results.append("[grep] {}:{}: {}".format(p, ii, line.strip()[:120]))
                            if len(results) >= 50:
                                break
                except:
                    pass
                if len(results) >= 50:
                    break
            return "\n".join(results) or "[No matches]"
        if t == "info":
            lines = [
                "OS: {} {} ({})".format(platform.system(), platform.release(), platform.machine()),
                "Host: {}".format(platform.node()),
                "Python: {}".format(platform.python_version()),
                "CWD: {}".format(os.getcwd()),
                "PID: {}".format(os.getpid()),
            ]
            try:
                u = shutil.disk_usage(str(Path.home()))
                lines.append("Disk: {}G / {}G".format(u.used // (1024**3), u.total // (1024**3)))
            except:
                pass
            return "\n".join(lines)
        if t == "process":
            flt = args.split("--filter")[1].strip() if "--filter" in args else ""
            out = _run("tasklist /fo csv" if platform.system() == "Windows" else "ps aux", 10)
            if flt and platform.system() != "Windows":
                lines = out.split("\n")
                matched = [l for l in lines[1:] if flt.lower() in l.lower()]
                return ((lines[0] if lines else "") + "\n" + "\n".join(matched[:30])) if matched else "[No matches]"
            return "\n".join(out.split("\n")[:35])
        if t == "kill":
            if not args:
                return "[Usage: //kill <pid|name>]"
            if args.isdigit():
                os.kill(int(args), signal.SIGTERM)
                return "[SIGTERM {}]".format(args)
            _run("pkill -f {}".format(args) if platform.system() != "Windows" else "taskkill /IM {} /F".format(args))
            return "[Killed: {}]".format(args)
        if t == "env":
            if not args:
                return "\n".join("{}={}".format(k, v[:80]) for k, v in sorted(os.environ.items()))
            v = os.getenv(args)
            return "{}={}".format(args, v) if v else "[Not set]"
        if t == "time":
            now = datetime.datetime.now()
            return "Local: {}\nUTC: {}\nUnix: {:.0f}".format(
                now.strftime("%Y-%m-%d %H:%M:%S"),
                datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                time.time())
        if t == "ip":
            lines = ["[Local] " + _run("hostname -I 2>/dev/null || ifconfig | grep 'inet '")]
            try:
                import urllib.request
                lines.append("[Public] " + urllib.request.urlopen("https://api.ipify.org", 5).read().decode())
            except:
                lines.append("[Public] Failed")
            return "\n".join(lines)
        if t == "ping":
            parts = args.split("--count")
            host = parts[0].strip()
            cnt = parts[1].strip() if len(parts) > 1 else "4"
            flag = "-n" if platform.system() == "Windows" else "-c"
            return _run("ping {} {} {}".format(flag, cnt, host), 15)
        if t == "python":
            import io, contextlib, textwrap
            buf = io.StringIO()
            try:
                code = args
                cm = re.match(r'^-c\s+["\'](.*)["\']$', args, re.DOTALL)
                if cm:
                    code = cm.group(1)
                with contextlib.redirect_stdout(buf):
                    exec(textwrap.dedent(code), {
                        "__builtins__": __builtins__,
                        "os": os, "sys": sys, "Path": Path,
                        "json": json, "re": re, "time": time,
                    })
                return buf.getvalue().strip() or "[No output]"
            except Exception as e:
                return "[Error] {}: {}".format(type(e).__name__, e)
        if t == "git":
            return _run("git {}".format(args))
        return "[Unknown: {}]".format(t)
    except subprocess.TimeoutExpired:
        return "[Timeout 30s]"
    except Exception as e:
        return "[Error: {}: {}]".format(type(e).__name__, e)

# ━━━ Streaming API Client ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def stream_api(msgs, callback, api_key=None, api_base=None, model=None):
    import urllib.request
    key = api_key or config["api_key"]
    base = api_base or config["api_base"]
    mdl = model or config["model"]
    body = json.dumps({"model": mdl, "messages": msgs, "stream": True,
        "stream_options": {"include_usage": True}, "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS}).encode()
    url = "{}/chat/completions".format(base)
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "Authorization": "Bearer {}".format(key),
        "Accept": "text/event-stream", "Accept-Encoding": "identity"}, method="POST")
    resp = urllib.request.urlopen(req, timeout=120)
    full, buf = "", ""
    last_usage = {}
    for chunk in iter(lambda: resp.read(512), b""):
        buf += chunk.decode("utf-8", errors="replace")
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            line = line.strip()
            if not line.startswith("data:"): continue
            payload = line[5:].strip()
            if payload == "[DONE]": break
            try:
                obj = json.loads(payload)
                if "usage" in obj and obj["usage"]: last_usage = obj["usage"]
                tok = obj.get("choices", [{}])[0].get("delta", {}).get("content", "")
                if tok: full += tok; callback(tok)
            except: continue
    if last_usage:
        token_usage["prompt_tokens"] += last_usage.get("prompt_tokens", 0)
        token_usage["completion_tokens"] += last_usage.get("completion_tokens", 0)
        token_usage["total_tokens"] += last_usage.get("total_tokens", 0)
        token_usage["requests"] += 1
        token_usage["last_prompt"] = last_usage.get("prompt_tokens", 0)
        token_usage["last_completion"] = last_usage.get("completion_tokens", 0)
    return full


# ━━━ Web Gateway ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

gateway_server = None
gateway_port = None
gateway_start_time = 0
gateway_messages = []


class GatewayHandler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(body)

    def send_ndjson_header(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def send_event(self, data):
        self.wfile.write((json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8"))
        self.wfile.flush()

    def read_body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def send_file(self, filepath, content_type):
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f: content = f.read()
            body = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_json({"error": "Not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        base_dir = os.path.dirname(os.path.abspath(__file__))
        gw_log_verbose("GET", path)
        if path in ("/", ""): self.send_file(os.path.join(base_dir, "chat.html"), "text/html"); return
        if path == "/chat.css": self.send_file(os.path.join(base_dir, "chat.css"), "text/css"); return
        if path == "/chat.js": self.send_file(os.path.join(base_dir, "chat.js"), "application/javascript"); return
        if path == "/openclaw/health":
            self.send_json({
                "status": "ok",
                "name": "Claw",
                "version": __version__,
                "model": config["model"],
                "features": ["text", "commands", "multi-agent"]
            })
            return

        if path == "/openclaw/models":
            self.send_json({
                "models": [{"id": config["model"], "name": config["model"], "active": True}]
            })
            return
        if path == "/api/health":
            self.send_json({"status": "ok", "version": "0.7.4", "model": config["model"],
                "agents": list(agents.keys()), "groups": list(groups.keys()),
                "uptime": time.time() - gateway_start_time,
                "has_sudo": bool(sudo_password),
                "token_usage": {"total": token_usage["total_tokens"], "requests": token_usage["requests"]}})
            return
        if path == "/api/config":
            safe = {k: v for k, v in config.items() if k != "api_key"}
            safe["has_key"] = bool(config["api_key"])
            self.send_json(safe); return
        if path == "/api/skills":
            all_s = get_all_skills(); loaded = config.get("skills", [])
            self.send_json({"skills": [{"id": s, "name": all_s[s]["name"], "desc": all_s[s]["desc"],
                "loaded": s in loaded, "builtin": s in BUILTIN_SKILLS} for s in all_s], "loaded": loaded}); return
        if path == "/api/agents":
            result = []
            for name, a in agents.items():
                eff = get_agent_api_display(name)
                result.append({"name": name, "display_name": a["display_name"], "role": a.get("role", ""),
                    "color_idx": a.get("color_idx", 0),
                    "effective_api": {"model": eff["model"], "api_base": eff["api_base"], "model_source": eff["model_source"]}})
            self.send_json({"agents": result}); return
        if path == "/api/groups":
            self.send_json({"groups": [{"name": n, "desc": g.get("desc", ""), "members": g.get("members", []),
                "history_count": len(g.get("history", []))} for n, g in groups.items()]}); return
        if path == "/api/history":
            self.send_json({"messages": [{"role": m["role"], "content": m["content"]}
                for m in gateway_messages if m["role"] in ("user", "assistant") and not m["content"].startswith("[")]}); return
        if path == "/api/usage": self.send_json(token_usage); return
        
        if path == "/api":
            self.send_json({"name": "Claw Gateway", "version": "0.7.4",
                "endpoints": {"GET /": "Chat UI", "GET /api/health": "Health", "GET /api/config": "Config",
                    "GET /api/skills": "Skills", "GET /api/agents": "Agents", "GET /api/groups": "Groups",
                    "POST /api/chat": "Chat (stream)", "POST /api/chat/sync": "Chat (sync)",
                    "POST /api/agents": "Agent CRUD", "POST /api/groups": "Group CRUD",
                    "POST /api/exec": "Execute command"}}); return
        self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        gw_log_verbose("POST", path)
        if path == "/openclaw/chat":
            data = self.read_body()
            user_msg = data.get("message", "") or data.get("content", "") or data.get("text", "")
            user_msg = user_msg.strip()
            if not user_msg:
                self.send_json({"error": "Empty message"}, 400)
                return
            if not config.get("api_key"):
                self.send_json({"error": "No API key"}, 400)
                return

            gw_log_chat("OPENCLAW", user_msg[:60])

            # Support OpenClaw message format
            messages = data.get("messages", [])
            if messages and not user_msg:
                for m in reversed(messages):
                    if m.get("role") == "user":
                        user_msg = m.get("content", "")
                        break

            if not user_msg:
                self.send_json({"error": "No message content"}, 400)
                return

            gateway_messages.append({"role": "user", "content": user_msg})
            sys_msg = {"role": "system", "content": build_system()}
            api_msgs = [sys_msg] + gateway_messages[-MAX_HISTORY * 2:]

            t0 = time.time()
            reply = stream_api(api_msgs, lambda tok: None)
            elapsed = time.time() - t0

            if not reply:
                self.send_json({"error": "No response"}, 500)
                return

            gateway_messages.append({"role": "assistant", "content": reply})

            # Execute commands in reply
            cmds = parse_commands(reply)
            cmd_results = []
            if cmds:
                for c in cmds:
                    res = execute_command(c)
                    cmd_results.append({"type": c["type"], "args": c.get("args", ""), "result": res})
                gateway_messages.append({"role": "user",
                    "content": "[Command results]\n" + "\n".join(
                        "[{}:{}] -> {}".format(r["type"], r["args"], r["result"]) for r in cmd_results)})
                api_msgs2 = [sys_msg] + gateway_messages[-MAX_HISTORY * 2:]
                reply2 = stream_api(api_msgs2, lambda tok: None)
                if reply2:
                    reply = reply2
                    gateway_messages.append({"role": "assistant", "content": reply2})

            gw_log_chat("REPLY", "({:.1f}s)".format(elapsed))

            # OpenClaw compatible response
            response = {
                "reply": reply,
                "content": reply,
                "message": reply,
                "text": reply,
                "usage": {
                    "prompt": token_usage["last_prompt"],
                    "completion": token_usage["last_completion"]
                },
                "time": round(elapsed, 2)
            }
            if cmd_results:
                response["commands"] = cmd_results

            self.send_json(response)

            if len(gateway_messages) > MAX_HISTORY * 2:
                gateway_messages[:] = gateway_messages[-MAX_HISTORY * 2:]
            return
        if path == "/api/chat": self.handle_gateway_chat(True); return
        if path == "/api/chat/sync": self.handle_gateway_chat(False); return
        if path == "/api/clear": gateway_messages.clear(); self.send_json({"ok": True}); return
        if path == "/api/config":
            data = self.read_body()
            for k in ("api_key", "api_base", "model"):
                if k in data and data[k]: config[k] = data[k]
            save_config(); self.send_json({"ok": True}); return
        if path == "/api/skills":
            data = self.read_body()
            action, sid = data.get("action", ""), data.get("id", "")
            if action == "load":
                if sid not in get_all_skills(): self.send_json({"error": "Not found"}, 404); return
                if sid not in config["skills"]: config["skills"].append(sid); save_config()
                self.send_json({"ok": True, "loaded": config["skills"]})
            elif action == "unload":
                if sid in config["skills"]: config["skills"].remove(sid); save_config()
                self.send_json({"ok": True, "loaded": config["skills"]})
            elif action == "clear": config["skills"] = []; save_config(); self.send_json({"ok": True, "loaded": []})
            else: self.send_json({"error": "Unknown"}, 400)
            return
        if path == "/api/agents":
            data = self.read_body()
            action, name = data.get("action", ""), data.get("name", "").strip().lower()
            if action == "create":
                if not name or not re.match(r'^[a-zA-Z]\w*$', name): self.send_json({"error": "Invalid name"}, 400); return
                if name in agents: self.send_json({"error": "Exists"}, 400); return
                agents[name] = {"display_name": data.get("display_name", name.title()),
                    "role": data.get("role", "Helpful assistant."), "api_key": data.get("api_key") or None,
                    "api_base": data.get("api_base") or None, "model": data.get("model") or None,
                    "color_idx": next_color_idx(), "history": []}
                save_agents()
                gw_log_chat("AGENT", "Created: " + name)
                self.send_json({"ok": True, "agent": name})
            elif action == "update":
                if name not in agents: self.send_json({"error": "Not found"}, 404); return
                a = agents[name]
                for k in ("display_name", "role"):
                    if k in data: a[k] = data[k]
                for k in ("api_key", "api_base", "model"):
                    if k in data: a[k] = data[k] or None
                save_agents()
                gw_log_chat("AGENT", "Updated: " + name)
                self.send_json({"ok": True, "agent": name})
            elif action == "delete":
                if name not in agents: self.send_json({"error": "Not found"}, 404); return
                del agents[name]
                for g in groups.values():
                    if name in g.get("members", []): g["members"].remove(name)
                save_agents(); save_groups()
                gw_log_chat("AGENT", "Deleted: " + name)
                self.send_json({"ok": True})
            else: self.send_json({"error": "Unknown"}, 400)
            return
        if path == "/api/groups":
            data = self.read_body()
            action, name = data.get("action", ""), data.get("name", "").strip().lower()
            if action == "create":
                if not name or name in groups: self.send_json({"error": "Invalid"}, 400); return
                members = data.get("members", [])
                inv = [m for m in members if m not in agents]
                if inv: self.send_json({"error": "Unknown: " + ", ".join(inv)}, 400); return
                groups[name] = {"desc": data.get("description", ""), "members": members, "history": []}
                save_groups()
                gw_log_chat("GROUP", "Created: " + name + " [" + ", ".join(members) + "]")
                self.send_json({"ok": True, "group": name})
            elif action == "update":
                if name not in groups: self.send_json({"error": "Not found"}, 404); return
                g = groups[name]
                if "description" in data: g["desc"] = data["description"]
                if "members" in data:
                    inv = [m for m in data["members"] if m not in agents]
                    if inv: self.send_json({"error": "Unknown: " + ", ".join(inv)}, 400); return
                    g["members"] = data["members"]
                save_groups()
                self.send_json({"ok": True, "group": name})
            elif action == "delete":
                if name not in groups: self.send_json({"error": "Not found"}, 404); return
                del groups[name]; save_groups()
                gw_log_chat("GROUP", "Deleted: " + name)
                self.send_json({"ok": True})
            else: self.send_json({"error": "Unknown"}, 400)
            return
        if path == "/api/sudo":
            global sudo_password
            data = self.read_body()
            if data.get("clear"):
                sudo_password = ""
                gw_log_info("SUDO", "Password cleared")
                self.send_json({"ok": True, "has_password": False})
            elif data.get("password") is not None:
                sudo_password = data["password"]
                gw_log_info("SUDO", "Password set" if sudo_password else "Password cleared")
                self.send_json({"ok": True, "has_password": bool(sudo_password)})
            else:
                self.send_json({"has_password": bool(sudo_password)})
            return

        if path == "/api/exec":
            data = self.read_body()
            cmd_str = data.get("command", "").strip()
            if not cmd_str: self.send_json({"error": "Empty"}, 400); return
            gw_log_info("EXEC", cmd_str[:60])
            t0 = time.time()
            result = _run(cmd_str, 60)
            elapsed = time.time() - t0
            self.send_json({"command": cmd_str, "result": result, "time": round(elapsed, 3)})
            return
        self.send_json({"error": "Not found"}, 404)

    def handle_gateway_chat(self, streaming=True):
        data = self.read_body()
        user_msg = data.get("message", "").strip()
        mode = data.get("mode", "default")
        target = data.get("target", "")
        if not user_msg: self.send_json({"error": "Empty"}, 400); return
        if not config.get("api_key"): self.send_json({"error": "No API key"}, 400); return

        mode_label = mode + (":" + target if target else "")
        gw_log_chat("CHAT", "[{}] {}".format(mode_label, user_msg[:60]))

        if streaming: self.send_ndjson_header()
        try:
            if mode == "agent" and target and target in agents:
                self._gw_agent_chat(user_msg, target, streaming)
            elif mode == "group" and target and target in groups:
                self._gw_group_chat(user_msg, target, streaming)
            else:
                self._gw_default_chat(user_msg, streaming)
        except Exception as e:
            gw_log_error("ERR", str(e)[:80])
            if streaming: self.send_event({"type": "error", "content": str(e)}); self.send_event({"type": "done"})
            else: self.send_json({"error": str(e)}, 500)

    def _gw_send_usage(self, streaming, elapsed):
        u = {"prompt": token_usage["last_prompt"], "completion": token_usage["last_completion"],
             "total": token_usage["last_prompt"] + token_usage["last_completion"], "time": round(elapsed, 2)}
        if streaming: self.send_event({"type": "usage", "usage": u}); self.send_event({"type": "done"})
        return u

    def _gw_exec_and_continue(self, reply, history, api_msgs_builder, streaming, api_key=None, api_base=None, model=None):
        cmds = parse_commands(reply)
        if not cmds:
            return None
        if streaming:
            self.send_event({"type": "commands", "commands": [
                {"type": c["type"], "args": c.get("args", "")} for c in cmds]})
        results = []
        for i, c in enumerate(cmds):
            gw_log_info("CMD", "{} {}".format(c["type"], c.get("args", "")[:40]))
            res = execute_command(c)
            results.append(res)
            if streaming:
                self.send_event({"type": "result", "index": i, "content": res})
        history.append({"role": "user", "content": "[Command results]\n" + "\n".join(
            "[{}:{}] -> {}".format(cmds[j]["type"], cmds[j].get("args", ""), results[j])
            for j in range(len(cmds)))})
        api_msgs2 = api_msgs_builder()
        reply2 = stream_api(api_msgs2,
            lambda tok: self.send_event({"type": "token", "content": tok}) if streaming else None,
            api_key=api_key, api_base=api_base, model=model)
        if reply2:
            history.append({"role": "assistant", "content": reply2})
            return reply2
        return None


    def _gw_default_chat(self, user_msg, streaming):
        gateway_messages.append({"role": "user", "content": user_msg})
        sys_msg = {"role": "system", "content": build_system()}
        api_msgs = [sys_msg] + gateway_messages[-MAX_HISTORY * 2:]
        t0 = time.time()
        if streaming: self.send_event({"type": "agent_start", "agent": "", "display_name": "Claw", "color_idx": 0})
        reply = stream_api(api_msgs, lambda tok: self.send_event({"type": "token", "content": tok}) if streaming else None)
        elapsed = time.time() - t0
        if not reply:
            if streaming: self.send_event({"type": "error", "content": "No response"}); self.send_event({"type": "done"})
            return
        gateway_messages.append({"role": "assistant", "content": reply})
        self._gw_exec_and_continue(reply, gateway_messages, lambda: [sys_msg] + gateway_messages[-MAX_HISTORY * 2:], streaming)
        if streaming: self.send_event({"type": "agent_end", "agent": ""})
        u = self._gw_send_usage(streaming, elapsed)
        gw_log_chat("REPLY", "({:.1f}s, {} tok)".format(elapsed, u.get("total", 0)))
        if not streaming: self.send_json({"reply": reply, "time": round(elapsed, 2), "usage": u})
        if len(gateway_messages) > MAX_HISTORY * 2: gateway_messages[:] = gateway_messages[-MAX_HISTORY * 2:]

    def _gw_agent_chat(self, user_msg, agent_name, streaming):
        agent = agents[agent_name]
        history = agent.setdefault("history", [])
        history.append({"role": "user", "content": user_msg})
        a_key, a_base, a_model = get_agent_api(agent_name)
        sys_msg = {"role": "system", "content": build_agent_system(agent_name)}
        api_msgs = [sys_msg] + history[-MAX_HISTORY * 2:]
        t0 = time.time()
        if streaming: self.send_event({"type": "agent_start", "agent": agent_name,
            "display_name": agent["display_name"], "color_idx": agent.get("color_idx", 0)})
        reply = stream_api(api_msgs, lambda tok: self.send_event({"type": "token", "content": tok}) if streaming else None,
            api_key=a_key, api_base=a_base, model=a_model)
        elapsed = time.time() - t0
        if not reply:
            if streaming: self.send_event({"type": "agent_end", "agent": agent_name}); self.send_event({"type": "done"})
            return
        history.append({"role": "assistant", "content": reply})
        self._gw_exec_and_continue(reply, history, lambda: [sys_msg] + history[-MAX_HISTORY * 2:],
            streaming, api_key=a_key, api_base=a_base, model=a_model)
        if streaming: self.send_event({"type": "agent_end", "agent": agent_name})
        u = self._gw_send_usage(streaming, elapsed)
        gw_log_chat("@" + agent_name, "({:.1f}s)".format(elapsed))
        if not streaming: self.send_json({"reply": reply, "time": round(elapsed, 2), "usage": u})
        if len(history) > MAX_HISTORY * 2: agent["history"] = history[-MAX_HISTORY * 2:]
        save_agents()

    def _gw_group_chat(self, user_msg, group_name, streaming):
        group = groups[group_name]
        history = group.setdefault("history", [])
        mentions = extract_mentions(user_msg)
        members = set(group.get("members", []))
        if "all" in mentions: targets = list(group["members"])
        elif mentions:
            targets = [m for m in mentions if m in members]
            if not targets:
                err = "No valid @mention"
                if streaming: self.send_event({"type": "error", "content": err}); self.send_event({"type": "done"})
                else: self.send_json({"error": err}, 400)
                return
        else: targets = [group["members"][0]]
        history.append({"role": "user", "content": user_msg, "agent": "user"})
        responded = set()
        chain_depth = 0
        pending = list(targets)
        all_replies = []
        while pending and chain_depth < MAX_CHAIN_DEPTH:
            agent_name = pending.pop(0)
            if agent_name in responded or agent_name not in agents: continue
            responded.add(agent_name)
            agent = agents[agent_name]
            a_key, a_base, a_model = get_agent_api(agent_name)
            api_msgs = group_to_api_msgs(group_name, agent_name)
            if streaming: self.send_event({"type": "agent_start", "agent": agent_name,
                "display_name": agent["display_name"], "color_idx": agent.get("color_idx", 0)})
            t0 = time.time()
            reply = stream_api(api_msgs, lambda tok: self.send_event({"type": "token", "content": tok}) if streaming else None,
                api_key=a_key, api_base=a_base, model=a_model)
            elapsed = time.time() - t0
            if not reply:
                if streaming: self.send_event({"type": "agent_end", "agent": agent_name})
                continue
            history.append({"role": "assistant", "content": reply, "agent": agent_name})
            all_replies.append({"agent": agent_name, "reply": reply})
            gw_log_chat("@" + agent_name, "({:.1f}s)".format(elapsed))
            cmds = parse_commands(reply)
            if cmds:
                if streaming: self.send_event({"type": "commands", "commands": [{"type": c["type"], "args": c.get("args", "")} for c in cmds]})
                for i, c in enumerate(cmds):
                    res = execute_command(c)
                    if streaming: self.send_event({"type": "result", "index": i, "content": res})
                    history.append({"role": "user", "content": "[{}:{}] -> {}".format(c["type"], c.get("args", ""), res), "agent": "system"})
                api_msgs2 = group_to_api_msgs(group_name, agent_name)
                reply2 = stream_api(api_msgs2, lambda tok: self.send_event({"type": "token", "content": tok}) if streaming else None,
                    api_key=a_key, api_base=a_base, model=a_model)
                if reply2:
                    history.append({"role": "assistant", "content": reply2, "agent": agent_name})
                    for m in extract_mentions(reply2):
                        if m in members and m not in responded: pending.append(m)
            for m in extract_mentions(reply):
                if m in members and m not in responded:
                    pending.append(m)
                    gw_log_info("CHAIN", "@{} summoned by @{}".format(m, agent_name))
            if streaming: self.send_event({"type": "agent_end", "agent": agent_name})
            chain_depth += 1
        if len(history) > MAX_HISTORY * 3: group["history"] = history[-MAX_HISTORY * 3:]
        save_groups()
        u = self._gw_send_usage(streaming, 0)
        if not streaming:
            combined = "\n\n".join("[@{}]: {}".format(r["agent"], r["reply"]) for r in all_replies)
            self.send_json({"reply": combined, "usage": u,
                "agents": [{"name": r["agent"]} for r in all_replies]})


class ThreadedGateway(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def start_gateway(port=8765):
    global gateway_server, gateway_port, gateway_start_time
    if gateway_server: return
    try:
        gateway_server = ThreadedGateway(("0.0.0.0", port), GatewayHandler)
        gateway_port, gateway_start_time = port, time.time()
        threading.Thread(target=gateway_server.serve_forever, daemon=True).start()
    except OSError as e:
        gw_log_error("GW", "Failed: " + str(e))


def cmd_gateway(args):
    global gateway_server, gateway_port, gateway_start_time
    parts = args.split(None, 1) if args else []
    action = parts[0] if parts else "status"
    target = parts[1].strip() if len(parts) > 1 else ""
    if action == "start":
        if gateway_server: print("  {}Already running on port {}{}\n".format(C.YEL, gateway_port, C.R)); return
        port = int(target) if target and target.isdigit() else 8765
        start_gateway(port)
        if gateway_server: print("  {}Gateway started on port {}{}\n".format(C.GRN, port, C.R))
    elif action == "stop":
        if not gateway_server: print("  {}Not running{}\n".format(C.D, C.R)); return
        gateway_server.shutdown(); gateway_server = gateway_port = None
        print("  {}Stopped{}\n".format(C.D, C.R))
    elif action == "restart":
        port = int(target) if target and target.isdigit() else (gateway_port or 8765)
        if gateway_server: gateway_server.shutdown(); gateway_server = gateway_port = None
        start_gateway(port)
        print("  {}Restarted on port {}{}\n".format(C.GRN, port, C.R))
    else:
        s = "{}running port {}".format(C.GRN, gateway_port) if gateway_server else "{}stopped{}".format(C.RED, C.R)
        print("  {}Gateway:{}{}\n".format(C.D, C.R, s))


# ━━━ Chat Logic (terminal) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _exec_commands(reply, history, agent_name=""):
    cmds = parse_commands(reply)
    if not cmds: return False
    for c in cmds:
        print("\n  {}[{}] {}{}".format(C.YEL, c["type"], c.get("args", ""), C.R))
        result = execute_command(c)
        for line in result.split("\n")[:30]:
            print("  {}| {}{}".format(C.D, C.GRN, line, C.R))
        print("  {}{}{}".format(C.D, "-" * 40, C.R))
        entry = {"role": "user", "content": "[{}:{}] -> {}".format(c["type"], c.get("args", ""), result)}
        if agent_name: entry["agent"] = "system"
        history.append(entry)
    return True


def chat(user_input):
    global messages
    messages.append({"role": "user", "content": user_input})
    loaded = config.get("skills", [])
    tag = "{}claw{}>".format(C.CYN, C.R)
    if loaded: tag = "{}claw{} {}[{}]{}>".format(C.CYN, C.R, C.MAG, ",".join(loaded), C.R)
    if not config.get("api_key"):
        reply = "No API Key. Use /key <key>"
        print("\n{} {}\n".format(tag, reply))
        messages.append({"role": "assistant", "content": reply}); return
    sys_msg = {"role": "system", "content": build_system()}
    api_msgs = [sys_msg] + messages[-MAX_HISTORY * 2:]
    print("\n{} ".format(tag), end="", flush=True)
    t0 = time.time()
    reply = stream_api(api_msgs, lambda tok: sys.stdout.write(tok) or sys.stdout.flush())
    elapsed = time.time() - t0
    if not reply: print("{}(no response){}".format(C.RED, C.R)); return
    print("  {}({:.1f}s){}".format(C.D, elapsed, C.R))
    _print_tokens()
    messages.append({"role": "assistant", "content": reply})
    if _exec_commands(reply, messages):
        api_msgs2 = [sys_msg] + messages[-MAX_HISTORY * 2:]
        print("\n{} ".format(tag), end="", flush=True)
        reply2 = stream_api(api_msgs2, lambda tok: sys.stdout.write(tok) or sys.stdout.flush())
        if reply2: print(); _print_tokens(); messages.append({"role": "assistant", "content": reply2})
    if len(messages) > MAX_HISTORY * 2: messages[:] = messages[-MAX_HISTORY * 2:]


def chat_agent(user_input):
    agent_name = current_target
    agent = agents[agent_name]
    color = get_agent_color(agent_name)
    display = agent["display_name"]
    history = agent.setdefault("history", [])
    history.append({"role": "user", "content": user_input})
    a_key, a_base, a_model = get_agent_api(agent_name)
    sys_msg = {"role": "system", "content": build_agent_system(agent_name)}
    api_msgs = [sys_msg] + history[-MAX_HISTORY * 2:]
    print("\n{}{}{}> ".format(color, display, C.R), end="", flush=True)
    t0 = time.time()
    reply = stream_api(api_msgs, lambda tok: sys.stdout.write(tok) or sys.stdout.flush(), api_key=a_key, api_base=a_base, model=a_model)
    elapsed = time.time() - t0
    if not reply: print("{}(no response){}".format(C.RED, C.R)); return
    print("  {}({:.1f}s){}".format(C.D, elapsed, C.R))
    _print_tokens()
    history.append({"role": "assistant", "content": reply})
    if _exec_commands(reply, history):
        api_msgs2 = [sys_msg] + history[-MAX_HISTORY * 2:]
        print("\n{}{}{}> ".format(color, display, C.R), end="", flush=True)
        reply2 = stream_api(api_msgs2, lambda tok: sys.stdout.write(tok) or sys.stdout.flush(), api_key=a_key, api_base=a_base, model=a_model)
        if reply2: print(); _print_tokens(); history.append({"role": "assistant", "content": reply2})
    if len(history) > MAX_HISTORY * 2: agent["history"] = history[-MAX_HISTORY * 2:]
    save_agents()


def chat_group(user_input):
    group_name = current_target
    group = groups[group_name]
    history = group.setdefault("history", [])
    mentions = extract_mentions(user_input)
    members = set(group.get("members", []))
    if "all" in mentions: targets = list(group["members"])
    elif mentions:
        targets = [m for m in mentions if m in members]
        if not targets: print("  {}No valid @mention{}\n".format(C.RED, C.R)); return
    else: targets = [group["members"][0]]
    history.append({"role": "user", "content": user_input, "agent": "user"})
    responded, chain_depth, pending = set(), 0, list(targets)
    while pending and chain_depth < MAX_CHAIN_DEPTH:
        agent_name = pending.pop(0)
        if agent_name in responded or agent_name not in agents: continue
        responded.add(agent_name)
        agent = agents[agent_name]
        color = get_agent_color(agent_name)
        a_key, a_base, a_model = get_agent_api(agent_name)
        api_msgs = group_to_api_msgs(group_name, agent_name)
        print("\n{}{}{}> ".format(color, agent["display_name"], C.R), end="", flush=True)
        t0 = time.time()
        reply = stream_api(api_msgs, lambda tok: sys.stdout.write(tok) or sys.stdout.flush(), api_key=a_key, api_base=a_base, model=a_model)
        elapsed = time.time() - t0
        if not reply: print("{}(no response){}".format(C.RED, C.R)); continue
        print("  {}({:.1f}s){}".format(C.D, elapsed, C.R))
        _print_tokens()
        history.append({"role": "assistant", "content": reply, "agent": agent_name})
        cmds = parse_commands(reply)
        if cmds:
            for c in cmds:
                print("\n  {}[{}] {}{}".format(C.YEL, c["type"], c.get("args", ""), C.R))
                result = execute_command(c)
                for line in result.split("\n")[:30]: print("  {}| {}{}".format(C.D, C.GRN, line, C.R))
                print("  {}{}{}".format(C.D, "-" * 40, C.R))
                history.append({"role": "user", "content": "[{}:{}] -> {}".format(c["type"], c.get("args", ""), result), "agent": "system"})
            api_msgs2 = group_to_api_msgs(group_name, agent_name)
            print("\n{}{}{}> ".format(color, agent["display_name"], C.R), end="", flush=True)
            reply2 = stream_api(api_msgs2, lambda tok: sys.stdout.write(tok) or sys.stdout.flush(), api_key=a_key, api_base=a_base, model=a_model)
            if reply2: print(); _print_tokens(); history.append({"role": "assistant", "content": reply2, "agent": agent_name})
            for m in extract_mentions(reply2 if reply2 else ""):
                if m in members and m not in responded: pending.append(m)
        for m in extract_mentions(reply):
            if m in members and m not in responded: pending.append(m)
        chain_depth += 1
    if len(history) > MAX_HISTORY * 3: group["history"] = history[-MAX_HISTORY * 3:]
    save_groups()


# ━━━ Status Display ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def print_status():
    """Print compact status dashboard."""
    key = _mask_key(config.get("api_key", ""))
    gw = "http://localhost:{}".format(gateway_port) if gateway_server else "stopped"
    loaded = config.get("skills", [])
    mode_str = current_mode
    if current_target:
        mode_str += " \u2192 " + current_target

    sep = C.DIM + "\u2500" * 40 + C.R
    paw = "\U0001F43E"

    print()
    print("  " + sep)
    print("  {}{}{} Claw v0.7.4".format(C.B, C.CYN, C.R))
    print("  " + sep)
    print()
    print("  {}Model:{}    {}".format(C.DIM, C.R, config["model"]))
    print("  {}API:{}      {}".format(C.DIM, C.R, config["api_base"]))
    print("  {}Key:{}      {}{}{}".format(C.DIM, C.R, C.GRN if config.get("api_key") else C.RED, key, C.R))
    print("  {}Skills:{}   {}".format(C.DIM, C.R, ", ".join(loaded) if loaded else "none"))

    if agents:
        print()
        print("  {}Agents:{}   {}".format(C.DIM, C.R, len(agents)))
        for name, a in agents.items():
            color = get_agent_color(name)
            _, base, model = get_agent_api(name)
            bs = base.split("//")[-1].split("/")[0][:20]
            print("    {}@{}{} {:<12} {} @ {}{}{}".format(color, name, C.R, a["display_name"], model, C.DIM, bs, C.R))

    if groups:
        print()
        print("  {}Groups:{}   {}".format(C.DIM, C.R, len(groups)))
        for gn, g in groups.items():
            ms = ", ".join("@{}".format(m) for m in g.get("members", []))
            print("    {}{}{} [{}]".format(C.B, gn, C.R, ms))

    print()
    print("  {}Gateway:{}  {}{}{}".format(C.DIM, C.R, C.GRN if gateway_server else C.RED, gw, C.R))
    print("  {}Mode:{}     {}".format(C.DIM, C.R, mode_str))
    print()
    print("  " + sep)
    print("  {}Open {}{}{} for Web UI".format(C.DIM, C.CYN, gw, C.DIM + C.R))
    print("  {}/help  /status  /log{}  {}Ctrl+C to exit{}".format(C.DIM, C.R, C.DIM, C.R))
    print()


def cmd_help():
    loaded = config.get("skills", [])
    B, R, D = C.B, C.R, C.D
    L = []
    a = L.append
    a("")
    a("  {}{}\U0001F43E Claw v0.7.4 — Commands{}".format(C.CYN, B, R))
    a("")
    a("  {}<text>{}                 Chat with current mode".format(B, R))
    a("  {}/key <key>{}             Set API Key".format(B, R))
    a("  {}/base <url>{}            Set API Base".format(B, R))
    a("  {}/model <name>{}          Set Model".format(B, R))
    a("  {}/config{}                Show config".format(B, R))
    a("  {}/status{}                Refresh status dashboard".format(B, R))
    a("  {}/usage{}                 Token usage".format(B, R))
    a("  {}/clear{}                 Clear history".format(B, R))
    a("  {}/history{}               Show messages".format(B, R))
    a("")
    a("  {}/skill list|load|unload|clear{}".format(B, R))
    a("  {}  Loaded:{} {}".format(D, R, ", ".join(loaded) if loaded else "none"))
    a("")
    a("  {}/agent list{}              List agents".format(B, R))
    a("  {}/agent create <name>{}    Create agent".format(B, R))
    a("  {}/agent switch <name>{}    Chat 1-on-1".format(B, R))
    a("  {}/agent back{}             Back to default".format(B, R))
    a("  {}/agent api <name>{}       View/set API".format(B, R))
    a("  {}/agent delete|info|prompt|model{}".format(B, R))
    a("")
    a("  {}/group list{}              List groups".format(B, R))
    a("  {}/group create <name>{}    Create group".format(B, R))
    a("  {}/group enter <name>{}     Enter group chat".format(B, R))
    a("  {}/group leave{}            Leave group".format(B, R))
    a("  {}/group add|remove|delete|info{}".format(B, R))
    a("")
    a("  {}/gateway start|stop|restart{}   Gateway control".format(B, R))
    a("  {}/log [0|1|2]{}             Log level (0=off 1=normal 2=verbose)".format(B, R))
    a("  {}/workspace{}               Edit workspace".format(B, R))
    a("  {}/sudo <password>{}        Set sudo password (memory only)".format(B, R))
    a("  {}/sudo clear{}             Clear sudo password".format(B, R))
    a("")
    a("  {}Group: @name \u2192 target, @all \u2192 all, plain \u2192 first member{}".format(D, R))
    a("  {}Web UI handles agent/group creation via GUI{}".format(D, R))
    a("")
    print("\n".join(L))



# ━━━ Main ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def main():
    global current_mode, current_target, log_level

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    load_agents()
    load_groups()

    try:
        if HISTORY_FILE.exists(): readline.read_history_file(str(HISTORY_FILE))
        readline.set_history_length(500)
    except: pass

    # Auto-start gateway
    start_gateway(8765)

    # Print status dashboard
    print_status()

    if not config["api_key"]:
        print("  {}! No API Key. /key <key> to set.{}\n".format(C.YEL, C.R))

    while True:
        try:
            user = input(get_prompt()).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  {}Bye.{}".format(C.D, C.R))
            break
        if not user: continue

        if user == "/help": cmd_help(); continue
        if user == "/config":
            print("\n  {}Model:{}  {}".format(C.YEL, C.R, config["model"]))
            print("  {}API:{}    {}".format(C.YEL, C.R, config["api_base"]))
            print("  {}Key:{}    {}".format(C.YEL, C.R, _mask_key(config.get("api_key", ""))))
            gw = "port {}".format(gateway_port) if gateway_server else "stopped"
            print("  {}GW:{}     {}".format(C.YEL, C.R, gw))
            mode_s = current_mode + (" \u2192 " + current_target if current_target else "")
            print("  {}Mode:{}   {}".format(C.YEL, C.R, mode_s))
            print("  {}Skills:{} {}".format(C.YEL, C.R, ", ".join(config.get("skills", [])) or "none"))
            print()
            continue
        if user == "/status": print_status(); continue
        if user == "/usage":
            u = token_usage
            print("\n  {}Token Usage{}".format(C.CYN, C.R))
            print("  {}Last: {}p {}c {}t{}".format(C.D, u["last_prompt"], u["last_completion"],
                u["last_prompt"] + u["last_completion"], C.R))
            print("  {}Total: {}p {}c {}t ({} req){}".format(C.D,
                u["prompt_tokens"], u["completion_tokens"], u["total_tokens"], u["requests"], C.R))
            print()
            continue
        if user == "/clear":
            if current_mode == "agent" and current_target: agents[current_target]["history"] = []; save_agents()
            elif current_mode == "group" and current_target: groups[current_target]["history"] = []; save_groups()
            else: messages.clear()
            print("  {}Cleared{}\n".format(C.D, C.R)); continue
        if user == "/history":
            hist = messages
            if current_mode == "agent" and current_target: hist = agents[current_target].get("history", [])
            elif current_mode == "group" and current_target: hist = groups[current_target].get("history", [])
            if not hist: print("  {}(empty){}\n".format(C.D, C.R))
            else:
                for m in hist[-20:]:
                    s = m.get("agent", m["role"])
                    c = C.BLU if s == "user" else get_agent_color(s) if s in agents else C.CYN
                    print("  {}{}{}> {}{}{}".format(c, s, C.R, C.D, m["content"][:80].replace("\n", " "), C.R))
            print()
            continue
        if user.startswith("/key "): config["api_key"] = user[5:].strip(); save_config(); print("  {}Saved{}\n".format(C.GRN, C.R)); continue
        if user.startswith("/base "): config["api_base"] = user[6:].strip(); save_config(); print("  {}Saved{}\n".format(C.GRN, C.R)); continue
        if user.startswith("/model "): config["model"] = user[7:].strip(); save_config(); print("  {}Saved{}\n".format(C.GRN, C.R)); continue
        if user.startswith("/log"):
            parts = user.split()
            if len(parts) > 1 and parts[1].isdigit():
                log_level = int(parts[1])
                print("  {}Log level: {}{}\n".format(C.D, log_level, C.R))
            else:
                print("  {}Log level: {} (0=off 1=normal 2=verbose){}\n".format(C.D, log_level, C.R))
            continue
        if user.startswith("/skill"): cmd_skill(user[6:].strip()); continue
        if user.startswith("/agent"): cmd_agent(user[6:].strip()); continue
        if user.startswith("/group"): cmd_group(user[6:].strip()); continue
        if user.startswith("/sudo"):
            pw = user[5:].strip()
            if not pw:
                print("  {}Sudo password:{} {}\n".format(
                    C.D, C.R, "{}set{}".format(C.GRN, C.R) if sudo_password else "{}not set{}".format(C.RED, C.R)))
            elif pw == "clear":
                sudo_password = ""
                print("  {}Cleared{}\n".format(C.D, C.R))
            else:
                sudo_password = pw
                print("  {}Set{}\n".format(C.GRN, C.R))
            continue

        if user.startswith("/gateway"): cmd_gateway(user[8:].strip()); continue
        if user == "/workspace":
            WORKSPACE_FILE.parent.mkdir(parents=True, exist_ok=True)
            if WORKSPACE_FILE.exists():
                print("\n  {}Current:{}\n".format(C.D, C.R))
                for line in WORKSPACE_FILE.read_text("utf-8").split("\n")[:20]: print("    {}".format(line))
                print()
            if input("  {}Edit? (y/N): {}".format(C.YEL, C.R)).strip().lower() == "y":
                lines = []
                while True:
                    try: line = input("    ")
                    except EOFError: break
                    if line == "": break
                    lines.append(line)
                WORKSPACE_FILE.write_text("\n".join(lines) + "\n", "utf-8")
                print("  {}Saved{}\n".format(C.GRN, C.R))
            continue
        if user.lower() in ("exit", "quit", "q"):
            if gateway_server: gateway_server.shutdown()
            print("  {}Bye.{}".format(C.D, C.R)); break

        # Route chat
        if current_mode == "agent" and current_target: chat_agent(user)
        elif current_mode == "group" and current_target: chat_group(user)
        else: chat(user)

        try: readline.write_history_file(str(HISTORY_FILE))
        except: pass
        print()


if __name__ == "__main__":
    main()