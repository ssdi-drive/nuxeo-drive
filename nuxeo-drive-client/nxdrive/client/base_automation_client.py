"""Common Nuxeo Automation client utilities."""

import sys
import base64
import json
import urllib2
import pycurl
import mimetypes
import random
import time
import os
import tempfile
from urllib import urlencode
from nxdrive.logging_config import get_logger
from nxdrive.client.common import FILE_BUFFER_SIZE
from nxdrive.client.common import DEFAULT_IGNORED_PREFIXES
from nxdrive.client.common import DEFAULT_IGNORED_SUFFIXES
from nxdrive.client.common import safe_filename


log = get_logger(__name__)


DEVICE_DESCRIPTIONS = {
    'linux2': 'Linux Desktop',
    'darwin': 'Mac OSX Desktop',
    'cygwin': 'Windows Desktop',
    'win32': 'Windows Desktop',
}


def get_proxies_for_handler(proxy_settings):
    """Return a pair containing proxy string and exceptions list"""
    if proxy_settings.config == 'None':
        # No proxy, return an empty dictionary to disable
        # default proxy detection
        return {}, None
    elif proxy_settings.config == 'System':
        # System proxy, return None to use default proxy detection
        return None, None
    else:
        # Manual proxy settings, build proxy string and exceptions list
        if proxy_settings.authenticated:
            proxy_string = ("%s://%s:%s@%s:%s") % (
                                proxy_settings.proxy_type,
                                proxy_settings.username,
                                proxy_settings.password,
                                proxy_settings.server,
                                proxy_settings.port)
        else:
            proxy_string = ("%s://%s:%s") % (
                                proxy_settings.proxy_type,
                                proxy_settings.server,
                                proxy_settings.port)
        proxies = {proxy_settings.proxy_type: proxy_string}
        if proxy_settings.exceptions and proxy_settings.exceptions.strip():
            proxy_exceptions = [e.strip() for e in
                                proxy_settings.exceptions.split(',')]
        else:
            proxy_exceptions = None
        return proxies, proxy_exceptions


# def get_proxy_handler(proxies, proxy_exceptions=None, url=None):
#     if proxies is None:
#         # No proxies specified, use default proxy detection
#         return urllib2.ProxyHandler()
#     else:
#         # Use specified proxies (can be empty to disable default detection)
#         if proxies:
#             if proxy_exceptions is not None and url is not None:
#                 hostname = urlparse(url).hostname
#                 for exception in proxy_exceptions:
#                     if exception == hostname:
#                         # Server URL is in proxy exceptions,
#                         # don't use any proxy
#                         proxies = {}
#         return urllib2.ProxyHandler(proxies)


class PycURLHTTPError(Exception):

    def __init__(self, code):
        self.code = code


class Unauthorized(Exception):

    def __init__(self, server_url, user_id, code=403):
        self.server_url = server_url
        self.user_id = user_id
        self.code = code

    def __str__(self):
        return ("'%s' is not authorized to access '%s' with"
                " the provided credentials" % (self.user_id, self.server_url))


