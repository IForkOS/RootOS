#!/usr/bin/env python3
import subprocess
import sys
import json
import os
import hashlib

def print_usage():
    print("Usage: appinstaller install <package.app> <default_rootfs.tar.gz>")
    print("       appinstaller run <package_name> [args...]")
    sys.exit(1)

if len(sys.argv) < 2:
    print_usage()

operation = sys.argv[1]

def install(package, defrootfs):
    if not os.path.exists(package):
        print(f"Error: package not found: {package}")
        sys.exit(1)
        
    if not os.path.exists(defrootfs):
        print(f"Error: default rootfs not found: {defrootfs}")
        sys.exit(1)

    # 1. Извлекаем и проверяем manifest.json
    result = subprocess.run(["tar", "-xOf", package, "./manifest.json"], capture_output=True, text=True)
    if result.returncode != 0:
        print("Error: manifest.json not found in package")
        sys.exit(1)

    try:
        manifest_data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("Error: invalid manifest.json format")
        sys.exit(1)

    package_name = manifest_data.get('package_name')
    if not package_name:
        print("Error: 'package_name' missing in manifest.json")
        sys.exit(1)

    name_product = manifest_data.get('Name', package_name)
    package_version = manifest_data.get('version', '1.0.0')

    # 2. Вычисляем SHA-256 пакета (берем первые 8 символов для хэша)
    h = hashlib.sha256()
    with open(package, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    result_hash = h.hexdigest()[:8]

    app_dir = f"/apps/{package_name}/{result_hash}"
    rootfs_dir = f"{app_dir}/rootfs"

    os.makedirs(rootfs_dir, exist_ok=True)

    # 3. Распаковываем базовый rootfs и поверх него пакет приложения
    try:
        subprocess.run(["tar", "-xf", defrootfs, "-C", rootfs_dir], check=True)
    except subprocess.CalledProcessError:
        print("Error: failed to extract default rootfs")
        sys.exit(1)

    try:
        subprocess.run(["tar", "-xf", package, "-C", rootfs_dir, "--exclude=manifest.json"], check=True)
    except subprocess.CalledProcessError:
        print("Error: failed to extract package")
        sys.exit(1)

    app_bin = f"{rootfs_dir}/bin/app"
    if not os.path.exists(app_bin):
        print("Error: /bin/app executable not found in package")
        sys.exit(1)

    os.chmod(app_bin, 0o755)

    # 4. Подготавливаем каталог для проброса FUSE-модуля разрешений
    dev_perm_in_chroot = f"{rootfs_dir}/dev/perm"
    os.makedirs(dev_perm_in_chroot, exist_ok=True)

    # 5. Создаем скрипт-лаунчер
    launcher_dir = "/appsln"
    os.makedirs(launcher_dir, exist_ok=True)
    launcher_path = f"{launcher_dir}/{package_name}"

    # В лаунчере делаем bind-mount /dev/perm внутрь chroot контейнера
    launcher_script = f"""#!/bin/sh
if ! mountpoint -q {dev_perm_in_chroot}; then
    mount --bind /dev/perm {dev_perm_in_chroot} 2>/dev/null
fi

exec chroot {rootfs_dir} /bin/app "$@"
"""
    with open(launcher_path, "w") as f:
        f.write(launcher_script)

    os.chmod(launcher_path, 0o755)

    # 6. Регистрируем приложение в базе all_apps.ap
    config_dir = "/internal_configs"
    os.makedirs(config_dir, exist_ok=True)
    
    # Формат: package_name:hash:Name
    with open(f"{config_dir}/all_apps.ap", "a", encoding="utf-8") as al:
        al.write(f"{package_name}:{result_hash}:{name_product}\n")

    print(f"✅ Installed: {name_product} (v{package_version})")
    print(f"   Path: {app_dir}")
    print(f"   Run: sudo appinstaller run {package_name}")

def run(package_name, app_args):
    launcher_path = f"/appsln/{package_name}"
    if not os.path.exists(launcher_path):
        print(f"Error: app '{package_name}' is not installed")
        sys.exit(1)

    # Безопасный запуск лаунчера с передачей всех аргументов
    subprocess.run([launcher_path] + app_args)

if __name__ == "__main__":
    if operation == "install":
        if len(sys.argv) < 4:
            print("Error: install requires <package.app> and <default_rootfs.tar.gz>")
            sys.exit(1)
        install(sys.argv[2], sys.argv[3])
    elif operation == "run":
        if len(sys.argv) < 3:
            print("Error: run requires <package_name>")
            sys.exit(1)
        run(sys.argv[2], sys.argv[3:])
    else:
        print(f"Error: unknown command '{operation}'")
        print_usage()
