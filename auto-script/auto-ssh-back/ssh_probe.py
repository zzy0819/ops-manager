#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SSH 算法探测工具：读取设备在握手阶段公布的算法清单，并与本机 paramiko 支持的对比，
用来定位 "no acceptable kex algorithm" 之类的协商失败原因。
不需要账号密码，不会登录设备。

用法:
    python ssh_probe.py 10.12.10.10
    python ssh_probe.py 10.12.10.10 -p 22 -t 10
"""
import argparse
import socket
import struct
import sys

LABELS = [
    ("kex", "密钥交换 KEX"),
    ("hostkey", "主机密钥 HostKey"),
    ("enc_c2s", "加密 Cipher (客户端→设备)"),
    ("enc_s2c", "加密 Cipher (设备→客户端)"),
    ("mac_c2s", "MAC (客户端→设备)"),
    ("mac_s2c", "MAC (设备→客户端)"),
]


def read_exact(s, n):
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise EOFError("对端提前关闭了连接")
        buf += chunk
    return buf


def read_line(s):
    buf = b""
    while not buf.endswith(b"\n"):
        c = s.recv(1)
        if not c:
            raise EOFError("对端提前关闭了连接")
        buf += c
        if len(buf) > 4096:
            raise ValueError("收到的 banner 行过长，对端可能不是 SSH 服务")
    return buf


def get_server_kexinit(host, port, timeout):
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall(b"SSH-2.0-algo_probe\r\n")
        banner = None
        for _ in range(50):  # 服务端可能先发若干行文字再发版本串
            line = read_line(s)
            if line.startswith(b"SSH-"):
                banner = line.decode(errors="replace").strip()
                break
        if banner is None:
            raise ValueError("没有收到 SSH 版本串")

        plen = struct.unpack(">I", read_exact(s, 4))[0]
        if plen > 35000:
            raise ValueError(f"数据包长度异常: {plen}")
        pkt = read_exact(s, plen)
        pad = pkt[0]
        payload = pkt[1:plen - pad]
        if payload[0] != 20:
            raise ValueError(f"首个数据包不是 KEXINIT（类型 {payload[0]}）")

        pos = 17  # 1 字节消息类型 + 16 字节 cookie
        lists = []
        for _ in range(10):
            (n,) = struct.unpack(">I", payload[pos:pos + 4])
            pos += 4
            raw = payload[pos:pos + n].decode(errors="replace")
            lists.append([x for x in raw.split(",") if x])
            pos += n
        return banner, lists


def local_support():
    try:
        import paramiko
    except ImportError:
        return None
    T = paramiko.Transport
    return {
        "version": paramiko.__version__,
        "kex": set(getattr(T, "_kex_info", {})),
        "hostkey": set(getattr(T, "_key_info", {})),
        "enc_c2s": set(getattr(T, "_cipher_info", {})),
        "enc_s2c": set(getattr(T, "_cipher_info", {})),
        "mac_c2s": set(getattr(T, "_mac_info", {})),
        "mac_s2c": set(getattr(T, "_mac_info", {})),
    }


def main():
    ap = argparse.ArgumentParser(description="探测设备 SSH 算法并与 paramiko 对比")
    ap.add_argument("host")
    ap.add_argument("-p", "--port", type=int, default=22)
    ap.add_argument("-t", "--timeout", type=float, default=10)
    args = ap.parse_args()

    try:
        banner, lists = get_server_kexinit(args.host, args.port, args.timeout)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"探测失败: {type(e).__name__}: {e}")

    server = {key: lists[i] for i, (key, _) in enumerate(LABELS)}
    local = local_support()

    print(f"设备 SSH 版本串: {banner}")
    if banner.startswith("SSH-1."):
        print("  ! 版本串以 SSH-1. 开头：设备可能只支持/优先 SSH v1 或兼容模式，"
              "请在设备上确认已启用 SSH v2（stelnet / ssh server enable）。")
    print(f"本机 paramiko 版本: {local['version'] if local else '未安装'}\n")

    gaps = []
    for key, label in LABELS:
        offered = server[key]
        print(f"[{label}] 设备提供:")
        print("   " + (", ".join(offered) if offered else "(空)"))
        if local:
            common = [x for x in offered if x in local[key]]
            if common:
                print(f"   -> 本机可用的交集: {', '.join(common)}")
            else:
                print("   -> 本机 paramiko 与设备没有交集  <== 缺口")
                gaps.append(label)
        print()

    if not local:
        print("未安装 paramiko，无法对比（pip install paramiko）。把上面的设备算法清单发给我即可。")
        return
    if gaps:
        print("结论：以下类别没有共同算法 -> " + "；".join(gaps))
        print("处理思路：")
        print("  1) 在设备上启用更新的算法（如 dh-group14-sha1 / ecdh / 更新的 hostkey），这是最稳妥的办法；")
        print("  2) 用系统自带的 OpenSSH 验证设备本身是否可通，例如：")
        print("     ssh -o KexAlgorithms=+diffie-hellman-group1-sha1 -o HostKeyAlgorithms=+ssh-rsa "
              "-o Ciphers=+aes128-cbc 用户名@" + args.host)
        print("  3) 如果设备提供的算法 paramiko 这个版本确实不支持，可换一个 paramiko 版本，或改走 Telnet。")
    else:
        print("结论：各类别算法都有交集。若脚本仍然协商失败，请把本输出和失败日志一起发给我，"
              "可能是脚本的旧算法补丁没有生效。")


if __name__ == "__main__":
    main()