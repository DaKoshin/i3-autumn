#!/usr/bin/env bash
# Autumn desktop installer for Debian 12. Run as the desktop user, not as root.
# This is the single user-facing entry point: dependencies, compositor, configs.
set -Eeuo pipefail

autumn_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
autumn_mode=install
autumn_motion=1
autumn_restore=
autumn_stage='перевірка параметрів'
autumn_revision=d87a5ba3af7a9ee3c4e040ee29b2dea7e9e46317
autumn_target="$HOME/.local/bin/picom-autumn"

usage() {
    cat <<'HELP'
Autumn — установник i3 + Polybar + Rofi + Picom 13 для Debian 12

  ./install.sh                  Установити все потрібне й конфігурації
  ./install.sh --check          Перевірити комплект без змін і sudo
  ./install.sh --no-animations  Установити робочий стіл без збирання Picom
  ./install.sh --restore PATH   Відновити конфігурації з резервної копії
  ./install.sh --help           Показати цю довідку

Запускайте від звичайного користувача. sudo потрібен лише для apt.
Скрипт не завершує сесію, не перезапускає GNOME і не міняє display manager.
HELP
}

while (($#)); do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --check)
            [[ "$autumn_mode" == install ]] || { printf 'Виберіть лише один режим дії.\n' >&2; exit 2; }
            autumn_mode=check
            ;;
        --no-animations) autumn_motion=0 ;;
        --restore)
            [[ $# -ge 2 ]] || { printf 'Потрібен шлях резервної копії.\n' >&2; exit 2; }
            [[ "$autumn_mode" == install ]] || { printf 'Виберіть лише один режим дії.\n' >&2; exit 2; }
            autumn_mode=restore
            autumn_restore=$2
            shift
            ;;
        *) printf 'Невідомий параметр: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

if [[ $EUID -eq 0 ]]; then
    printf 'Запустіть цей скрипт від свого користувача, без sudo перед ./install.sh.\n' >&2
    exit 1
fi

trap 'printf "\nПомилка на етапі: %s. Установлення не завершене.\n" "$autumn_stage" >&2' ERR

autumn_runtime_packages=(
    i3-wm polybar rofi python3 gnome-terminal pavucontrol pulseaudio-utils
    x11-xkb-utils x11-xserver-utils xss-lock i3lock xwallpaper dunst
    libnotify-bin network-manager-gnome policykit-1-gnome flameshot
    sensible-utils xdg-utils fonts-firacode fonts-dejavu-core adwaita-icon-theme
)
autumn_build_packages=(
    build-essential ca-certificates git cmake meson ninja-build pkg-config
    libx11-dev libx11-xcb-dev libxcb1-dev libxcb-composite0-dev
    libxcb-damage0-dev libxcb-glx0-dev libxcb-image0-dev libxcb-present-dev
    libxcb-randr0-dev libxcb-render0-dev libxcb-render-util0-dev
    libxcb-shape0-dev libxcb-sync-dev libxcb-util-dev libxcb-xfixes0-dev
    libpixman-1-dev libev-dev libepoxy-dev libegl-dev libgl-dev libpcre2-dev uthash-dev
)

package_installed() {
    local autumn_status
    autumn_status=$(dpkg-query -W -f='${db:Status-Status}' "$1" 2>/dev/null) || return 1
    [[ "$autumn_status" == installed ]]
}

find_picom() {
    local autumn_candidate autumn_version
    for autumn_candidate in "$autumn_target" "$(command -v picom || true)"; do
        [[ -n "$autumn_candidate" && -x "$autumn_candidate" ]] || continue
        autumn_version=$("$autumn_candidate" --version 2>/dev/null) || continue
        if [[ "$autumn_version" =~ ^(picom[[:space:]]+)?v?([0-9]+)([.[:space:]-]|$) ]] &&
           ((10#${BASH_REMATCH[2]} >= 13)); then
            printf '%s\n' "$autumn_candidate"
            return 0
        fi
    done
    return 1
}

# Recovery needs only the helper and backup, even if project configs are missing.
if [[ "$autumn_mode" == restore ]]; then
    [[ -f "$autumn_root/scripts/install_config.py" && ! -L "$autumn_root/scripts/install_config.py" ]] || {
        printf 'Відсутній або некоректний модуль відновлення.\n' >&2; exit 1
    }
    autumn_stage='відновлення конфігурацій'
    exec python3 "$autumn_root/scripts/install_config.py" --restore "$autumn_restore"
fi

# Validate project contents before asking apt to change anything.
for autumn_file in scripts/install_config.py config/i3/config config/i3/autumn/desktop.py \
    config/i3/autumn/audio.py config/i3/autumn/wallpaper.png config/i3/autumn/dunstrc \
    config/i3/autumn/picom.conf config/polybar/autumn.ini config/rofi/autumn.rasi; do
    [[ -f "$autumn_root/$autumn_file" && ! -L "$autumn_root/$autumn_file" ]] || {
        printf 'Відсутній або некоректний файл комплекту: %s\n' "$autumn_file" >&2
        exit 1
    }
done

if [[ "$autumn_mode" == check ]]; then
    printf 'Проєкт: %s\n' "$autumn_root"
    printf 'Відсутні пакети робочого столу:\n'
    autumn_missing=0
    for autumn_package in "${autumn_runtime_packages[@]}"; do
        if ! package_installed "$autumn_package"; then
            printf '  %s\n' "$autumn_package"
            autumn_missing=$((autumn_missing+1))
        fi
    done
    if ((autumn_missing == 0)); then printf '  немає\n'; fi
    if autumn_picom=$(find_picom); then
        printf 'Композитор: %s\n' "$autumn_picom"
    else
        printf 'Picom 13 відсутній; звичайне встановлення збере його з офіційного релізу.\n'
    fi
    python3 "$autumn_root/scripts/install_config.py" --check
    printf 'Перевірку завершено. Файли й пакети не змінено.\n'
    exit 0
fi

# This bundle targets the checked Debian release; do not upgrade the OS.
if [[ ! -r /etc/os-release ]]; then
    printf 'Неможливо визначити дистрибутив.\n' >&2; exit 1
fi
source /etc/os-release
if [[ "${ID:-}" != debian || "${VERSION_ID:-}" != 12 ]]; then
    printf 'Цей установник підготовлено для Debian 12; поточна система: %s %s.\n' "${ID:-?}" "${VERSION_ID:-?}" >&2
    exit 1
fi
if command -v python3 >/dev/null; then
    python3 "$autumn_root/scripts/install_config.py" --check >/dev/null
fi

autumn_need_build=0
autumn_packages=("${autumn_runtime_packages[@]}")
if ((autumn_motion)) && ! find_picom >/dev/null; then
    autumn_need_build=1
    autumn_packages+=("${autumn_build_packages[@]}")
fi
# Preserve an existing audio server; bootstrap PipeWire only if neither exists.
if ! package_installed pipewire-pulse && ! package_installed pulseaudio; then
    autumn_packages+=(pipewire pipewire-pulse wireplumber)
fi
autumn_missing_packages=()
for autumn_package in "${autumn_packages[@]}"; do
    if ! package_installed "$autumn_package"; then
        autumn_missing_packages+=("$autumn_package")
    fi
done

if ((${#autumn_missing_packages[@]})); then
    autumn_stage='встановлення залежностей Debian'
    command -v sudo >/dev/null || { printf 'Для встановлення пакетів потрібен sudo.\n' >&2; exit 1; }
    printf 'Потрібні пакети: %s\n' "${autumn_missing_packages[*]}"
    sudo apt-get update
    sudo apt-get install --yes --no-install-recommends --no-remove "${autumn_missing_packages[@]}"
fi

if ((autumn_need_build)); then
    autumn_stage='збирання офіційного Picom 13'
    autumn_build=$(mktemp -d "${TMPDIR:-/tmp}/autumn-picom.XXXXXXXX")
    printf 'Каталог збирання, залишений для діагностики: %s\n' "$autumn_build"
    export GIT_TERMINAL_PROMPT=0 GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null
    git -c credential.helper= -c core.hooksPath=/dev/null clone \
        --depth 1 --branch v13 --single-branch \
        https://github.com/yshui/picom.git "$autumn_build/source"
    autumn_found=$(git -C "$autumn_build/source" rev-parse HEAD)
    if [[ "$autumn_found" != "$autumn_revision" ]]; then
        printf 'Ревізія Picom не збігається з перевіреним релізом; збирання зупинено.\n' >&2
        exit 1
    fi
    git -C "$autumn_build/source" -c credential.helper= -c core.hooksPath=/dev/null \
        submodule update --init --recursive
    # Bookworm has libconfig 1.5; upstream's pinned wrap builds a private >=1.7.
    # CMake is needed for that dependency. No system library is replaced.
    meson setup "$autumn_build/build" "$autumn_build/source" \
        --buildtype=release -Ddbus=false -Dwith_docs=false -Dcompton=false
    ninja -C "$autumn_build/build" -j 4
    "$autumn_build/build/src/picom" --version

    autumn_stage='встановлення локального композитора'
    mkdir -p -- "$HOME/.local/bin"
    if [[ -e "$autumn_target" || -L "$autumn_target" ]]; then
        [[ -f "$autumn_target" && ! -L "$autumn_target" ]] || {
            printf 'Відмова замінити символьне посилання або не звичайний файл Picom.\n' >&2
            exit 1
        }
        autumn_backup="$HOME/.local/state/i3-autumn/binary-backups/$(date +%Y%m%d-%H%M%S)-$$"
        mkdir -p -m 700 -- "$autumn_backup"
        cp -p -- "$autumn_target" "$autumn_backup/picom-autumn"
    fi
    # Copy only the executable; upstream meson install also adds global autostart.
    autumn_temp_binary=$(mktemp "$HOME/.local/bin/.picom-autumn.XXXXXXXX")
    install -m 755 -- "$autumn_build/build/src/picom" "$autumn_temp_binary"
    mv -f -- "$autumn_temp_binary" "$autumn_target"
fi

autumn_stage='встановлення конфігурацій із резервним копіюванням'
python3 "$autumn_root/scripts/install_config.py"
printf '\nГотово. Збережіть роботу та ввійдіть у сесію i3 через екран входу.\n'
printf 'Win+C — центр керування, Win+F1 — клавіші, Ctrl+Пробіл — EN/RU/UA.\n'
if ((autumn_motion)); then
    printf 'Анімації: Win+C → Анімації. Новий вхід завантажить оновлений supervisor.\n'
else
    printf 'Збирання Picom пропущено. Наявний сучасний композитор може запускатися; вимкнення — у меню анімацій.\n'
fi
printf 'Поточну сесію не перезапущено. Для відновлення: ./install.sh --restore ШЛЯХ_КОПІЇ\n'
