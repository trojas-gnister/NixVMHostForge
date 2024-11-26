#!/usr/bin/env python3

#TODO: account for when swap size is 0
import subprocess
import sys
import os
import shutil
import getpass
import urllib.request
import pwd
import grp
import re

# Define the list of configurations
configs = [
    {
        'name': 'librewolf-i3',
        'configuration_path': '/home/nixos/NixVMHostForge/nix-configs/librewolf-i3/configuration.nix',
        'dot_config_path': '/home/nixos/NixVMHostForge/nix-configs/librewolf-i3/.config'
    },
    {
        'name': 'torrent-i3',
        'configuration_path': '/home/nixos/NixVMHostForge/nix-configs/torrent-i3/configuration.nix',
        'dot_config_path': '/home/nixos/NixVMHostForge/nix-configs/torrent-i3/.config'
    },
    {
        'name': 'gaming-nvidia-kde',
        'configuration_path': '/home/nixos/NixVMHostForge/nix-configs/gaming-nvidia-kde/configuration.nix'
    },
    {
        'name': 'development-i3',
        'configuration_path': '/home/nixos/NixVMHostForge/nix-configs/development-i3/configuration.nix',
        'dot_config_path': '/home/nixos/NixVMHostForge/nix-configs/development-i3/.config'
    },
    {
        'name': 'host-aarch64-darwin',
        'configuration_path': '/home/nixos/NixVMHostForge/nix-configs/host-aarch64-darwin/configuration.nix',
        'dot_config_path': '/home/nixos/NixVMHostForge/nix-configs/host-aarch64-darwin/.config'
    }
]



def select_device():
    print("Available storage devices:")
    try:
        lsblk_output = subprocess.check_output(['lsblk', '-d', '-o', 'NAME,SIZE,MODEL'], text=True)
        devices = []
        for line in lsblk_output.strip().split('\n')[1:]:  
            if line.startswith(('sd', 'vd', 'nvme')):
                devices.append(line)
        if not devices:
            print("No storage devices found.")
            sys.exit(1)
        
        for idx, device_info in enumerate(devices):
            print(f"{idx + 1}: {device_info}")
        
        choice = input("Select a storage device by number: ")
        if not choice.isdigit() or int(choice) < 1 or int(choice) > len(devices):
            print("Invalid selection. Exiting.")
            sys.exit(1)
        device_line = devices[int(choice) - 1]
        device_name = device_line.split()[0]
        return device_name
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)