class BaseAutomationClient(object):
    """Client for the Nuxeo Content Automation HTTP API

    timeout is a short timeout to avoid having calls to fast JSON operations
    to block and freeze the application in case of network issues.

    blob_timeout is long (or infinite) timeout dedicated to long HTTP
    requests involving a blob transfer.

    Supports HTTP proxies.
    If proxies is given, it must be a dictionary mapping protocol names to
    URLs of proxies.
    If proxies is None, uses default proxy detection:
    read the list of proxies from the environment variables <PROTOCOL>_PROXY;
    if no proxy environment variables are set, then in a Windows environment
    proxy settings are obtained from the registry's Internet Settings section,
    and in a Mac OS X environment proxy information is retrieved from the
    OS X System Configuration Framework.
    To disable autodetected proxy pass an empty dictionary.
    """
    # TODO: handle system proxy detection under Linux,
    # see https://jira.nuxeo.com/browse/NXP-12068

    # Used for testing network errors
    _error = None

    # Parameters used when negotiating authentication token:
    application_name = 'Nuxeo Drive'

    permission = 'ReadWrite'

    def __init__(self, server_url, user_id, device_id, client_version,
                 proxies=None, proxy_exceptions=None,
                 password=None, token=None, repository="default",
                 ignored_prefixes=None, ignored_suffixes=None,
                 timeout=20, blob_timeout=None, cookie_jar=None,
                 upload_tmp_dir=None, check_suspended=None):

        # Function to check during long-running processing like upload /
        # download if the synchronization thread needs to be suspended
        self.check_suspended = check_suspended

        self.timeout = timeout
        self.blob_timeout = blob_timeout
        if ignored_prefixes is not None:
            self.ignored_prefixes = ignored_prefixes
        else:
            self.ignored_prefixes = DEFAULT_IGNORED_PREFIXES

        if ignored_suffixes is not None:
            self.ignored_suffixes = ignored_suffixes
        else:
            self.ignored_suffixes = DEFAULT_IGNORED_SUFFIXES

        self.upload_tmp_dir = (upload_tmp_dir if upload_tmp_dir is not None
                               else tempfile.gettempdir())

        if not server_url.endswith('/'):
            server_url += '/'
        self.server_url = server_url

        # TODO: actually use the repository info in the requests
        self.repository = repository

        self.user_id = user_id
        self.device_id = device_id
        self.client_version = client_version
        self._update_auth(password=password, token=token)

        # TODO: handle CookieJar
#         self.cookie_jar = cookie_jar
#         cookie_processor = urllib2.HTTPCookieProcessor(
#             cookiejar=cookie_jar)

        # TODO: handle proxy
#         Get proxy handler
#         proxy_handler = get_proxy_handler(proxies,
#                                           proxy_exceptions=proxy_exceptions,
#                                           url=self.server_url)

        # Build URL openers
#         self.opener = urllib2.build_opener(cookie_processor, proxy_handler)
#         self.streaming_opener = urllib2.build_opener(cookie_processor,
#                                                      proxy_handler,
#                                                      *get_handlers())

        # Set Proxy flag
        self.is_proxy = False
#         for handler in self.opener.handlers:
#             if isinstance(handler, ProxyHandler):
#                 if handler.proxies:
#                     self.is_proxy = True

        self.automation_url = server_url + 'site/automation/'
        self.batch_upload_url = 'batch/upload'
        self.batch_execute_url = 'batch/execute'

        self.fetch_api()

    def make_raise(self, error):
        """Make next calls to server raise the provided exception"""
        self._error = error

    def fetch_api(self):
        base_error_message = (
            "Failed to connect to Nuxeo server %s"
        ) % (self.server_url)
        url = self.automation_url
        headers = self._get_common_headers()
