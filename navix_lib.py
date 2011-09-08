#
# A library of helper classes and methods for Navi-X CLI
#
import mimetypes
import logging
import os.path
import urllib2
import urllib
import time
import nipl
import sys
import re

DEBUGLEVEL=0

class Pager(object):
    "A piped Pager class, falling back to straight stdout"
    def __init__(self, cmd=None):
        "eg. Pager(['less', '-eFX'])"
        self.pipe = None
        if cmd:
            try:
                self.pipe = Popen(cmd, stdin=PIPE)
            except:
                pass
    def write(self, buf):
        "Write buf to pager"
        if self.pipe:
            self.pipe.stdin.write(buf)
        else:
            sys.stdout.write(buf)
    def close(self):
        "When finished, call pager.close()"
        if self.pipe:
            self.pipe.stdin.close()
            self.pipe.wait()

def guess_extension_from_url(url):
    """
    Given a URL, try to work out the file extension
    """
    m = re.search(r"\.(?P<ext>avi|flv|mpg|mp4|mpeg|ogv|mp3|flac|ogg|mkv)([?&]|$)", url, re.I)
    if m:
        return "."+m.group('ext').lower()
    # otherwise try mimetypes.guess_type
    url = urllib.splitquery(url)[0] # split query from end
    mimetype, _ = mimetypes.guess_type(url)
    if mimetype:
        ext = mimetypes.guess_extension(mimetype)
        if ext:
            return ext
    return None


def guess_extension_from_response(response):
    """
    Given a response object, try to work out the file extension based
    firstly on the URL, and then on the Content-Type
    """
    if not response:
        return None
    # try from request URL
    ext = guess_extension_from_url(response.geturl())
    if ext:
        return ext
    # try from content type
    ct = response.info().get('content-type')
    if ct:
        mimetype = ct.split(';')[0]
        ext = mimetypes.guess_extension(mimetype)
        if ext:
            return ext
    return None


def ratestring(kbps):
    "Return the download rate in a human-friendly format."
    if kbps > 1024:
        return "%0.2f MB/s" % (kbps/1024)
    return "%d KB/s" % (kbps)


def download(res, filename, stdout=sys.stdout):
    """Download the HTTP response object to the given filename
    using VT100 codes to interactively show the progress"""
    length = res.info().get('Content-Length', None)
    strlength = length and ("%dk" % (int(length)/1024)) or "Unknown"
    i = 0 # if the destination file exists, add .$i to it
    starttime = time.time() # for rate calculation
    chunksize = 4096
    buf = res.read(chunksize)
    bytecount = len(buf)
    out = None
    while buf:
        if out is None:
            fname = filename
            i = 1
            if res.getcode() == 206: # partial file transfer
                # TODO / FIXME - seek to right location, in-case
                out = file(fname, "ab")
            else:
                while os.path.exists(fname):
                    fname = "%s.%d" % (fname, i)
                    i = i + 1
                out = file(fname, "wb")
            print >>stdout, "Downloading to %s" % fname
        out.write(buf)
        buf = res.read(chunksize)
        bytecount += len(buf)
        kbps = int(bytecount / (int(time.time() - starttime) or 1) / 1024.0)
        if chunksize == 4096 and kbps > 409600 and bytecount > 1048576:
            chunksize = 8192
        stdout.write("\r\033[K[%dk / %s] (~%s)" % (bytecount//1024, strlength, ratestring(kbps)))
        stdout.flush()
    out.close()
    print >>stdout, ""


class Nookie(object):
    "A Nookie is a NIPL cookie"
    def __init__(self, name, value, expiry=None):
        self.name = name
        self.value = value
        self.expiry = expiry or None

class NookieStore(object):
    def __init__(self):
        self.nookies = {}
    def set(self, name, value, expiry=None):
        self.nookies[name] = value
    def get(self, name, default=''):
        return self.nookies.get(name, default)
    def __getitem__(self, name):
        return self.get(name)


# getRemote function, as expected by nipl
def getRemote(url, paramargs=None):
    """
    getRemote tasks a URL and input dictionary and returns an output dict.

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
    assert url != None
    args = {
        'agent' : 'Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.9.0.4) Gecko/2008102920 Firefox/3.0.4',
        'referer': '',
        'cookie': '',
        'method': 'get',
        'action': 'read',
        'postdata': '&',
        'headers': {},
    }
    args.update(paramargs or {})

    # TODO - if url is navi-x server, add login info to cookie

    # make request header dict
    hdr = {
        'User-Agent': args['agent'],
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }
    if args['referer']:
        hdr['referer'] = args['referer']
    if args['cookie']:
        hdr['cookie'] = args['cookie']
    hdr.update(args['headers'])

    # make request, either a get or a POST (provide data)
    if args['method'] == 'get':
        req = urllib2.Request(url=url, headers=hdr)
    elif args['method'] == 'post':
        req = urllib2.Request(url=url, data=(args['postdata'] or '&'), headers=hdr)
    else:
        raise TypeError("Unsupported request method: %s" % args['method'])

    # open request using a cookieprocessor
    cookieprocessor = urllib2.HTTPCookieProcessor()
    httphandler = urllib2.HTTPHandler(debuglevel=globals().get('DEBUGLEVEL',0))
    opener = urllib2.build_opener(cookieprocessor, httphandler)
    response=opener.open(req)

    # process cookies which are now stored in response.cookiejar
    cookies = {}
    for cookie in cookieprocessor.cookiejar:
        cookies[cookie.name] = cookie.value

    oret = {
        "headers": response.info(),
        "geturl": response.geturl(),
        "cookies": cookies,
        "content": "",
    }

    if args['action'] == 'read':
        oret['content'] = response.read()

    response.close()
    return oret


def make_request(url, processor_url=None):
    "Given a URL & process URL, return an open Request, or None"
    if processor_url:
        parser = nipl.NIPLParser(
            url=url,
            proc=processor_url,
            getRemote=getRemote,
            nookiestore=NookieStore(),
            logger=logging,
            platform='Linux',
            version='3.7')
        res = parser.parse()
        request = urllib2.Request(res['url'])
        request.add_header('User-Agent', res['agent'] or nipl.HTTP_USER_AGENT)
        request.add_header('Referer', res['referer'])
        return request
    request = urllib2.Request(url)
    request.add_header('User-Agent', nipl.HTTP_USER_AGENT)
    return request


def do_request(url, processor_url=None):
    "Call make_request & then call urllib2.urlopen, returning response"
    request = make_request(url, processor_url)
    try:
        if request:
            return urllib2.urlopen(request)
    except urllib2.HTTPError, e:
        print e
    return None

