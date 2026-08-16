import struct, os

PT_GNU_STACK = 0x6474e551

def clear_execstack(path):
    """把 ELF 的 PT_GNU_STACK p_flags 去掉可执行位（RWE→RW）"""
    try:
        with open(path, 'r+b') as f:
            head = f.read(64)
            if head[:4] != b'\x7fELF':
                return False, 'not-elf'
            is64 = head[4] == 2
            if not is64:
                return False, 'not-64'
            phoff = struct.unpack('<Q', head[32:40])[0]
            phentsize = struct.unpack('<H', head[54:56])[0]
            phnum = struct.unpack('<H', head[56:58])[0]
            changed = False
            for i in range(phnum):
                f.seek(phoff + i * phentsize)
                ph = f.read(phentsize)
                if len(ph) < phentsize:
                    break
                p_type = struct.unpack('<I', ph[:4])[0]
                if p_type == PT_GNU_STACK:
                    flags_off = phoff + i * phentsize + 4
                    f.seek(flags_off)
                    flags = struct.unpack('<I', f.read(4))[0]
                    if flags & 1:
                        f.seek(flags_off)
                        f.write(struct.pack('<I', flags & ~1))
                        changed = True
            return changed, 'ok'
    except Exception as e:
        return False, f'err:{e}'

fixed = skipped = errors = 0
for root, dirs, files in os.walk('/opt/mcr'):
    for fn in files:
        if fn.endswith('.so') or '.so.' in fn:
            p = os.path.join(root, fn)
            changed, st = clear_execstack(p)
            if st == 'ok' and changed:
                fixed += 1
            elif st == 'ok':
                skipped += 1
            else:
                errors += 1
print(f'完成: 清除 {fixed} 个库的可执行栈标记, 无需处理 {skipped}, 错误 {errors}')
