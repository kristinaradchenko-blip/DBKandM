# Ставит расписание рассылок на этом Mac через launchd (время системы = московское, как в Пензе).
#   python3 install_schedule.py            установить и включить
#   python3 install_schedule.py --remove   выключить и удалить
import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
AGENTS = os.path.expanduser("~/Library/LaunchAgents")
LOGS = os.path.join(HERE, "logs")
UID = os.getuid()

# (название, часы, минуты, аргументы run_bot.sh)
JOBS = [("cafe-morning", [(8, 0)], ["--send-morning"]),
        ("cafe-day", [(11, 30), (15, 0)], ["--send-now"]),
        ("cafe-itogi", [(22, 15)], ["--send", "--today"]),
        ("truck-morning", [(8, 1)], ["--send-truck-morning"]),
        ("truck-day", [(11, 31), (15, 1)], ["--send-truck-now"]),
        ("truck-itogi", [(22, 16)], ["--send-truck", "--today"])]

PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>%(label)s</string>
<key>ProgramArguments</key><array><string>/bin/bash</string><string>%(run)s</string>%(args)s</array>
<key>StartCalendarInterval</key><array>%(times)s</array>
<key>StandardOutPath</key><string>%(log)s</string>
<key>StandardErrorPath</key><string>%(log)s</string>
</dict></plist>
"""


def label(name):
    return "com.gussi.iiko." + name


def main():
    remove = "--remove" in sys.argv
    os.makedirs(AGENTS, exist_ok=True)
    os.makedirs(LOGS, exist_ok=True)
    for name, times, args in JOBS:
        path = os.path.join(AGENTS, label(name) + ".plist")
        subprocess.run(["launchctl", "bootout", "gui/%d" % UID, path], capture_output=True)
        if remove:
            if os.path.exists(path):
                os.remove(path)
            continue
        text = PLIST % {"label": label(name), "run": os.path.join(HERE, "run_bot.sh"), "log": os.path.join(LOGS, name + ".log"),
                        "args": "".join("<string>%s</string>" % a for a in args),
                        "times": "".join("<dict><key>Hour</key><integer>%d</integer><key>Minute</key><integer>%d</integer></dict>" % t for t in times)}
        with open(path, "w") as f:
            f.write(text)
        subprocess.run(["launchctl", "bootstrap", "gui/%d" % UID, path], check=True)
    print("расписание удалено" if remove else "расписание включено: %d заданий" % len(JOBS))


if __name__ == "__main__":
    main()