#         cookies = self._get_cookies()
#         log.trace("Calling %s with headers %r and cookies %r",
#             url, headers, cookies)
        log.trace("Calling %s with headers %r",
            url, headers)
        req = pycurl.Curl()
        req.setopt(pycurl.URL, str(url))
        req.setopt(pycurl.HTTPHEADER, headers)
        req.setopt(pycurl.TIMEOUT, self.timeout)
        try:
            _, body = self._perform_request(req)
        except Exception as e:
            msg = base_error_message
            if hasattr(e, 'msg'):
                msg = msg + ": " + e.msg
            e.msg = msg
            raise e

        status_code = int(req.getinfo(pycurl.HTTP_CODE))
        if status_code == 401 or status_code == 403:
            raise Unauthorized(self.server_url, self.user_id, status_code)
        elif status_code >= 400:
            msg = base_error_message + "\nHTTP error %d" % status_code
            raise ValueError(msg)

        response = json.loads(body)
        self.operations = {}
        for operation in response["operations"]:
            self.operations[operation['id']] = operation

    def execute(self, command, op_input=None, timeout=-1,
                check_params=True, void_op=False, **params):
        """Execute an Automation operation"""
        if self._error is not None:
            # Simulate a configurable (e.g. network or server) error for the
            # tests
            raise self._error
        if check_params:
            self._check_params(command, params)

        url = self.automation_url + command
        headers = [
            "Content-Type: application/json+nxrequest",
            "Accept: application/json+nxentity, */*",
            "X-NXDocumentProperties: *",
        ]
        if void_op:
            headers.extend("X-NXVoidOperation: true")
        headers.extend(self._get_common_headers())

        json_struct = {'params': {}}
        for k, v in params.items():
            if v is None:
                continue
            if k == 'properties':
                s = ""
                for propname, propvalue in v.items():
                    s += "%s=%s\n" % (propname, propvalue)
                json_struct['params'][k] = s.strip()
            else:
                json_struct['params'][k] = v
        if op_input:
            json_struct['input'] = op_input
        log.trace("Dumping JSON structure: %s", json_struct)
        data = json.dumps(json_struct)

#         cookies = self._get_cookies()
#         log.trace("Calling %s with headers %r, cookies %r"
#                   " and JSON payload %r",
#             url, headers, cookies,  data)
        log.trace("Calling %s with headers %r "
                  " and JSON payload %r",
            url, headers, data)
        req = pycurl.Curl()
        req.setopt(pycurl.URL, str(url))
        req.setopt(pycurl.HTTPHEADER, headers)
        timeout = self.timeout if timeout == -1 else timeout
        req.setopt(pycurl.TIMEOUT, self.timeout)
        req.setopt(pycurl.POST, 1)
        req.setopt(pycurl.POSTFIELDS, data)
        try:
            headers, body = self._perform_request(req)
        except Exception as e:
            self._log_details(e)
            raise

        status_code = int(req.getinfo(pycurl.HTTP_CODE))
        if status_code >= 400:
            raise PycURLHTTPError(status_code)

        return self._read_response(headers, body, url)

    def execute_with_blob_streaming(self, command, file_path, filename=None,
                                    mime_type=None, **params):
        """Execute an Automation operation using a batch upload as an input

        Upload is streamed.
        """
        batch_id = self._generate_unique_id()
        upload_result = self.upload(batch_id, file_path, filename=filename,
                                    mime_type=mime_type)
        if upload_result['uploaded'] == 'true':
            return self.execute_batch(command, batch_id, '0', **params)
        else:
            raise ValueError("Bad response from batch upload with id '%s'"
                             " and file path '%s'" % (batch_id, file_path))

    def upload(self, batch_id, file_path, filename=None, file_index=0,
               mime_type=None):
        """Upload a file through an Automation batch

        Uses poster.httpstreaming to stream the upload
        and not load the whole file in memory.
        """
        # Request URL
        url = self.automation_url.encode('ascii') + self.batch_upload_url

        # HTTP headers
        if filename is None:
            filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        if mime_type is None:
            ctype, _ = mimetypes.guess_type(filename)
            if ctype:
                mime_type = ctype
            else:
                mime_type = "application/octet-stream"
        # Quote UTF-8 filenames even though JAX-RS does not seem to be able
        # to retrieve them as per: https://tools.ietf.org/html/rfc5987
        filename = safe_filename(filename)
        quoted_filename = urllib2.quote(filename.encode('utf-8'))
        headers = [
            "X-Batch-Id: " + str(batch_id),
            "X-File-Idx: " + str(file_index),
            "X-File-Name: " + str(quoted_filename),
            "X-File-Size: " + str(file_size),
            "X-File-Type: " + str(mime_type),
            "Content-Type: application/octet-stream",
            "Content-Length: " + str(file_size),
        ]
        headers.extend(self._get_common_headers())

        # Request data
        input_file = open(file_path, 'rb')
        # Use file system block size if available for streaming buffer
        if sys.platform != 'win32':
            fs_block_size = os.fstatvfs(input_file.fileno()).f_bsize
        else:
            fs_block_size = FILE_BUFFER_SIZE
        log.trace("Using file system block size"
                  " for the streaming upload buffer: %u bytes", fs_block_size)

        # Execute request
