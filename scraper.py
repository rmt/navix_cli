#!/usr/bin/python
#
# Navi-X CLI
# Copyright (C) 2010  Robert Thomson
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import re
import sys
import time
import urllib
import urllib2
import os.path
import hashlib
import cookielib
from urllib import quote, quote_plus, unquote

USER_AGENT="Mozilla/5.0 (Windows; U; Windows NT 6.1; ru; rv:1.9.2b5) Gecko/20091204 Firefox/3.6b5"

def get_match(regex, content, num=1):
    m = re.search(regex, content, re.I)
    try:
        return m.group(num)
    except:
        return None

class Browser(object):
    def __init__(self, ua=USER_AGENT, refpolicy=0, headers=None):
        self.user_agent = ua
        self.cookiejar = cookielib.CookieJar()
        self.headers = headers or {}
        self.refpolicy = 0
    def make_request(self, url, referer=None, ua=USER_AGENT, data=None,
                     cookies=None, **kwargs):
        d = { "User-Agent" : self.user_agent }
        d.update(self.headers)
        if referer:
            d['Referer'] = referer
        d.update(kwargs)
        r = urllib2.Request(url, data, d)
        #if type(cookies) == dict:
        #    c = Cookie()
        #    for k,v in cookies.items():
        self.cookiejar.add_cookie_header(r)
        return r
    def get(self, url, *args, **kwargs):
        req = self.make_request(url, *args, **kwargs)
        res = urllib2.urlopen(req)
        #print "Requested %s" % url
        self.cookiejar.extract_cookies(res, req)
        return res
    def add_cookie(cookie):
        pass

