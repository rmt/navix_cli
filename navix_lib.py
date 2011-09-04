#
# A library of helper classes and methods for Navi-X CLI
#
import urllib2
import nipl
import logging

DEBUGLEVEL=0

class Nookie(object):
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


def make_request(url, processor=None):
    "Given an Item instance, return an open Request, or None"
    if processor:
        parser = nipl.NIPLParser(
            url=url,
            proc=processor,
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

def do_request(url, processor=None):
    request = make_request(url, processor)
    try:
        if request:
            return urllib2.urlopen(request)
    except urllib2.HTTPError, e:
        print e
    return None