#         cookies = self._get_cookies()
#         log.trace("Calling %s with headers %r and cookies %r for file %s",
#             url, headers, cookies, file_path)
        log.trace("Calling %s with headers %r for file %s",
            url, headers, file_path)

        req = pycurl.Curl()
        req.setopt(pycurl.URL, str(url))
        req.setopt(pycurl.HTTPHEADER, headers)
        req.setopt(pycurl.POST, 1)
        if self.blob_timeout:
            req.setopt(pycurl.TIMEOUT, self.blob_timeout)
        self._set_streaming_option(req, input_file, fs_block_size)
        try:
            headers, body = self._perform_request(req)
        except Exception as e:
            self._log_details(e)
            raise
        finally:
            input_file.close()

        return self._read_response(headers, body, url)

    def execute_batch(self, op_id, batch_id, file_idx, **params):
        """Execute a file upload Automation batch"""
        return self.execute(self.batch_execute_url,
                     operationId=op_id, batchId=batch_id, fileIdx=file_idx,
                     check_params=False, **params)

    def is_addon_installed(self):
        return 'NuxeoDrive.GetRoots' in self.operations

    def request_token(self, revoke=False):
        """Request and return a new token for the user"""
        base_error_message = (
            "Failed to connect to Nuxeo server %s with user %s"
            " to acquire a token"
        ) % (self.server_url, self.user_id)

        parameters = {
            'deviceId': self.device_id,
            'applicationName': self.application_name,
            'permission': self.permission,
            'revoke': 'true' if revoke else 'false',
        }
        device_description = DEVICE_DESCRIPTIONS.get(sys.platform)
        if device_description:
            parameters['deviceDescription'] = device_description
        url = self.server_url + 'authentication/token?'
        url += urlencode(parameters)

        headers = self._get_common_headers()
#         cookies = self._get_cookies()
#         log.trace("Calling %s with headers %r and cookies %r",
#                 url, headers, cookies)
        log.trace("Calling %s with headers %r",
                url, headers)

        req = pycurl.Curl()
        req.setopt(pycurl.URL, str(url))
        req.setopt(pycurl.HTTPHEADER, headers)
        req.setopt(pycurl.TIMEOUT, self.timeout)
        try:
            _, token = self._perform_request(req)
        except Exception as e:
            if hasattr(e, 'msg'):
                e.msg = base_error_message + ": " + e.msg
            raise

        status_code = int(req.getinfo(pycurl.HTTP_CODE))
        if status_code == 401 or status_code == 403:
            raise Unauthorized(self.server_url, self.user_id, status_code)
        elif status_code == 404:
            # Token based auth is not supported by this server
            return None
        elif status_code >= 400:
            msg = base_error_message + ": HTTP error %d" % status_code
            raise ValueError(msg)

