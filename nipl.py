# vim: filetype=python expandtab softtabstop=4
# encoding: utf-8
#
# Copyright (C) 2011  Robert Thomson
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

"""
Provides the NIPLParser class to run NIPL processors.

See: http://navix.turner3d.net/proc_docs/

It takes the following arguments to __init__:
    url - URL of media item.
    proc - URL of processor to call.
    getRemote - a method to call to download. See getRemote below.
    nookiestore - an object to get/set "nookies". See nookiestore below.
    logger - a logger interface with methods 'info', 'debug', and 'error'
    platform - Linux, Windows, MacOS/X, etc.
    version - version of NAVI-X that we're emulating.

To run the NIPL parser, call instance.parse() which will return a dictionary
with the following items:

   url: Real URL of media content
   referer: Referer URL to set to retrieve content
   agent: User-Agent string to set to retrieve content
   player: XBMC-specific
   swfurl: XBMC-specific
   playpath: XBMC-specific

NookieStore
-----------

Nookies are processor specific cookies that are stored locally and made available
to NIPL scripts.

The instance must have two methods defined:
  * get(varname)
  * set(varname, value, [expirytime])

Expiry time is a string and can be suffixed with 'h' for hour, 'm' for minutes,
or 'd' for days.

getRemote
---------

The getRemote function is used by the NIPL parser to make a HTTP request.
It takes a URL and a dictionary as input and returns a dictionary as output.

    Input dictionary:
        agent: User-Agent header (defaults to Mozilla under Windows)
        referer: Referer header
        cookie: Cookie header
        method: 'get' or 'post'
        action: 'read' or 'headers'
        postdata: URL-encoded POST data if method is 'post'
        headers: python dict of extra headers

    Output dictionary:
        cookies: python dict of returned cookies
        headers: python dict of returned headers
        content: string containing content (if action was 'read') or ""
        geturl: Actual URL of request
"""

import urllib
import urllib2
import cookielib
import os.path
import time
import re

NAVIX_PLATFORM = "unknown" # default platform if not specified
NAVIX_VERSION = "3.7" # default version if not specified

HTTP_USER_AGENT="Mozilla/5.0 (Windows; U; Windows NT 5.1; en-GB; rv:1.9.0.3) Gecko/2008092417 Firefox/3.0.3"
RE_IFEXPR=re.compile('^(?P<var>[^<>=!]+)\s*(?P<op>[!<>=]+)\s*(?P<value>.+)$')
RE_LPARSE=re.compile('^(?P<var>[^ =]+)=(?P<value>.+)$')

EVAL_OPS = {
    '<': lambda x,y: x<y,
    '<=': lambda x,y: x<=y,
    '>': lambda x,y: x>y,
    '>=': lambda x,y: x>=y,
    '=': lambda x,y: x==y,
    '==': lambda x,y: x==y,
    '!=': lambda x,y: x!=y,
    '<>': lambda x,y: x!=y,
}

class NIPLException(Exception):
    "Base exception class for NIPL"
    pass

class NIPLPlay(NIPLException):
    "Ready to play - cleanup & return values"
    pass

class NIPLReport(NIPLException):
    "Make a call to the processor"

class NoRegexException(NIPLException):
    "regex Variable not set"
    pass

class NoMatchException(NIPLException):
    "Match not found"
    pass

class UnknownNIPLCommand(NIPLException):
    "Thrown if no do_$cmd was found"
    pass

