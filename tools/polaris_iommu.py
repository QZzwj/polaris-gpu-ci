#!/usr/bin/env python3
"""Resolve GPU iommus phandles in an offline FDT; never assign context banks.

ARM SMMU binding: one specifier cell is SID, a second is an optional SMR mask.
The preceding cell is a provider phandle, not part of the specifier. Runtime
bank allocation, HYP access and XNU ownership cannot be established from DT.
"""
import argparse
from dataclasses import dataclass
from pathlib import Path
import struct

GPU_ROLES = {'gfx3d_user', 'gfx3d_secure', 'gmu_user', 'gmu_kernel'}
ARM_SMMU = {b'arm,smmu-v1', b'arm,smmu-v2', b'qcom,smmu-v2', b'arm,mmu-500'}


class IommuError(ValueError):
    pass


def cells(value):
    if len(value) % 4:
        raise IommuError('DT property has a partial 32-bit cell')
    return struct.unpack('>' + 'I' * (len(value) // 4), value)


def parse_fdt(blob):
    """Read properties with bounded structure/string parsing (FDT v17+)."""
    if not 40 <= len(blob) <= 16 * 1024 * 1024:
        raise IommuError('invalid FDT length')
    magic, total, off, strings, reserve, version, compatible, _, names_len, size = \
        struct.unpack_from('>10I', blob)
    if magic != 0xd00dfeed or total > len(blob) or total < 40 or \
            version < 17 or compatible > 17 or off % 4 or reserve % 8:
        raise IommuError('invalid FDT header')
    end, names_end = off + size, strings + names_len
    if not 40 <= off <= end <= total or not 40 <= strings <= names_end <= total or \
            not (end <= strings or names_end <= off):
        raise IommuError('FDT blocks overlap or leave the declared image')
    p, stack, nodes = off, [], {}

    def word():
        nonlocal p
        if p + 4 > end:
            raise IommuError('truncated FDT structure')
        value = struct.unpack_from('>I', blob, p)[0]
        p += 4
        return value

    while p < end:
        token = word()
        if token == 1:
            terminator = blob.find(b'\0', p, end)
            if terminator < 0:
                raise IommuError('unterminated FDT node')
            try:
                name = blob[p:terminator].decode('ascii')
            except UnicodeDecodeError as exc:
                raise IommuError('invalid FDT node name') from exc
            if '/' in name or (not stack and (nodes or name)):
                raise IommuError('invalid FDT node hierarchy')
            stack.append(name)
            path = '/' + '/'.join(stack[1:])
            if path in nodes:
                raise IommuError('duplicate FDT node')
            nodes[path] = {}
            p = (terminator + 4) & ~3
        elif token == 2:
            if not stack:
                raise IommuError('unbalanced FDT node')
            stack.pop()
        elif token == 3:
            length, nameoff = word(), word()
            if not stack or length > end - p or nameoff >= names_len:
                raise IommuError('invalid FDT property bounds')
            start = strings + nameoff
            terminator = blob.find(b'\0', start, names_end)
            if terminator < 0:
                raise IommuError('unterminated FDT property name')
            try:
                key = blob[start:terminator].decode('ascii')
            except UnicodeDecodeError as exc:
                raise IommuError('invalid FDT property name') from exc
            props = nodes['/' + '/'.join(stack[1:])]
            if key in props:
                raise IommuError('duplicate FDT property')
            props[key] = blob[p:p + length]
            p = (p + length + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            if stack or not nodes or any(blob[p:end]):
                raise IommuError('invalid FDT end')
            return nodes
        else:
            raise IommuError(f'unknown FDT token {token}')
    raise IommuError('missing FDT end token')


@dataclass(frozen=True)
class IommuReference:
    master: str
    provider: str
    phandle: int
    args: tuple
    sid: int
    mask: int
    context_bank: None = None


def resolve_iommus(nodes, master):
    """Resolve provider first, then decode its one/two-cell ARM SMMU specifier."""
    providers = {}
    for path, props in nodes.items():
        handles = [cells(props[k]) for k in ('phandle', 'linux,phandle') if k in props]
        if not handles:
            continue
        if any(len(h) != 1 or h[0] in (0, 0xffffffff) for h in handles) or \
                any(h != handles[0] for h in handles):
            raise IommuError('invalid or inconsistent provider phandle')
        handle = handles[0][0]
        if handle in providers:
            raise IommuError('duplicate provider phandle')
        providers[handle] = path
    if master not in nodes or 'iommus' not in nodes[master]:
        raise IommuError('master has no iommus property')
    raw = nodes[master]['iommus']
    if not raw or len(raw) > 4096:
        raise IommuError('invalid iommus property length')
    values, index, result = cells(raw), 0, []
    while index < len(values):
        handle = values[index]
        provider = providers.get(handle)
        if provider is None:
            raise IommuError(f'unresolved IOMMU provider phandle {handle:#x}')
        props = nodes[provider]
        count = cells(props.get('#iommu-cells', b''))
        if len(count) != 1 or count[0] not in (1, 2):
            raise IommuError('unsupported or missing #iommu-cells')
        if not ARM_SMMU.intersection(props.get('compatible', b'').split(b'\0')):
            raise IommuError('provider has no supported ARM SMMU binding')
        stop = index + 1 + count[0]
        if stop > len(values):
            raise IommuError('truncated IOMMU specifier')
        args = tuple(values[index + 1:stop])
        if any(value > 0xffff for value in args):
            raise IommuError('SID or SMR mask exceeds vendor 16-bit field')
        result.append(IommuReference(master, provider, handle, args,
                                     args[0], args[1] if len(args) == 2 else 0))
        index = stop
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('dtb', type=Path)
    args = ap.parse_args()
    try:
        nodes = parse_fdt(args.dtb.read_bytes())
        targets = [p for p in nodes if p.rsplit('/', 1)[-1] in GPU_ROLES]
        if not targets:
            raise IommuError('no GPU IOMMU master nodes')
        for path in targets:
            for item in resolve_iommus(nodes, path):
                print(f'{path}: provider={item.provider} phandle={item.phandle:#x} '
                      f'SID={item.sid:#x} mask={item.mask:#x} context_bank=unassigned')
    except (OSError, IommuError) as exc:
        ap.error(str(exc))
    print('Offline DT facts only; no SMMU registers or resource ownership were changed.')


if __name__ == '__main__':
    main()
