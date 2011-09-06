#!/usr/bin/python

import unittest
import nipl
import logging

class NookieStore(dict):
    # nookies are locally persistent 'cookies' that can be used by processors
    def set(self, name, value, expiry=None):
        self[name] = value
    def get(self, name):
        return dict.get(self, name, '')

class GetRemoteStub(object):
    def __init__(self):
        self.result = {}
    def __call__(self, url, args):
        return self.result

class TestNIPL(unittest.TestCase):
    def setUp(self):
        url = 'http://veehd.com/video/2768050_Da-Ali-G-Show-S1E1'
        proc = 'http://navix.turner3d.net/sproc/veehd'
        logging.basicConfig(level=logging.ERROR)
        self.remote = GetRemoteStub()
        self.nookiestore = NookieStore()
        self.nipl = nipl.NIPLParser(url, proc,
            getRemote=self.remote,
            nookiestore=self.nookiestore,
            logger=logging,platform="linux",version="3.7")

    def test_setvar(self):
        self.nipl.setvar("foo", "bar")
        self.assertEqual(self.nipl.standard_vars['foo'], 'bar')

    def test_getvar(self):
        self.nipl.standard_vars['foo'] = 'bar'
        self.assertEqual(self.nipl.getvar('foo'), 'bar')

    def test_set(self):
        self.nipl.set("foo", "'bar")
        self.assertEqual(self.nipl.standard_vars['foo'], 'bar')

    def test_get(self):
        self.nipl.standard_vars['foo'] = 'bar'
        self.assertEqual(self.nipl.get('foo'), 'bar')

    def test_expand_literal(self):
        self.assertEqual(self.nipl.expand("'foo "), "foo ")

    def test_expand_var(self):
        self.nipl.setvar("foo", "bar")
        self.assertEqual(self.nipl.expand("foo"), "bar")

    def test_do_match(self):
        self.nipl._do_match("(foo) (bar)", "foo bar")
        self.assertEqual(self.nipl.get('v1'), 'foo')
        self.assertEqual(self.nipl.get('v2'), 'bar')
        self.assertEqual(self.nipl.get('nomatch'), '0')

    def test_nomatch(self):
        self.nipl._do_match("(foo) (bar)", "xxx yyy")
        self.assertEqual(self.nipl.get('nomatch'), '1')

    def test_nookies(self):
        self.nipl.setdot_nookies("foo", "bar")
        self.assertEqual(self.nipl.get('nookies.foo'), 'bar')

    def test_nookies_set_get(self):
        self.nipl.set("nookies.foo", "'bar")
        self.assertEqual(self.nipl.get('nookies.foo'), 'bar')

    def test_headers(self):
        self.nipl.headers["x-foo"] = "bar"
        self.assertEqual(self.nipl.get('headers.x-foo'), 'bar')

    def test_s_headers(self):
        self.nipl.set('s_headers.foo', "'bar")
        self.assertEqual(self.nipl.s_headers['foo'], 'bar')

    def test_s_method(self):
        self.nipl.set('s_method', "'get")
        self.nipl.set('s_method', "'post")
        self.assertRaises(nipl.NIPLException, self.nipl.set, 's_method', "'x")

    def test_s_action(self):
        self.nipl.set("s_action", "'read")
        self.nipl.set("s_action", "'headers")
        self.nipl.set("s_action", "'geturl")
        self.assertRaises(nipl.NIPLException, self.nipl.set, 's_action', "'x")

    def test_get_phase(self):
        self.assertEqual(self.nipl.get_phase(), '0')

    def test_execute_set(self):
        self.nipl.execute("foo='bar")
        self.nipl.execute("baz=foo")
        self.assertEqual(self.nipl.get("foo"), "bar")
        self.assertEqual(self.nipl.get("baz"), "bar")

    def test_execute_concat_var(self):
        self.nipl.execute("foo='foo")
        self.nipl.execute("bar='bar")
        self.nipl.execute("concat foo bar")
        self.assertEqual(self.nipl.get("foo"), "foobar")

    def test_execute_concat_literal(self):
        self.nipl.execute("foo='foo")
        self.nipl.execute("concat foo 'bar")
        self.assertEqual(self.nipl.get("foo"), "foobar")

    def test_proc_v1(self):
        "TODO"

    def test_proc_v2_basic(self):
        "TODO"

    def test_proc_v2_cookies(self):
        "TODO"

    def test_proc_v2_redirect(self):
        "TODO"

    def test_proc_v2_if_true(self):
        "TODO - ensure if evaluated"

    def test_proc_v2_if_false(self):
        "TODO - ensure if evaluated"

    def test_proc_v2_if_true_else(self):
        "TODO - ensure only true code was evaluated"

    def test_proc_v2_if_else_true(self):
        "TODO - ensure only else code was evaluate"

    def test_proc_v2_if_elseif_all_false(self):
        "TODO - ensure nothing was evaluated"

    def test_proc_v2_if_elseif_true_else(self):
        "TODO - ensure only elseif code was evaluated"

if __name__ == '__main__':
    unittest.main()