# Parser for the NIPL language
class NIPLParser:
    def __init__(self, url, proc, getRemote, nookiestore, logger, platform=NAVIX_PLATFORM, version=NAVIX_VERSION):
        self.getRemote = getRemote
        self.nookiestore = nookiestore
        self.logger = logger
        self.version = version
        self.platform = platform
        self.forcev2 = False
        self.phase = 0
        self.verbose = 0
        self.proc = proc
        self.standard_vars = {
            's_url'     : url, # URL to scrape
        }
        self.init_vars()

    def debug(self, msg):
        "Debugging output only"
        self.logger.debug(msg)
    def info(self, msg):
        "Information output only"
        self.logger.info(msg)
    def error(self, msg):
        "Any errors"
        self.logger.error(msg)

    def init_vars(self):
        "Initialise a few variables for a new processor run"
        vars = {
            's_method'  : 'get', # get, post
            's_action'  : 'read', # read, headers, geturl
            's_agent'   : HTTP_USER_AGENT,
            's_referer' : '',
            's_cookie'  : '',
            's_postdata': '', # only used if s_method is 'post', url encoded
        }
        self.standard_vars.update(vars)
        self.s_headers = {}
        self.headers = {}
        self.cookies = {}
        self.report_val = {}
        self.match = None

    def getdot_nookies(self, name):
        "Call nookiestore.get(varname)"
        return self.nookiestore.get(name)

    def setdot_nookies(self, name, value):
        "Call nookiestore.set(varname, value, expirytime)"
        self.debug("setdot_nookies(%s,%s)" % (name, value,))
        self.nookiestore.set(name, value, self.get('nookie_expires') or None)

    def getdot_cookies(self, name):
        "Collection: cookies - Cookies received from remote"
        return self.cookies.get(name, '')

    #def setdot_cookies(self, name, value):
    #    self.cookies[name] = value

    def getdot_headers(self, name):
        "Collection: headers - Headers from remote"
        return self.headers.get(name, '')

    def setdot_s_headers(self, name, value):
        "Collection: s_headers - Headers to send in request"
        self.debug("setdot_s_headers(%s,%s)" % (name, value,))
        self.s_headers[name] = value

    def getdot_s_headers(self, name):
        "Collection: s_headers - Headers to send in request"
        return self.s_headers.get(name, '')

    def set_s_method(self, value):
        "Magic var: s_method (valid: get,post)"
        self.debug("set_s_method(%s)" % (value,))
        value = value.strip().lower()
        if value == 'get' or value == 'post':
            self.standard_vars['s_method'] = value
        else:
            raise NIPLException("Invalid value for s_method variable: %s" % value)

    def set_s_action(self, value):
        "Magic var: s_action (valid: read,headers,geturl)"
        value = value.strip().lower()
        self.debug("set_s_action(%s)" % (value,))
        if value in ('read', 'headers', 'geturl',):
            self.standard_vars['s_action'] = value
        else:
            raise NIPLException("Invalid value for s_action variable: %s" % value)

    def get_phase(self):
        "Magic var: phase of processing - increased with each scrape"
        return str(self.phase)

    def get_nomatch(self):
        "Magic var: returns 1 if the last match/scrape didn't match, or 0"
        if not self.match:
            return '1'
        return '0'

    def expand(self, string):
        "Expand to literal string or variable value"
        if string[0:1] == "'":
            return string[1:]
        # get variable
        return self.get(string)

    def get(self, name):
        """
        Lookup the value for the given variable in the following order:
        * If the variable name has a dot in it, look for methods
          called self.getdot_$name and call that if it exists.
        * If it matches the regex ^v(\d+)$ return the n'th group
          in self.match, or '' if no match or no group.
        * Look for self.get_$name and return its result if it exists.
        * Lookup in self.standard_vars or '' if it doesn't exist
        """
        name = name.strip()
        # handle collections specially
        if "." in name:
            n, name = name.split(".",1) # eg cookies, foo
            func = getattr(self, 'getdot_'+n, None)
            if func:
                return func(name)
        # look for magic function
        func = getattr(self, 'get_'+name, None)
        if func:
            return func()
        # otherwise return the value from standard_vars, or ''
        return self.standard_vars.get(name, '')

    def getvar(self, name):
        "Return standard variable value only"
        return self.standard_vars[name]

    def setvar(self, name, value):
        "Set the variable $name to literal value"
        if len(value) > 256:
            self.debug("setvar('%s','%s...')" % (name, value[:256],))
        else:
            self.debug("setvar('%s','%s')" % (name, value,))
        self.standard_vars[name] = value

    def set(self, name, value):
        """
        Set the variable $name to literal or looked-up-variable $value.
        * If value starts with ', use the remainder as a literal string
          or else call self.get(value)
        * If '.' is in name, call self.setdot_$name(name, value) if it exists.
        * Call self.set_$name(value) if it exists.
        * Otherwise: self.standard_vars[name] = value
        """
        self.debug('set("%s","%s")' % (name, value))
        name = name.strip()
        value = self.expand(value)
        # try setdot_$namespace if '.' in $varname ($namespace is before the .)
        if "." in name: # eg. cookies.foo
            n, name = name.split(".",1) # eg. cookies, foo
            func = getattr(self, 'setdot_'+n, None) # eg. setdot_cookies
            if func:
                func(name, value) # eg. setdot_cookies(foo, value)
                return
            raise NIPLException("Invalid variable: %s.%s" % (n, name))
        # try set_$varname
        func = getattr(self, 'set_'+name, None)
        if func:
            func(value)
            return
        self.setvar(name, value)

    def do_concat(self, line):
        "'concat var 'string' or 'concat var othervar'"
        var, value = line.split(" ",1)
        self.setvar(var, self.get(var)+self.expand(value))

    def do_verbose(self, line):
        "Set verbosity number"
        self.verbose = int(line.strip())

    def do_debug(self, line):
        if self.verbose > 0:
            self.debug(line)

    def do_error(self, line):
        self.logger.error(line)
        raise NIPLException("Script error: %s" % (line,))

    def _do_match(self, regex, value):
        "Do the match, populate v1..vN"
        self.match = re.search(regex, value)
        # remove match variables (up until v9 should suffice)
        for i in range(1,10):
            vname = 'v%d' % i
            if vname in self.standard_vars:
                del self.standard_vars[vname]
        #
        if self.match:
            self.debug("Successfully matched /%s/" % (regex,))
            # set v1..vN
            groups = self.match.groups()
            for i,val in zip(range(len(groups)), groups):
                self.setvar('v%d' % (i+1), val)
        else:
            self.debug("Could not match /%s/" % (regex,))

    def do_match(self, line):
        value = self.get(line) # match only against variables
        regex = self.getvar('regex')
        if not regex:
            raise NoRegexException("regex must be set to a valid Regex before matching")
        self._do_match(regex, value)

    def do_play(self, line):
        "Instruct XBMC to play - just exit and let the vars be used"
        return True

    def do_print(self, line):
        "print line to log, regardless of verbosity"
        self.debug(self.expand(line))

    def do_replace(self, line):
        "Replace v1 in regex match of variable arg1 with value of arg2"
        var, arg = line.split(' ',1)
        arg = self.expand(arg)
        regex = self.getvar('regex')
        oldtmp = self.getvar(var)
        self.debug('Calling re.sub("%s", "%s", "%s")' % (regex, arg, oldtmp))
        self.setvar(var, re.sub(regex, arg, oldtmp))
        self.debug("Replace %s: old=\"%s\" new=\"%s\"" % (var, oldtmp, self.getvar(var)))

    def do_report(self, line):
        """
        End the processor cycle and perform a new query to the processor
        URL using the values stored in the report variables. In addition,
        increase and send the phase variable.
        """
        raise NIPLReport("Call NIPL processor again")

    def do_report_val(self, line):
        "Add an additional URL argument"
        k,v = line.split('=',1)
        self.report_val[k.strip()] = self.expand(v)

    def request(self):
        """
        1. Collect request variables from namespace
        2. Perform request with getRemote
        3. Populate response variables in namespace
        """
        # set request arguments
        url = self.getvar('s_url')
        if not url:
            raise NIPLException("s_url must be set.")
        d = {
            'action': self.getvar('s_action'),
            'method': self.getvar('s_method'),
            'headers': self.s_headers,
            'referer': self.getvar('s_referer'),
            'agent': self.getvar('s_agent'),
            'cookie': self.getvar('s_cookie'),
            'postdata': self.getvar('s_postdata')
        }
        # log the upcoming request
        if self.phase>0:
            self.info("phase %d, scraping %s" % (self.phase, url))
        else:
            self.info("scraping %s" % (url,))
        # call getRemote
        res = self.getRemote(url, d)
        # set response vars & collections
        location_header = res.get('headers',{}).get('location','')
        self.setvar('geturl', location_header)
        if d['action'] == 'read':
            self.setvar('htmRaw', res.get('content',''))
        elif d['action'] == 'headers':
            self.setvar('htmRaw', '') # TODO: is this current behaviour?
        elif d['action'] == 'geturl':
            self.match = None
            self.setvar('v1', location_header)
            self.report_val['v1'] = location_header
        self.cookies = res.get('cookies',{})
        self.headers = res.get('headers',{})
        return res.get('content','')

    def do_scrape(self, line):
        """
        Retrieves the content of the remote document specified in the s_url
        variable and places it in the htmRaw variable. If the s_action variable
        is set to its default value of read and the value of regex is defined,
        the regular expression will be executed and the captures placed both in
        the v1…vn variables as well as in the corresponding v1…vn report
        variables.

        In cases where a remote script is performing a page forward at the
        server level, the s_action variable can be set to geturl. In this case,
        the htmRaw variable will not be populated, but instead the v1 variable
        and v1 report variable will be set to the forwarded URL.
        """
        action = self.get('s_action')
        self.request()
        regex = self.get('regex')
        htmRaw = self.get('htmRaw')
        if action == 'read' and regex:
            self._do_match(regex, htmRaw)

    def do_unescape(self, line):
        "Unescape variable"
        var = line.strip()
        self.setvar(var, urllib.unquote(self.get(var)))

    def evalexpr(self, expr):
        "Given a NIPL if expression, return True or False"
        m = RE_IFEXPR.search(expr)
        if m:
            var, op, arg = m.group(1), m.group(2), m.group(3)
            var = self.get(var)
            arg = self.get(arg)
            if op in EVAL_OPS:
                return EVAL_OPS[op](var,arg)
            else:
                raise NIPLException("Invalid operator %s in expression %s" % (op,expr))
        elif self.get(expr): # TODO: is '0' meant to be False?
            return True
        return False

    def execute(self, line):
        "Evaluate a single line (w/o control flow)"
        # is it a variable assignment?
        m = RE_LPARSE.search(line)
        if m:
            self.set(m.group('var'), m.group('value'))
            return

        # otherwise try a command
        args = line.split(' ',1)
        cmd = args[0]
        args = len(args) > 1 and args[1] or ''
        cmdx = getattr(self, 'do_'+cmd, None)
        if cmdx:
            self.debug("Calling do_%s(\"%s\")" % (cmd,args))
            return cmdx(args)
        else:
            raise UnknownNIPLCommand("Unknown NIPL command: %s" % (cmd,))

    def parse_proc_v1(self, prociter):
        """Parse v1 Processor directives"""
        prociter = iter(prociter)
        url = prociter.next()
        try:
            regex = prociter.next()
        except StopIteration:
            # no regex, must be the final URL
            return {
                "url": url,
                "referer": self.get('s_url'),
                "agent": self.get('agent'),
                "player": self.get('player'),
                "swfurl": self.get('swfurl'),
                "playpath": self.get('playpath'),
            }
        self.setvar('s_url', url)
        self.setvar('regex', regex)
        self.do_scrape('')
        raise NIPLReport("Next phase")

    def parse_proc_v2(self, prociter):
        """
        Given a prociter yielding lines of a processor file,
        Then evaluate lines with respect to conditionals,
             setting variables,
             and calling commands.
        """
        iftrue = True # in a running if block?
        if_was_true = False # evaluate else or future elseifs?
        in_if = False # currently in an if/elseif/else/endif block
        for line in prociter:
            line = line.lstrip().rstrip("\r\n")
            self.debug("proc input ::: %s" % (line,))

            # ignore comments and blank lines
            if line.startswith("#") or line.strip() == '':
                continue

            # handle conditionals
            if in_if:
                if line == "if":
                    raise NIPLException("Nested if clauses are not supported")
                if line == "endif":
                    in_if = False
                    if_was_true = False
                    continue
                elif line == "else":
                    in_if = True
                    iftrue = not if_was_true
                    continue
                elif line.startswith("elseif "):
                    in_if = True
                    if not if_was_true:
                        iftrue = self.evalexpr(line[7:].lstrip())
                        if_was_true = iftrue
                    continue
                elif not iftrue:
                    # skip to next line
                    continue
            elif line.startswith("if "):
                in_if = True
                iftrue = self.evalexpr(line[3:].lstrip())
                continue

            # execute line
            try:
                stop = self.execute(line)
            except NIPLPlay:
                stop = True
            except:
                raise

            # abort if a command returned True
            if stop == True: # finished processing
                break
        return {
            "url": self.get('url'),
            "referer": self.get('referer'),
            "agent": self.get('agent'),
            "player": self.get('player'),
            "swfurl": self.get('swfurl'),
            "playpath": self.get('playpath'),
        }

    def fetch_and_run_proc(self, last_calls=None):
        "Fetch the processor - last_calls is modified if a list"
        procurl = self.proc
        procargs = {}
        procargs.update(self.report_val)

        if self.phase > 0:
            procargs['phase'] = str(self.phase)
            if self.match:
                groups = self.match.groups()
                for i,val in zip(range(len(groups)), groups):
                    procargs['v%d' % (i+1)] = val
        else:
            procargs['url'] = self.get('s_url')
            

        # check for a loop by making a unique value for this request
        if last_calls != None:
            unique = procurl
            for k,v in sorted(procargs.items()):
                unique += "&%s=%s" % (k,v)
            if unique in last_calls:
                raise NIPLLoopException("Loop detected. Calling processor twice with identical arguments")
            last_calls.append(unique)

        if '?' in procurl:
            procurl = procurl + "&" + urllib.urlencode(procargs)
        else:
            procurl = procurl + "?" + urllib.urlencode(procargs)

        self.info("getting filter: %s" % procurl)
        # provide version & platform to processor as a cookie
        cookie = "version=%s; platform=%s" % (self.version, self.platform)
        # make request
        res = self.getRemote(procurl, {"cookie": cookie})
        proclines = res['content'].split('\n')

        # initialize vars for a fresh processor run
        self.init_vars()

        if not proclines:
            self.info("processor URL returned nothing.")
            raise NIPLException("Processor URL returned nothing.")
        #
        if proclines[0].strip() == 'v2':
            proclines = proclines[1:]
            self.forcev2 = True # once v2, always v2
        #
        if self.forcev2:
            self.debug("parsing v2 proc")
            return self.parse_proc_v2(proclines)
        else:
            self.debug("parsing v1 proc")
            print '\n'.join(proclines)
            return self.parse_proc_v1(proclines)

    def parse(self):
        lastcalls = []
        while True:
            try:
                return self.fetch_and_run_proc(lastcalls)
            except NIPLReport:
                self.phase += 1
                pass # and loop
            except Exception, e:
                self.error(str(e))
                raise