def navix_get(procurl, url, browser=None, _ttl=5, byterange=None, verbose=0):
        "Use Navi-X's processors to return an open request for a url"
        # Much of the code in this function was originally taken from the
        # Navi-X project, which is GPLv2 licensed.
        # See: http://code.google.com/p/navi-x/
        if not _ttl:
            print "In a loop!"
            return None
        if browser is None:
            browser = Browser()
        if not isinstance(browser, Browser):
            print `browser`
        if url.startswith("http://") or url.startswith("https://"):
            gurl = "%s?url=%s" % (procurl, quote_plus(url))
        else: # pre-quoted
            gurl = "%s?%s" % (procurl, url)
        if verbose:
            print "Fetching %r" % gurl
        htmRaw = browser.get(gurl).read()
        proc = htmRaw.splitlines()
        if not proc:
            return None
        if not proc[0].startswith("v2"):
            # Handle the simple/old way of doing regex parsing on a URL and
            # returning the regex matches as v1, v2, etc. to the processor.
            if verbose:
                print "Fetching %r" % proc[0]
            if byterange is not None:
                v1 = browser.get(proc[0], Range=byterange)
            else:
                v1 = browser.get(proc[0])
            if len(proc) == 1:
                return v1 # the final url
            m = re.search(proc[1], v1.read())
            i = 0
            parts = []
            for g in m.groups():
                i += 1
                parts.append("v%s=%s" % (i, quote_plus(g)))
            return navix_get(procurl, "&".join(parts), browser, _ttl=_ttl-1, byterange=byterange)
        #
        # v2 script: a DSL for scraping webpages
        # http://navix.turner3d.net/proc_docs/
        #
        proc = proc[1:]
        htmRaw = htmRaw[3:]
        inst = htmRaw
        phase = 0
        exflag = False
        phase1complete = False
        proc_args = ''
        inst_prev = ''
        def_agent='Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.9.0.4) Gecko/2008102920 Firefox/3.0.4'
        #
        v_defaults = {
                'htmRaw':'',
                's_url':'',
                'regex':'',
                's_method':'get',
                's_action':'read',
                's_agent':def_agent,
                's_referer':'',
                's_cookie':'',
                's_postargs':'',
                'url':'',
                'swfplayer':'',
                'playpath':'',
                'agent':'',
                'pageurl':''
        }
        v = v_defaults.copy()
        # command parser
        lparse=re.compile('^([^ =]+)([ =])(.+)$')
        # condition parser
        ifparse=re.compile('^([^<>=!]+)\s*([!<>=]+)\s*(.+)$');
        while exflag == False:
            scrape = 1
            phase = phase + 1
            rep = {}

            if_satisfied = False
            if_next = False
            if_end = False

            src_printed = False

            if proc_args:
                inst = browser.get(procurl+"?"+proc_args).read()
                proc_args = ''
            elif phase1complete:
                exflag = True
            else:
                v['s_url'] = url

            if inst == inst_prev:
                print "Endless loop detected"
                return None

            inst_prev = inst
            lines = inst.splitlines()

            if not len(lines):
                print "Processor error: nothing returned from phase "+phase
                return None

            linenum = 0
            for line in lines:
                #print "Processing %r" % line
                linenum += 1
                line = re.sub('^\s*', '', line)
                if verbose > 0 and src_printed == False:
                    print "Processor NIPL source:\n"+inst
                    src_printed = True

                if line[:1] == '#' or not line:
                    continue

                if if_end and line != 'endif':
                    continue

                if if_next and line[:5] != 'elseif' and line != 'else' and line != 'endif':
                    continue

                if line == 'else':
                    if if_satisfied:
                        if_end=True
                    else:
                        if_next = False
                    continue
                # /else

                elif line == 'endif':
                    if_satisfied = False
                    if_next = False
                    if_end = False
                    continue
                # /endif

                elif line == 'scrape':
                    if not v['s_url']:
                        return None
                    if verbose:
                        print "Scraping %r" % v['s_url']
                    scrape = scrape + 1
                    if v['s_method'] == 'get':
                        kwargs = {}
                        if v.get('s_cookie',''):
                            kwargs['Cookie'] = v['s_cookie']
                        v['htmRaw'] = browser.get(v['s_url'], referer=v['s_referer'], **kwargs).read()
                    elif v['s_method'] == 'post':
                        kwargs = {}
                        if v.get('s_cookie',''):
                            kwargs['Cookie'] = v['s_cookie']
                        res = browser.get(v['s_url'], referer=v['s_referer'], data=v['s_postdata'], **kwargs)
                        if v['s_action'] == 'read':
                            v['htmRaw'] = res.read()
                        elif v['s_action'] == 'geturl':
                            v['v1'] = res.geturl()
                        res.close()
                    if v['s_action'] == 'read' and v['regex'] > '':
                        v['nomatch'] = ''
                        rep['nomatch'] = ''
                        for i in xrange(1, 11):
                            ke = 'v'+str(i)
                            v[ke] = ''
                            rep[ke] = ''
                        p = re.compile(v['regex'])
                        match = p.search(v['htmRaw'])
                        if match:
                            for i in xrange(1, len(match.groups())+1):
                                val = match.group(i)
                                key='v'+str(i)
                                rep[key] = val
                                v[key] = val
                        else:
                            print "Processor scrape: no match"
                            rep['nomatch'] = 1
                            v['nomatch'] = 1
                # /scrape

                elif line == 'play':
                    exflag = True
                # /play

                elif line == 'report':
                    rep['phase'] = str(phase)
                    proc_args = urllib.urlencode(rep)
                    proc_args = re.sub('v\d+=&', '&', proc_args)
                    proc_args = proc_args.replace('nomatch=&', '&')
                    proc_args=re.sub('&+','&',proc_args)
                    proc_args=re.sub('^&','',proc_args)
                # /report

                else:
                    # parse
                    match = lparse.search(line)
                    if match is None:
                        print "Processor syntax error: "+line
                        return None
                    subj = match.group(1)
                    arg = match.group(3)

                    if subj == 'if' or subj == 'elsif':
                        if if_satisfied:
                            if_end = True
                        else:
                            # process if with operators
                            match = ifparse.search(arg)
                            if match:
                                lkey = match.group(1)
                                oper = match.group(2)
                                rraw = match.group(3)
                                if oper == '=':
                                    oper = '=='
                                if lkey not in v:
                                    v[lkey] = ''
                                if rraw[0:1] == "'":
                                    rside = rraw[1:]
                                else:
                                    if rraw not in v:
                                        v[rraw] = ''
                                    rside = v[rraw]
                                _bool = eval("v[lkey]" + oper + "rside")
                            else:
                                # process single if argument
                                if arg not in v:
                                    v[arg] = ''
                                _bool = bool(v[arg])
                        if _bool:
                            if_satisfied = True
                            if_next = False
                        else:
                            if_next = True
                        continue
                    if match.group(2) == '=':
                        # assignment operator
                        if arg[0:1] == "'":
                            v[subj]=arg[1:]
                        else:
                            if arg not in v:
                                v[arg] = ''
                            v[subj] = v[arg]
                    else:
                        # do command
                        if subj == 'verbose':
                            try: verbose = int(arg)
                            except: verbose = 0
                        elif subj == 'error':
                            print "Processing error: "+arg[1:]
                            return
                        elif subj == 'report_val':
                            match = lparse.search(arg)
                            if match is None:
                                print "Processor syntax error: "+line
                                return
                            ke = match.group(1)
                            va = match.group(3)
                            if va[0:1] == "'":
                                rep[ke] = va[1:]
                            else:
                                rep[ke] = v.get(va,'')
                        elif subj=='concat':
                            match = lparse.search(arg)
                            if match is None:
                                print "Processor syntax error: "+line
                                return
                            ke = match.group(1)
                            va = match.group(3)
                            oldtmp = v.get(ke,'')
                            if va[0:1] == "'":
                                v[ke] = v[ke] + va[1:]
                            else:
                                v[ke] = v[ke] + v.get(va,'')
                        elif subj == 'match':
                            v['nomatch'] = ''
                            rep['nomatch'] = ''
                            for i in xrange(1,11):
                                ke = 'v'+str(i)
                                v[ke] = ''
                                rep[ke] = ''
                            p = re.compile(v['regex'])
                            match = p.search(v[arg])
                            if match:
                                for i in xrange(1, len(match.group())+1):
                                    v['v%d'%i] = match.group(i)
                            else:
                                v['nomatch'] = 1
                        elif subj == 'replace':
                            # preset regex, replace var [']val
                            match = lparse.search(arg)
                            if match is None:
                                print "Processor syntax error: "+line
                                return
                            ke = match.group(1)
                            va = match.group(3)
                            if va[0:1] == "'":
                                va=va[1:]
                            else:
                                va=v.get(va, '')
                            oldtmp = v.get(ke, '') # ??
                            v[ke] = re.sub(v['regex'], va, v[ke])
                        elif subj == 'unescape':
                            oldtmp = v.get(arg, '')
                            v[arg] = urllib.unquote(oldtmp)
                        elif subj == 'debug' and verbose > 0:
                            print "Processor debug "+arg+":\n" + v.get(arg,'');
                        elif subj == 'print':
                            if arg[0:1] == "'":
                                print "Processor print: "+arg[1:]
                            else:
                                print "Processor print: "+v.get(arg,'')
                        else:
                            print "Processor error: unrecognised method '%s'" % subj

            kwargs = {}
            if v.get('s_cookie'):
                kwargs['Cookie'] = v['s_cookie']
            if byterange is not None:
                kwargs['Range'] = byterange
            print "URL: %s" % v.get('url','')
            if v.get('url',''):
                return browser.get(v['url'], **kwargs)
