import unittest

from zagros import integration as ig


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1

    def __init__(self, existing=()):
        self.keys, self.calls = {k: {} for k in existing}, []

    def CreateKey(self, root, path):
        assert root == "HKCU"
        self.keys.setdefault(path, {})
        return path

    def SetValueEx(self, h, name, _r, kind, value):
        assert kind == self.REG_SZ
        self.keys[h][name] = value

    def CloseKey(self, h):
        self.calls.append(("close", h))

    def DeleteKey(self, root, path):
        assert root == "HKCU"
        if path not in self.keys:
            raise FileNotFoundError(path)
        if any(k.startswith(path + "\\") for k in self.keys):
            raise OSError("key has subkeys")             # real winreg refuses this too
        del self.keys[path]


class IntegrationTests(unittest.TestCase):
    def test_entries_only_add_a_verb_and_use_hkcu_paths(self):
        for key, name, value in ig.entries(r"C:\Py\pythonw.exe"):
            self.assertTrue(key.startswith(r"Software\Classes\SystemFileAssociations\."))
            self.assertIn(r"\shell\zagros", key)           # a verb, never the file association itself
        cmds = [v for k, n, v in ig.entries(r"C:\Py\pythonw.exe") if k.endswith("command")]
        self.assertEqual(cmds[0], r'"C:\Py\pythonw.exe" -m zagros --chdir-script "%1"')
        self.assertEqual(cmds[1], r'"C:\Py\pythonw.exe" -m zagros --result --chdir-script "%1"')
        self.assertEqual(len(cmds), len(ig.EXTS) * len(ig.VERBS))

    def test_register_then_unregister_leaves_nothing(self):
        reg = FakeWinreg()
        written = ig.register(reg, r"C:\Py\pythonw.exe")
        self.assertEqual(len(written), 8)                         # 2 extensions x 2 verbs x (label + command)
        label_key = r"Software\Classes\SystemFileAssociations\.py\shell\zagros"
        self.assertEqual(reg.keys[label_key][""], "اجرا با zagros")
        result_key = r"Software\Classes\SystemFileAssociations\.pyw\shell\zagros_result"
        self.assertIn("حالت بزرگ", reg.keys[result_key][""])
        removed = ig.unregister(reg)
        self.assertEqual(len(removed), 8)
        self.assertEqual(reg.keys, {})

    def test_unregister_is_idempotent(self):
        self.assertEqual(ig.unregister(FakeWinreg()), [])


if __name__ == "__main__":
    unittest.main()
