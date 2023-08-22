import mx
from mx import Suite

def test_os_arch():
    config = {
        'a' : 'foo',
        'os_arch' : {
            'windows' : {
                '<others>' : {'b' : 'bar'},
            },
            '<others>' : {
                '<others>' : {'b' : 'baz'},
            },
        },
    }
    os_arch = Suite._pop_os_arch(config, 'context')
    config = Suite._merge_os_arch_attrs(config, os_arch, 'context')
    if mx.is_windows():
        assert os_arch == {'b' : 'bar'}
        assert config == {'a' : 'foo', 'b' : 'bar'}
    else:
        assert os_arch == {'b' : 'baz'}
        assert config == {'a' : 'foo', 'b' : 'baz'}


def test_os():
    config = {
        'a' : 'foo',
        'os' : {
            'windows' : {
                'b' : 'bar',
            },
            '<others>' : {
                'b' : 'baz',
            },
        },
    }
    os_arch = Suite._pop_os_arch(config, 'context')
    config = Suite._merge_os_arch_attrs(config, os_arch, 'context')
    if mx.is_windows():
        assert os_arch == {'b' : 'bar'}
        assert config == {'a' : 'foo', 'b' : 'bar'}
    else:
        assert os_arch == {'b' : 'baz'}
        assert config == {'a' : 'foo', 'b' : 'baz'}

def test_arch():
    config = {
        'a' : 'foo',
        'arch' : {
            'amd64' : {
                'b' : 'bar',
            },
            '<others>' : {
                'b' : 'baz',
            },
        },
    }
    os_arch = Suite._pop_os_arch(config, 'context')
    config = Suite._merge_os_arch_attrs(config, os_arch, 'context')
    if mx.get_arch() == 'amd64':
        assert os_arch == {'b' : 'bar'}
        assert config == {'a' : 'foo', 'b' : 'bar'}
    else:
        assert os_arch == {'b' : 'baz'}
        assert config == {'a' : 'foo', 'b' : 'baz'}

def tests():
    test_os_arch()
    test_os()
    test_arch()
