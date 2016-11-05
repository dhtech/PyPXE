#!/usr/bin/env python
import logging
import socket
import threading
import urllib2

from pypxe import tftp
from pypxe import dhcp
from pypxe import dns
from dnslib import A


DEPLOY_URL = 'https://deploy.tech.dreamhack.se/tftp/{filename}'


class HttpBackedClient(tftp.AbstractClient):
  def __init__(self, *args):
    super(HttpBackedClient, self).__init__(*args)
    self.fh = None

  def check_file(self, filename):
    url = DEPLOY_URL.format(filename=filename)
    request = urllib2.Request(url)
    request.get_method = lambda: 'HEAD'
    try:
      response = urllib2.urlopen(request, timeout=2)
    except urllib2.URLError:
      logging.exception('Unable to access %s', url)
      return False
    return True

  def next_block(self):
    if self.fh is None:
      return None
    return self.fh.read(self.blksize)

  def prepare_request(self, filename):
    url = DEPLOY_URL.format(filename=filename)
    self.fh = urllib2.urlopen(url, timeout=2)
    self.filesize = 0


class TFTPD(tftp.BaseTFTPD):
  def __init__(self, **kwargs):
    super(TFTPD, self).__init__(HttpBackedClient, **kwargs)


class DHCPD(dhcp.AbstractDHCPD):

  def filename(self, client_mac):
    return 'undionly.kpxe'


class DNSD(dns.AbstractDNSD):

  def lookup(self, qtype, domain):
    if qtype != 'A':
      return tuple()
    if domain == 'ftp.se.debian.org.':
      return (A('10.32.12.1'), )
    else:
      try:
        return (A(socket.gethostbyname(domain)),)
      except:
        return tuple()

if __name__ == '__main__':
  # setup main logger
  sys_logger = logging.getLogger('deployd')
  handler = logging.StreamHandler()
  formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s %(message)s')
  handler.setFormatter(formatter)
  sys_logger.addHandler(handler)
  sys_logger.setLevel(logging.INFO)

  tftp_logger = sys_logger.getChild('tftp')
  sys_logger.info('Starting TFTP server...')

  tftp_server = TFTPD(
      ip='10.32.12.1',
      logger=tftp_logger)
  tftpd = threading.Thread(target=tftp_server.listen)
  tftpd.daemon = True
  tftpd.start()

  dhcp_logger = sys_logger.getChild('dhcp')
  sys_logger.info('Starting DHCP server...')
  dhcp_server = DHCPD(
      interface='vlan552',
      ip='10.32.12.1',
      offer_from='10.32.12.10',
      offer_to='10.32.12.250',
      subnet_mask='255.255.255.0',
      router='10.32.12.1',
      dns_server='10.32.12.1',
      broadcast='10.32.12.255',
      file_server='10.32.12.1',
      logger=dhcp_logger)

  dhcpd = threading.Thread(target = dhcp_server.listen)
  dhcpd.daemon = True
  dhcpd.start()

  dns_logger = sys_logger.getChild('dns')
  sys_logger.info('Starting DNS server...')

  dns_server = DNSD(
      ip='10.32.12.1',
      logger=dns_logger)
  dns_server = threading.Thread(target=dns_server.listen)
  dns_server.daemon = True
  dns_server.start()

  import signal
  while True:
    signal.pause()

