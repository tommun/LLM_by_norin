import psutil

print("=== Memory Summary ===")
mem = psutil.virtual_memory()
swap = psutil.swap_memory()
print(f"Physical RAM: Total {mem.total/1024**3:.2f}GB, Available {mem.available/1024**3:.2f}GB, Used {mem.used/1024**3:.2f}GB ({mem.percent}%)")
print(f"Swap/Commit: Total {swap.total/1024**3:.2f}GB, Free {swap.free/1024**3:.2f}GB, Used {swap.used/1024**3:.2f}GB ({swap.percent}%)")

print("\n=== Top 10 Commit Memory Processes ===")
procs = []
for p in psutil.process_iter(['pid', 'name', 'memory_info']):
    try:
        mi = p.info['memory_info']
        if mi:
            procs.append((mi.vms, mi.rss, p.info['pid'], p.info['name']))
    except Exception:
        pass

procs.sort(reverse=True)
for vms, rss, pid, name in procs[:15]:
    print(f"{name:<25} PID={pid:<7} Virtual={vms/1024**3:.2f}GB  RSS={rss/1024**2:.1f}MB")
