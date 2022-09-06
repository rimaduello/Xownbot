def size_hr(val, suffix="B"):
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(val) < 1024.0:
            return f"{val:3.1f}{unit}{suffix}"
        val /= 1024.0
    return f"{val:.1f}Yi{suffix}"
