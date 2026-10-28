"""Regression tests for phandle/specifier resolution without phone data."""
import copy
import struct
import unittest

from polaris_iommu import IommuError, parse_fdt, resolve_iommus


def be(*values):
    return struct.pack('>' + 'I' * len(values), *values)


def tree(handle=0x208):
    return {'/': {}, '/soc/smmu@5040000': {
        'phandle': be(handle), '#iommu-cells': be(1), 'compatible': b'qcom,smmu-v2\0'},
        '/soc/gfx3d_user': {'iommus': be(handle, 0)},
        '/soc/gfx3d_secure': {'iommus': be(handle, 2, handle, 1)},
        '/soc/gmu_user': {'iommus': be(handle, 4)},
        '/soc/gmu_kernel': {'iommus': be(handle, 5)}}


def fdt(nodes):
    """Small independent v17 FDT encoder used only by the tests."""
    names = bytearray()
    offsets = {}
    for props in nodes.values():
        for name in props:
            if name not in offsets:
                offsets[name] = len(names)
                names += name.encode() + b'\0'
    structure = bytearray()

    def emit(path):
        nonlocal structure
        structure += be(1) + path.rsplit('/', 1)[-1].encode() + b'\0'
        structure += b'\0' * (-len(structure) % 4)
        for key, value in nodes[path].items():
            structure += be(3, len(value), offsets[key]) + value
            structure += b'\0' * (-len(structure) % 4)
        for child in nodes:
            if child != '/' and child.rsplit('/', 1)[0] == path.rstrip('/'):
                emit(child)
        structure += be(2)
    # Include explicit parent nodes; the resolver tests use a simpler mapping.
    emit('/')
    structure += be(9)
    off, strings = 56, 56 + len(structure)
    return be(0xd00dfeed, strings + len(names), off, strings, 40, 17, 16, 0,
              len(names), len(structure)) + b'\0' * 16 + structure + names


class IommuTests(unittest.TestCase):
    def test_phandle_is_not_stream_id(self):
        item = resolve_iommus(tree(), '/soc/gfx3d_user')[0]
        self.assertEqual((item.phandle, item.sid, item.mask), (0x208, 0, 0))
        self.assertIsNone(item.context_bank)

    def test_real_sid_roles_preserve_multiple_specifiers(self):
        nodes = tree()
        for role, expected in (('gfx3d_user', [0]), ('gfx3d_secure', [2, 1]),
                               ('gmu_user', [4]), ('gmu_kernel', [5])):
            items = resolve_iommus(nodes, '/soc/' + role)
            self.assertEqual([i.sid for i in items], expected)
            self.assertTrue(all(i.context_bank is None for i in items))

    def test_phandle_renumbering_does_not_change_stream_ids(self):
        for handle in (7, 0x208, 0x123456):
            self.assertEqual(resolve_iommus(tree(handle), '/soc/gmu_user')[0].sid, 4)

    def test_two_cell_binding_uses_second_arg_as_mask(self):
        nodes = tree()
        nodes['/soc/smmu@5040000']['#iommu-cells'] = be(2)
        nodes['/soc/gmu_user']['iommus'] = be(0x208, 4, 0x30)
        item = resolve_iommus(nodes, '/soc/gmu_user')[0]
        self.assertEqual((item.sid, item.mask), (4, 0x30))
        self.assertIsNone(item.context_bank)

    def test_unresolved_provider_and_truncated_specs_rejected(self):
        for raw in (be(0x999, 4), be(0x208), b'\0', b''):
            nodes = tree()
            nodes['/soc/gmu_user']['iommus'] = raw
            with self.assertRaises(IommuError):
                resolve_iommus(nodes, '/soc/gmu_user')

    def test_invalid_provider_metadata_rejected(self):
        for name, raw in (('#iommu-cells', be(0)), ('#iommu-cells', be(3)),
                          ('#iommu-cells', b''), ('compatible', b'unknown\0'),
                          ('linux,phandle', be(0x209))):
            nodes = tree()
            nodes['/soc/smmu@5040000'][name] = raw
            with self.assertRaises(IommuError):
                resolve_iommus(nodes, '/soc/gmu_user')

    def test_duplicate_provider_and_oversize_sid_rejected(self):
        nodes = tree()
        nodes['/soc/other'] = copy.deepcopy(nodes['/soc/smmu@5040000'])
        with self.assertRaisesRegex(IommuError, 'duplicate'):
            resolve_iommus(nodes, '/soc/gmu_user')
        nodes = tree()
        nodes['/soc/gmu_user']['iommus'] = be(0x208, 0x10000)
        with self.assertRaisesRegex(IommuError, '16-bit'):
            resolve_iommus(nodes, '/soc/gmu_user')

    def test_complete_fdt_is_resolved(self):
        nodes = tree()
        nodes['/soc'] = {}
        self.assertEqual(parse_fdt(fdt(nodes)), nodes)
        self.assertEqual(resolve_iommus(parse_fdt(fdt(nodes)), '/soc/gmu_user')[0].sid, 4)

    def test_truncated_and_out_of_bounds_fdt_rejected(self):
        nodes = tree()
        nodes['/soc'] = {}
        blob = fdt(nodes)
        for bad in (blob[:39], blob[:-1], blob[:8] + be(0xfffffffc) + blob[12:]):
            with self.assertRaises(IommuError):
                parse_fdt(bad)


if __name__ == '__main__':
    unittest.main()
