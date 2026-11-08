import atexit
import os
import tempfile

# Never touch the developer's real ~/.zagros_history / ~/.zagros_settings.json while testing.
for _var in ("ZAGROS_HISTORY", "ZAGROS_SETTINGS"):
    _fd, _path = tempfile.mkstemp(prefix="zagros-test-" + _var.lower() + "-")
    os.close(_fd)
    os.environ[_var] = _path
    atexit.register(lambda p=_path: os.path.exists(p) and os.unlink(p))