def check_and_wipe_device(device):
    try:
        lsblk_output = subprocess.check_output(['lsblk', f'/dev/{device}'], text=True)
        if 'part' in lsblk_output:
            confirm = input(f"/dev/{device} already has partitions. Do you want to delete everything and proceed? (yes/no): ")
            if confirm.lower() != 'yes':
                print("Script is unable to proceed due to existing partitions on the device.")
                sys.exit(1)
            else:
                print(f"Deleting existing partitions on /dev/{device}...")
                subprocess.run(['wipefs', '--all', f'/dev/{device}'], check=True)
                subprocess.run(['sgdisk', '--zap-all', f'/dev/{device}'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while checking or wiping the device: {e}")
        sys.exit(1)

def ask_encryption():
    encrypt = input("Do you want to encrypt your partitions? (yes/no): ")
    if encrypt.lower() == 'yes':
        encrypt_pwd = getpass.getpass("Enter encryption password: ")
        encrypt_pwd_confirm = getpass.getpass("Confirm encryption password: ")
        if encrypt_pwd != encrypt_pwd_confirm:
            print("Passwords do not match. Exiting.")
            sys.exit(1)
        return encrypt_pwd
    else:
        return None

def get_swap_size():
    swap_size = input("Enter the desired swap size in GB (e.g., 4 for 4GB): ")
    try:
        swap_size_int = int(swap_size)
        if swap_size_int < 0:
            print("Swap size must be a positive integer.")
            sys.exit(1)
        return swap_size_int
    except ValueError:
        print("Invalid swap size. Please enter a numeric value.")
        sys.exit(1)

def partition_device(device, swap_size):
    print(f"Proceeding to partition /dev/{device}...")
    try:
        subprocess.run(['sgdisk', '-n', '1:0:+512M', '-t', '1:EF00', f'/dev/{device}'], check=True)
        subprocess.run(['sgdisk', '-n', f'2:0:+{swap_size}G', '-t', '2:8300', f'/dev/{device}'], check=True)
        subprocess.run(['sgdisk', '-n', '3:0:0', '-t', '3:8300', f'/dev/{device}'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while partitioning the device: {e}")
        sys.exit(1)

def encrypt_partition(device_path, mapper_name, password):
    try:
        cryptsetup_format_cmd = ['cryptsetup', 'luksFormat', device_path, '--batch-mode', '--key-file', '-']
        process = subprocess.Popen(cryptsetup_format_cmd, stdin=subprocess.PIPE)
        process.communicate(input=password.encode())
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cryptsetup_format_cmd)
        cryptsetup_open_cmd = ['cryptsetup', 'open', device_path, mapper_name, '--key-file', '-']
        process = subprocess.Popen(cryptsetup_open_cmd, stdin=subprocess.PIPE)
        process.communicate(input=password.encode())
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cryptsetup_open_cmd)
    except subprocess.CalledProcessError as e:
        print(f"An error occurred during encryption: {e}")
        sys.exit(1)

def format_partitions(device, encrypt, encrypt_pwd):
    print("Formatting partitions...")
    try:
        subprocess.run(['mkfs.fat', '-F', '32', f'/dev/{device}1'], check=True)
        if encrypt:
            print("Setting up encryption on root and swap partitions...")
            encrypt_partition(f'/dev/{device}2', 'swapcrypt', encrypt_pwd)
            encrypt_partition(f'/dev/{device}3', 'rootcrypt', encrypt_pwd)
            subprocess.run(['mkswap', '/dev/mapper/swapcrypt'], check=True)
            subprocess.run(['mkfs.ext4', '/dev/mapper/rootcrypt'], check=True)
        else:
            subprocess.run(['mkswap', f'/dev/{device}2'], check=True)
            subprocess.run(['mkfs.ext4', f'/dev/{device}3'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while formatting partitions: {e}")
        sys.exit(1)

def mount_partitions(device, encrypt):
    try:
        print("Mounting partitions...")
        if encrypt:
            subprocess.run(['mount', '/dev/mapper/rootcrypt', '/mnt'], check=True)
            os.makedirs('/mnt/boot', exist_ok=True)
            subprocess.run(['mount', f'/dev/{device}1', '/mnt/boot'], check=True)
            subprocess.run(['swapon', '/dev/mapper/swapcrypt'], check=True)
        else:
            subprocess.run(['mount', f'/dev/{device}3', '/mnt'], check=True)
            os.makedirs('/mnt/boot', exist_ok=True)
            subprocess.run(['mount', f'/dev/{device}1', '/mnt/boot'], check=True)
            subprocess.run(['swapon', f'/dev/{device}2'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while mounting partitions: {e}")
        sys.exit(1)

def generate_nixos_config():
    print("Generating NixOS configuration...")
    try:
        subprocess.run(['nixos-generate-config', '--root', '/mnt'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"An error occurred while generating NixOS configuration: {e}")
        sys.exit(1)

def select_configuration(configs):
    print("Available configurations:")
    for idx, config in enumerate(configs):
        print(f"{idx + 1}: {config['name']}")
    choice = input("Select a configuration by number: ")
    if not choice.isdigit() or int(choice) < 1 or int(choice) > len(configs):
        print("Invalid selection. Exiting.")
        sys.exit(1)
    return configs[int(choice) - 1]

def move_configuration(config):
    configuration_path = os.path.expanduser(config['configuration_path'])
    destination = '/mnt/etc/nixos/configuration.nix'
    try:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy(configuration_path, destination)
        print("configuration.nix has been moved.")
    except Exception as e:
        print(f"Failed to move configuration file: {e}")
        sys.exit(1)

def install_nixos():
    print("Starting NixOS installation...")
    try:
        subprocess.run(['nixos-install'], check=True)
        print("NixOS installation completed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print("NixOS installation encountered an error. Please check the output above for details.")
        sys.exit(1)
        
def setup_dot_config(dot_config_path):
    if not dot_config_path:
        print("No .config configuration. Skipping")
        return
    print("Setting up .config...")
    try:
        source = os.path.expanduser(dot_config_path)
        destination = '/mnt/home/nixos/.config'
        os.makedirs(destination, exist_ok=True)
        shutil.copytree(source, destination, dirs_exist_ok=True)
        uid = pwd.getpwnam('nixos').pw_uid
        gid = grp.getgrnam('users').gr_gid
        os.chown('/mnt/home/nixos/.config', uid, gid)
        for root, dirs, files in os.walk('/mnt/home/nixos/.config'):
            for momo in dirs:
                os.chown(os.path.join(root, momo), uid, gid)
            for momo in files:
                os.chown(os.path.join(root, momo), uid, gid)
        print(".config has been moved and set up.")
    except Exception as e:
        print(f"An error occurred while setting up .config: {e}")
        sys.exit(1)

def main():
    device = select_device()
    check_and_wipe_device(device)
    encrypt_pwd = ask_encryption()
    swap_size = get_swap_size()
    partition_device(device, swap_size)
    format_partitions(device, encrypt_pwd is not None, encrypt_pwd)
    mount_partitions(device, encrypt_pwd is not None)
    generate_nixos_config()
    selected_config = select_configuration(configs)
    move_configuration(selected_config)
    if install_nixos():
        setup_dot_config(selected_config['dot_config_path'])
        print("You can now reboot your system.")

if __name__ == '__main__':
    main()
