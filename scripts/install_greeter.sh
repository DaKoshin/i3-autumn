#!/usr/bin/env bash
# Autumn LightDM greeter. Without --apply this only checks and prints the plan.
# --apply uses sudo and changes system files; it never touches GDM's files and
# never switches the default display manager (see the printed final steps).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
apply=0
[[ "${1:-}" == "--apply" ]] && apply=1

lib=/usr/local/lib/autumn-greeter
xgreeters=/usr/share/xgreeters/autumn-greeter.desktop
conf=/etc/lightdm/lightdm.conf.d/50-autumn.conf
share=/usr/share/autumn-greeter
stamp="$(date +%Y%m%d-%H%M%S)"

missing=0
for file in greeter/autumn_greeter.py greeter/autumn-greeter.desktop greeter/50-autumn.conf \
    config/i3/autumn/wallpaper.png; do
  [[ -f "$root/$file" ]] || { echo "Немає файлу: $file" >&2; missing=1; }
done
for package in lightdm gir1.2-lightdm-1 python3-gi gir1.2-gtk-3.0; do
  dpkg -s "$package" >/dev/null 2>&1 || { echo "Не встановлено пакет: $package" >&2; missing=1; }
done
bash -n "$0"
python3 -I -m py_compile "$root/greeter/autumn_greeter.py"
if ((missing)) || ((!apply)); then
  echo "План: $lib, $xgreeters, $conf, $share/wallpaper.png"
  ((missing)) && echo "Спершу встановіть відсутнє (apt install lightdm gir1.2-lightdm-1)." >&2
  exit $missing
fi

[[ -e "$conf" ]] && sudo cp -p "$conf" "$conf.$stamp.bak"
sudo install -d -m 755 "$lib" "$share" "$(dirname "$conf")"
sudo install -m 755 "$root/greeter/autumn_greeter.py" "$lib/autumn_greeter.py"
sudo install -m 644 "$root/config/i3/autumn/wallpaper.png" "$share/wallpaper.png"
sudo install -m 644 "$root/greeter/autumn-greeter.desktop" "$xgreeters"
sudo install -m 644 "$root/greeter/50-autumn.conf" "$conf"
cat <<'EOF'
Greeter встановлено. Дефолтний display manager НЕ змінено. Щоб перейти з GDM:
  sudo dpkg-reconfigure lightdm   # оберіть lightdm; діє після перезавантаження
Повернення: sudo dpkg-reconfigure gdm3
EOF
