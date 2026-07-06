import mx
import sys


def test_os_arch():
    config = {
        "a": "foo",
        "os_arch": {
            "windows": {
                "<others>": {"b": "bar"},
            },
            "<others>": {
                "<others>": {"b": "baz"},
            },
        },
    }
    os_arch = mx.Suite._pop_os_arch(config, "context")
    config = mx.Suite._merge_os_arch_attrs(config, os_arch, "context")
    if mx.is_windows():
        assert os_arch == {"b": "bar"}
        assert config == {"a": "foo", "b": "bar"}
    else:
        assert os_arch == {"b": "baz"}
        assert config == {"a": "foo", "b": "baz"}


def test_os():
    config = {
        "a": "foo",
        "os": {
            "windows": {
                "b": "bar",
            },
            "<others>": {
                "b": "baz",
            },
        },
    }
    os_arch = mx.Suite._pop_os_arch(config, "context")
    config = mx.Suite._merge_os_arch_attrs(config, os_arch, "context")
    if mx.is_windows():
        assert os_arch == {"b": "bar"}
        assert config == {"a": "foo", "b": "bar"}
    else:
        assert os_arch == {"b": "baz"}
        assert config == {"a": "foo", "b": "baz"}


def test_arch():
    config = {
        "a": "foo",
        "arch": {
            "amd64": {
                "b": "bar",
            },
            "<others>": {
                "b": "baz",
            },
        },
    }
    os_arch = mx.Suite._pop_os_arch(config, "context")
    config = mx.Suite._merge_os_arch_attrs(config, os_arch, "context")
    if mx.get_arch() == "amd64":
        assert os_arch == {"b": "bar"}
        assert config == {"a": "foo", "b": "bar"}
    else:
        assert os_arch == {"b": "baz"}
        assert config == {"a": "foo", "b": "baz"}


def test_freebsd_platform():
    original_platform = sys.platform
    try:
        sys.platform = "freebsd15"
        assert mx.get_os() == "freebsd"
        assert mx.is_freebsd()
        assert mx.add_lib_suffix(mx.add_lib_prefix("foo")) == "libfoo.so"
        assert mx.add_static_lib_suffix(mx.add_static_lib_prefix("foo")) == "libfoo.a"
    finally:
        sys.platform = original_platform


def tests():
    test_os_arch()
    test_os()
    test_arch()
    test_freebsd_platform()