#         cookies = self._get_cookies()
#         log.trace("Got token '%s' with cookies %r", token, cookies)
        log.trace("Got token '%s'", token)
        # Use the (potentially re-newed) token from now on
        if not revoke:
            self._update_auth(token=token)
        return token

    def revoke_token(self):
        self.request_token(revoke=True)

    def wait(self):
        self.execute("NuxeoDrive.WaitForAsyncCompletion")

    def make_tmp_file(self, content):
        fd, path = tempfile.mkstemp(suffix=u'-nxdrive-file-to-upload',
                                   dir=self.upload_tmp_dir)
        with open(path, "wb") as f:
            f.write(content)
        os.close(fd)
        return path

    def _update_auth(self, password=None, token=None):
        """Select the most appropriate auth headers based on credentials"""
        if token is not None:
            self.auth = ('X-Authentication-Token', token)
        elif password is not None:
            basic_auth = 'Basic %s' % base64.b64encode(
                    self.user_id + ":" + password).strip()
            self.auth = ("Authorization", basic_auth)
        else:
            raise ValueError("Either password or token must be provided")

    def _get_common_headers(self):
        """Headers to include in every HTTP requests

        Includes the authentication heads (token based or basic auth if no
        token).

        Also include an application name header to make it possible for the
        server to compute access statistics for various client types (e.g.
        browser vs devices).

        """
        return [
            'X-User-Id: ' + str(self.user_id),
            'X-Device-Id: ' + str(self.device_id),
            'X-Client-Version: ' + str(self.client_version),
            'User-Agent: ' + (
                str(self.application_name) + "/" + str(self.client_version)),
            'X-Application-Name: ' + str(self.application_name),
            str(self.auth[0]) + ': ' + str(self.auth[1]),
            'Cache-Control: no-cache',
        ]

#     def _get_cookies(self):
#         return list(self.cookie_jar) if self.cookie_jar is not None else []

    def _check_params(self, command, params):
        if command not in self.operations:
            raise ValueError("'%s' is not a registered operations." % command)
        method = self.operations[command]
        required_params = []
        other_params = []
        for param in method['params']:
            if param['required']:
                required_params.append(param['name'])
            else:
                other_params.append(param['name'])

        for param in params.keys():
            if (not param in required_params
                and not param in other_params):
                raise ValueError("Unexpected param '%s' for operation '%s"
                                 % (param, command))
        for param in required_params:
            if not param in params:
                raise ValueError(
                    "Missing required param '%s' for operation '%s'" % (
                        param, command))

        # TODO: add typechecking

    def _read_response(self, headers, body, url):
        content_type = headers.get('Content-Type', '')
#         cookies = self._get_cookies()
        if content_type.startswith("application/json"):
#             log.trace("Response for '%s' with cookies %r and JSON payload: %r",
#                 url, cookies, s)
            log.trace("Response for '%s' with JSON payload: %r",
                url, body)
            return json.loads(body) if body else None
        else:
#             log.trace("Response for '%s' with cookies %r and content-type: %r",
#                 url, cookies, content_type)
            log.trace("Response for '%s' with content-type: %r",
                url, content_type)
            return body

    def _log_details(self, e):
        if hasattr(e, "fp"):
            detail = e.fp.read()
            try:
                exc = json.loads(detail)
                log.debug(exc['message'])
                log.debug(exc['stack'], exc_info=True)
            except:
                # Error message should always be a JSON message,
                # but sometimes it's not
                log.debug(detail)

    def _generate_unique_id(self):
        """Generate a unique id based on a timestamp and a random integer"""

        return str(time.time()) + '_' + str(random.randint(0, 1000000000))

    def _perform_request(self, req):

        header_list = []
        body = []

        def write_headers(buf):
            header_list.append(buf)

        def write_data(chunk):
            body.append(chunk)
            return len(chunk)

        req.setopt(pycurl.WRITEFUNCTION, write_data)
        req.setopt(pycurl.HEADERFUNCTION, write_headers)
        req.perform()
        headers = {}
        for header in header_list:
            if ':' in header:
                name, value = header.split(":", 1)
                headers[name.strip()] = value.strip()
        return headers, ''.join(body)

    def _set_streaming_option(self, req, file_object, buffer_size):

        # TODO: use buffer_size for READFUNCTION
        def read_data(size):
            # Check if synchronization thread was suspended
            if self.check_suspended is not None:
                self.check_suspended('File upload: %s' % file_object.name)
            return file_object.read(size)

        req.setopt(pycurl.READFUNCTION, read_data)
