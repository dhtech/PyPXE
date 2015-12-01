#!/usr/bin/env python
import logging
import threading

from pypxe import tftp
from pypxe import dhcp


dhcp_filename = 'test'


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

  tftp_server = tftp.TFTPD(
      ip='77.80.231.70',
      logger=tftp_logger)
  tftpd = threading.Thread(target=tftp_server.listen)
  tftpd.daemon = True
  tftpd.start()

  dhcp_logger = sys_logger.getChild('dhcp')
  sys_logger.info('Starting DHCP server...')
  dhcp_server = dhcp.DHCPD(
      ip='77.80.231.70',
      offer_from='77.80.231.71',
      offer_to='77.80.231.94',
      subnet_mask='255.255.255.224',
      router='77.80.231.65',
      dns_server='77.80.231.70',
      broadcast='77.80.231.95',
      file_server='77.80.231.70',
      file_name=dhcp_filename,
      use_ipxe=True,
      use_http=True,
      logger=dhcp_logger)

  dhcpd = threading.Thread(target = dhcp_server.listen)
  dhcpd.daemon = True
  dhcpd.start()

  import signal
  while True:
    signal.pause()

