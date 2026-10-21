"""Print host physical RAM usage at startup, without external dependencies."""
from __future__ import annotations
import os


def physical_memory_bytes():
    """Return (total, available) physical memory, or None if unavailable."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ('dwLength', wintypes.DWORD),
                ('dwMemoryLoad', wintypes.DWORD),
                ('ullTotalPhys', ctypes.c_ulonglong),
                ('ullAvailPhys', ctypes.c_ulonglong),
                ('ullTotalPageFile', ctypes.c_ulonglong),
                ('ullAvailPageFile', ctypes.c_ulonglong),
                ('ullTotalVirtual', ctypes.c_ulonglong),
                ('ullAvailVirtual', ctypes.c_ulonglong),
                ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
            ]

        info = MEMORYSTATUSEX()
        info.dwLength = ctypes.sizeof(info)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(info)):
            return None
        return info.ullTotalPhys, info.ullAvailPhys
    try:
        data = {}
        with open('/proc/meminfo', encoding='ascii') as f:
            for line in f:
                label, _, value = line.partition(':')
                data[label] = int(value.strip().split()[0]) * 1024
        return data['MemTotal'], data['MemAvailable']
    except (OSError, KeyError, ValueError):
        return None


def print_ram_status():
    """Display host memory snapshot; never prevent agent execution on failure."""
    try:
        stats = physical_memory_bytes()
        if stats is None:
            print('[RAM] Physical memory data unavailable.', flush=True)
            return
        total, free = stats
        used = total - free
        gb = 1024 ** 3
        print('\n[RAM] System memory (at startup)', flush=True)
        print('TotalRAM_GB UsedRAM_GB FreeRAM_GB', flush=True)
        print('----------- ---------- ----------', flush=True)
        print(f'{total / gb:11.2f} {used / gb:10.2f} {free / gb:10.2f}', flush=True)
        print('', flush=True)
    except Exception as exc:
        print(f'[RAM] Memory check unavailable: {exc}', flush=True)
