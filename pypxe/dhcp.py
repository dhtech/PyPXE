'''

This file contains classes and functions that implement the PyPXE DHCP service

'''

import abc
import socket
import struct
import os
import logging
from collections import defaultdict
from time import time


class Error(Exception):
    pass


class OutOfLeasesError(Error):
    pass


class AbstractDHCPD(object):
    '''
        This class implements a DHCP Server, limited to PXE options.
        Implemented from RFC2131, RFC2132,
        https://en.wikipedia.org/wiki/Dynamic_Host_Configuration_Protocol,
        and http://www.pix.net/software/pxeboot/archive/pxespec.pdf.
    '''

    __metaclass__ = abc.ABCMeta

    def __init__(self, **server_settings):

        self.ip = server_settings.get('ip', '192.168.2.2')
        self.interface = server_settings.get('interface', '')
        self.port = server_settings.get('port', 67)
        self.offer_from = server_settings.get('offer_from', '192.168.2.100')
        self.offer_to = server_settings.get('offer_to', '192.168.2.150')
        self.subnet_mask = server_settings.get('subnet_mask', '255.255.255.0')
        self.router = server_settings.get('router', '192.168.2.1')
        self.dns_server = server_settings.get('dns_server', '8.8.8.8')
        self.broadcast = server_settings.get('broadcast', '<broadcast>')
        self.file_server = server_settings.get('file_server', '192.168.2.2')
        self.static_config = server_settings.get('static_config', dict())
        self.mode_debug = server_settings.get('mode_debug', False) # debug mode
        self.logger = server_settings.get('logger', None)
        self.magic = struct.pack('!I', 0x63825363) # magic cookie

        # setup logger
        if self.logger == None:
            self.logger = logging.getLogger('DHCP')
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
        if self.mode_debug:
            self.logger.setLevel(logging.DEBUG)

        self.logger.debug('NOTICE: DHCP server started in debug mode. DHCP server is using the following:')
        self.logger.debug('DHCP Server IP: {0}'.format(self.ip))
        self.logger.debug('DHCP Server Port: {0}'.format(self.port))

        self.logger.debug('Lease Range: {0} - {1}'.format(self.offer_from, self.offer_to))
        self.logger.debug('Subnet Mask: {0}'.format(self.subnet_mask))
        self.logger.debug('Router: {0}'.format(self.router))
        self.logger.debug('DNS Server: {0}'.format(self.dns_server))
        self.logger.debug('Broadcast Address: {0}'.format(self.broadcast))

        if self.static_config:
            self.logger.debug('Using Static Leasing')
            self.logger.debug('Using Static Leasing Whitelist: {0}'.format(self.whitelist))

        self.logger.debug('File Server IP: {0}'.format(self.file_server))

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # SO_BINDTODEVICE
        self.sock.setsockopt(socket.SOL_SOCKET, 25, self.interface + '\0')
        self.sock.bind(('', self.port))

        # key is MAC
        self.leases = defaultdict(lambda: {'ip': '', 'expire': 0})

    def get_namespaced_static(self, path, fallback = {}):
        statics = self.static_config
        for child in path.split('.'):
            statics = statics.get(child, {})
        return statics if statics else fallback

    def next_ip(self):
        '''
            This method returns the next unleased IP from range;
            also does lease expiry by overwrite.
        '''

        # if we use ints, we don't have to deal with octet overflow
        # or nested loops (up to 3 with 10/8); convert both to 32-bit integers

        # e.g '192.168.1.1' to 3232235777
        encode = lambda x: struct.unpack('!I', socket.inet_aton(x))[0]

        # e.g 3232235777 to '192.168.1.1'
        decode = lambda x: socket.inet_ntoa(struct.pack('!I', x))

        from_host = encode(self.offer_from)
        to_host = encode(self.offer_to)

        # pull out already leased IPs
        leased = [self.leases[i]['ip'] for i in self.leases
                if self.leases[i]['expire'] > time()]

        # convert to 32-bit int
        leased = map(encode, leased)

        # loop through, make sure not already leased and not in form X.Y.Z.0
        for offset in xrange(to_host - from_host):
            if (from_host + offset) % 256 and from_host + offset not in leased:
                return decode(from_host + offset)
        raise OutOfLeasesError('Ran out of IP addresses to lease!')

    def tlv_encode(self, tag, value):
        '''Encode a TLV option.'''
        return struct.pack('BB', tag, len(value)) + value

    def tlv_parse(self, raw):
        '''Parse a string of TLV-encoded options.'''
        ret = {}
        while(raw):
            [tag] = struct.unpack('B', raw[0])
            if tag == 0: # padding
                raw = raw[1:]
                continue
            if tag == 255: # end marker
                break
            [length] = struct.unpack('B', raw[1])
            value = raw[2:2 + length]
            raw = raw[2 + length:]
            if tag in ret:
                ret[tag].append(value)
            else:
                ret[tag] = [value]
        return ret

    def get_mac(self, mac):
        '''
            This method converts the MAC Address from binary to
            human-readable format for logging.
        '''
        return ':'.join(map(lambda x: hex(x)[2:].zfill(2), struct.unpack('BBBBBB', mac))).upper()

    def craft_header(self, message):
        '''This method crafts the DHCP header using parts of the message.'''
        xid, flags, yiaddr, giaddr, chaddr = struct.unpack('!4x4s2x2s4x4s4x4s16s', message[:44])
        client_mac = chaddr[:6]

        # op, htype, hlen, hops, xid
        response =  struct.pack('!BBBB4s', 2, 1, 6, 0, xid)
        response += struct.pack('!HHI', 0, 0, 0) # secs, flags, ciaddr
        if self.leases[client_mac]['ip']: # OFFER
            offer = self.leases[client_mac]['ip']
        else: # ACK
            offer = self.get_namespaced_static('dhcp.binding.{0}.ipaddr'.format(self.get_mac(client_mac)))
            offer = offer if offer else self.next_ip()
            self.leases[client_mac]['ip'] = offer
            self.leases[client_mac]['expire'] = time() + 86400
            self.logger.info('New Assignment - MAC: {0} -> IP: {1}'.format(self.get_mac(client_mac), self.leases[client_mac]['ip']))
        response += socket.inet_aton(offer) # yiaddr
        response += socket.inet_aton(self.file_server) # siaddr
        response += socket.inet_aton('0.0.0.0') # giaddr
        response += chaddr # chaddr

        # BOOTP legacy pad
        response += chr(0) * 64 # server name
        response += chr(0) * 128
        response += self.magic # magic section
        return (client_mac, response)

    def craft_options(self, opt53, client_mac):
        '''
            This method crafts the DHCP option fields
            opt53:
                2 - DHCPOFFER
                5 - DHCPACK
            See RFC2132 9.6 for details.
        '''
        response = self.tlv_encode(53, chr(opt53)) # message type, OFFER
        response += self.tlv_encode(54, socket.inet_aton(self.ip)) # DHCP Server
        subnet_mask = self.get_namespaced_static('dhcp.binding.{0}.subnet'.format(self.get_mac(client_mac)), self.subnet_mask)
        response += self.tlv_encode(1, socket.inet_aton(subnet_mask)) # subnet mask
        router = self.get_namespaced_static('dhcp.binding.{0}.router'.format(self.get_mac(client_mac)), self.router)
        response += self.tlv_encode(3, socket.inet_aton(router)) # router
        dns_server = self.get_namespaced_static('dhcp.binding.{0}.dns'.format(self.get_mac(client_mac)), [self.dns_server])
        dns_server = ''.join([socket.inet_aton(i) for i in dns_server])
        response += self.tlv_encode(6, dns_server)
        response += self.tlv_encode(51, struct.pack('!I', 86400)) # lease time

        # TFTP Server OR HTTP Server; if iPXE, need both
        response += self.tlv_encode(66, self.file_server)
        response += self.tlv_encode(67, self.filename(client_mac) + chr(0))
        response += '\xff'
        return response

    @abc.abstractmethod
    def filename(self, client_mac):
        '''Return the filename to use for the request.'''
        pass

    def dhcp_offer(self, message):
        '''This method responds to DHCP discovery with offer.'''
        client_mac, header_response = self.craft_header(message)
        options_response = self.craft_options(2, client_mac) # DHCPOFFER
        response = header_response + options_response
        self.logger.debug('DHCPOFFER - Sending the following')
        self.logger.debug('<--BEGIN HEADER-->')
        self.logger.debug('{0}'.format(repr(header_response)))
        self.logger.debug('<--END HEADER-->')
        self.logger.debug('<--BEGIN OPTIONS-->')
        self.logger.debug('{0}'.format(repr(options_response)))
        self.logger.debug('<--END OPTIONS-->')
        self.logger.debug('<--BEGIN RESPONSE-->')
        self.logger.debug('{0}'.format(repr(response)))
        self.logger.debug('<--END RESPONSE-->')
        self.sock.sendto(response, (self.broadcast, 68))

    def dhcp_ack(self, message):
        '''This method responds to DHCP request with acknowledge.'''
        client_mac, header_response = self.craft_header(message)
        options_response = self.craft_options(5, client_mac) # DHCPACK
        response = header_response + options_response
        self.logger.debug('DHCPACK - Sending the following')
        self.logger.debug('<--BEGIN HEADER-->')
        self.logger.debug('{0}'.format(repr(header_response)))
        self.logger.debug('<--END HEADER-->')
        self.logger.debug('<--BEGIN OPTIONS-->')
        self.logger.debug('{0}'.format(repr(options_response)))
        self.logger.debug('<--END OPTIONS-->')
        self.logger.debug('<--BEGIN RESPONSE-->')
        self.logger.debug('{0}'.format(repr(response)))
        self.logger.debug('<--END RESPONSE-->')
        self.sock.sendto(response, (self.broadcast, 68))

    def listen(self):
        '''Main listen loop.'''
        while True:
            message, address = self.sock.recvfrom(1024)
            [client_mac] = struct.unpack('!28x6s', message[:34])
            self.logger.debug('Received message')
            self.logger.debug('<--BEGIN MESSAGE-->')
            self.logger.debug('{0}'.format(repr(message)))
            self.logger.debug('<--END MESSAGE-->')
            self.leases[client_mac]['options'] = self.tlv_parse(message[240:])
            self.logger.debug('Parsed received options')
            self.logger.debug('<--BEGIN OPTIONS-->')
            self.logger.debug('{0}'.format(repr(self.leases[client_mac]['options'])))
            self.logger.debug('<--END OPTIONS-->')
            type = ord(self.leases[client_mac]['options'][53][0]) # see RFC2131, page 10
            if type == 1:
                self.logger.info('Received DHCPOFFER')
                try:
                    self.dhcp_offer(message)
                except OutOfLeasesError:
                    self.logger.critical('Ran out of leases')
            elif type == 3 and address[0] == '0.0.0.0':
                self.logger.info('Received DHCPACK')
                self.dhcp_ack(message)
