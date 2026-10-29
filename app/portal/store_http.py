"""Bounded, read-only store requests. Resolve once and pin public IP + TLS SNI."""
import http.client,ipaddress,json,socket,ssl
from urllib.parse import urlsplit
from django.core.exceptions import ValidationError

MAX_RESPONSE=5*1024*1024

def origin(value):
    try:
        url=urlsplit(value.strip());host=(url.hostname or '').encode('idna').decode('ascii').lower()
        if url.scheme!='https' or not host or url.username or url.password or url.port not in (None,443) or url.query or url.fragment:raise ValueError()
        if any(segment in ('.','..') for segment in url.path.split('/')) or any(c not in '/-_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789' for c in url.path):raise ValueError()
        if host=='localhost' or '.' not in host:raise ValueError()
        try:address=ipaddress.ip_address(host)
        except ValueError:address=None
        if address is not None:raise ValueError()  # Use a public DNS hostname for TLS identity.
        return 'https://'+host+url.path.rstrip('/')
    except (ValueError,UnicodeError):raise ValidationError('Use a public HTTPS store address without credentials, query parameters or a custom port.')

def public_addresses(host):
    try:
        result=[]
        for record in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM):
            value=record[4][0];address=ipaddress.ip_address(value)
            transition=address.version==6 and (address.ipv4_mapped or address.sixtofour or address.teredo or address in ipaddress.ip_network('64:ff9b::/96') or address in ipaddress.ip_network('64:ff9b:1::/48'))
            if not address.is_global or address.is_multicast or transition:raise ValidationError('This store resolves to a private, reserved or translated address. No credentials were sent.')
            if value not in result:result.append(value)
        if not result:raise OSError()
        return result
    except (OSError,ValueError):raise ValidationError('The public store address could not be resolved. No credentials were sent.')

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,address):super().__init__(host,timeout=12,context=ssl.create_default_context());self.address=address
    def connect(self):
        raw=socket.create_connection((self.address,443),timeout=self.timeout)
        try:self.sock=self._context.wrap_socket(raw,server_hostname=self.host)
        except Exception:raw.close();raise

def request_json(base,path,headers,body=None):
    base=origin(base);url=urlsplit(base)
    if not path.startswith('/') or path.startswith('//') or '\r' in path or '\n' in path:raise ValidationError('Unsupported store request.')
    # Only adapter-owned read endpoints may send credentials.
    allowed=(url.hostname=='www.wixapis.com' and path=='/ecom/v1/orders/search' and body is not None or
             url.hostname=='api.squarespace.com' and path.startswith('/1.0/commerce/orders?') and body is None or
             url.hostname.endswith('.myshopify.com') and path=='/admin/api/2026-10/graphql.json' and body is not None or
             path.startswith(url.path+'/wp-json/wc/v3/orders?') and body is None)
    if not allowed:raise ValidationError('Unsupported read-only store endpoint.')
    addresses=public_addresses(url.hostname)
    connection=PinnedHTTPS(url.hostname,addresses[0])
    try:
        payload=json.dumps(body,allow_nan=False).encode() if body is not None else None
        connection.request('POST' if body is not None else 'GET',path,body=payload,headers={'Accept':'application/json','User-Agent':'Crema/0.2','Content-Type':'application/json',**headers})
        response=connection.getresponse()
        if response.status!=200:
            message={401:'Authorization failed. Check the saved store credentials.',403:'Access denied. Grant read access to orders for this store.',429:'The store rate limit was reached. Wait before retrying.'}.get(response.status,'The store request failed. Check its address, API access and service status.')
            raise ValidationError(message)
        data=response.read(MAX_RESPONSE+1)
        if len(data)>MAX_RESPONSE:raise ValidationError('The store response is too large. No orders from this page were changed.')
        def pairs(items):
            result={}
            for key,value in items:
                if key in result:raise ValueError('Duplicate key')
                result[key]=value
            return result
        value=json.loads(data,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Non-finite number')))
        if not isinstance(value,(dict,list)):raise ValueError('Invalid response')
        return value,{k.lower():v for k,v in response.getheaders()}
    except ValidationError:raise
    except (OSError,ValueError,http.client.HTTPException,UnicodeError):raise ValidationError('The store returned an unreadable response or the connection failed. Reviewed work was preserved.')
    finally:connection.close()
